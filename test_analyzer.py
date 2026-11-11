import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from store import CommentStore
from analyzer import build_context, ask


def _make_store_with_comments(comments=None):
    """构造独立 store，可选预填评论"""
    tmpdir = tempfile.mkdtemp(prefix="tdd_analyzer_")
    db = os.path.join(tmpdir, "t.db")
    log = os.path.join(tmpdir, "t.jsonl")
    store = CommentStore(db_path=db, log_path=log)
    if comments:
        store.save(comments)
    return store, tmpdir


class TestBuildContext(unittest.TestCase):
    """T08/T12：上下文构建"""

    def setUp(self):
        self.store, self.tmpdir = _make_store_with_comments()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_T08_empty_store_returns_placeholder(self):
        """T08：无评论时 build_context 返回占位文本"""
        ctx = build_context(self.store, limit=300)
        self.assertEqual(ctx, "（暂无评论数据）")

    @patch("analyzer.Generation.call")
    def test_T08_ask_without_comments_does_not_call_model(self, mock_call):
        """T08：无评论时 ask 不调用模型，直接返回提示"""
        result = ask("观众最关心什么", store=self.store)
        self.assertFalse(mock_call.called, "无评论时不应调用 LLM")
        self.assertIn("暂无", result)

    def test_T12_over_300_takes_latest_300(self):
        """T12：评论超过300条，build_context 只取最近300条"""
        comments = [
            {"username": f"u{i}", "content": f"c{i}", "raw_text": f"u{i}:c{i}"}
            for i in range(350)
        ]
        self.store.save(comments)
        ctx = build_context(self.store, limit=300)
        # 占位文本不会有多行，这里应是有评论的上下文
        self.assertNotEqual(ctx, "（暂无评论数据）")
        # 每条评论占一行
        lines = ctx.split("\n")
        self.assertEqual(len(lines), 300, "应只取最近300条")


class TestAskErrorHandling(unittest.TestCase):
    """T10：模型调用失败"""

    def setUp(self):
        # 预填1条评论以越过 T08 短路，到达模型调用分支
        self.store, self.tmpdir = _make_store_with_comments(
            [{"username": "u", "content": "hi", "raw_text": "u:hi"}]
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("analyzer.Generation.call")
    def test_T10_model_exception_returns_error_no_raise(self, mock_call):
        """T10：模型抛异常 → 返回错误信息，不向上抛"""
        mock_call.side_effect = Exception("timeout")
        result = ask("任意问题", store=self.store)
        self.assertIn("调用异常", result)
        self.assertIn("timeout", result)

    @patch("analyzer.Generation.call")
    def test_T10_model_non_200_returns_failure(self, mock_call):
        """T10：模型返回非200 → 返回失败信息"""
        resp = MagicMock()
        resp.status_code = 500
        resp.code = "ERR"
        resp.message = "boom"
        mock_call.return_value = resp
        result = ask("任意问题", store=self.store)
        self.assertIn("调用失败", result)


class TestRateLimitRetry(unittest.TestCase):
    """限流重试：Throttling 类错误应指数退避重试"""

    def setUp(self):
        self.store, self.tmpdir = _make_store_with_comments(
            [{"username": "u", "content": "hi", "raw_text": "u:hi"}]
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _rate_limit_resp(self):
        resp = MagicMock()
        resp.status_code = 429
        resp.code = "Throttling.RateQuota"
        resp.message = "Requests rate limit exceeded"
        return resp

    @patch("analyzer.time.sleep")
    @patch("analyzer.Generation.call")
    def test_rate_limit_retries_then_success(self, mock_call, mock_sleep):
        """前两次限流、第三次成功 → 最终返回回答，重试间隔退避"""
        ok = MagicMock()
        ok.status_code = 200
        ok.output.choices = [MagicMock(message=MagicMock(content="AI回答"))]
        mock_call.side_effect = [self._rate_limit_resp(), self._rate_limit_resp(), ok]
        result = ask("任意问题", store=self.store)
        self.assertEqual(result, "AI回答")
        self.assertEqual(mock_call.call_count, 3)
        # 退避间隔 1s、2s
        self.assertEqual([c.args[0] for c in mock_sleep.call_args_list], [1, 2])

    @patch("analyzer.time.sleep")
    @patch("analyzer.Generation.call")
    def test_rate_limit_exhausted_returns_friendly_error(self, mock_call, mock_sleep):
        """持续限流，重试耗尽 → 返回友好提示，不抛异常"""
        mock_call.return_value = self._rate_limit_resp()
        result = ask("任意问题", store=self.store)
        self.assertIn("频繁", result)
        self.assertEqual(mock_call.call_count, 4)  # 1 次原始 + 3 次重试

    @patch("analyzer.Generation.call")
    def test_non_throttle_error_no_retry(self, mock_call):
        """非限流错误不重试，直接返回"""
        resp = MagicMock()
        resp.status_code = 400
        resp.code = "InvalidParameter"
        resp.message = "bad request"
        mock_call.return_value = resp
        result = ask("任意问题", store=self.store)
        self.assertIn("调用失败", result)
        self.assertEqual(mock_call.call_count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
