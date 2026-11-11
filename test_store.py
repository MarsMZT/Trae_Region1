import os
import shutil
import tempfile
import unittest
from store import CommentStore


def _make_store():
    """用临时目录构造独立 store，避免污染真实 comments.db"""
    tmpdir = tempfile.mkdtemp(prefix="tdd_store_")
    db = os.path.join(tmpdir, "t.db")
    log = os.path.join(tmpdir, "t.jsonl")
    return CommentStore(db_path=db, log_path=log), tmpdir


class TestStoreDedup(unittest.TestCase):
    """T01/T02：评论去重"""

    def setUp(self):
        self.store, self.tmpdir = _make_store()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_T01_same_user_same_content_dedup(self):
        """T01：同一用户名+内容出现两次，仅保存一条"""
        comments = [
            {"username": "userA", "content": "你好", "raw_text": "userA:你好"},
            {"username": "userA", "content": "你好", "raw_text": "userA:你好"},
        ]
        saved = self.store.save(comments)
        self.assertEqual(len(saved), 1, "第二条应被指纹去重")
        self.assertEqual(self.store.stats()["total"], 1)

    def test_T02_different_user_same_content_kept(self):
        """T02：不同用户名相同内容，两条各自保留"""
        comments = [
            {"username": "userA", "content": "好看", "raw_text": "userA:好看"},
            {"username": "userB", "content": "好看", "raw_text": "userB:好看"},
        ]
        saved = self.store.save(comments)
        self.assertEqual(len(saved), 2, "不同用户应各自保留")
        self.assertEqual(self.store.stats()["total"], 2)

    def test_T02_dedup_across_batches(self):
        """T02 补充：跨批次重复同样去重"""
        self.store.save([{"username": "u", "content": "x", "raw_text": "u:x"}])
        saved2 = self.store.save([{"username": "u", "content": "x", "raw_text": "u:x"}])
        self.assertEqual(len(saved2), 0, "跨批次重复应被去重")
        self.assertEqual(self.store.stats()["total"], 1)


class TestStoreStats(unittest.TestCase):
    """T06/T07：统计"""

    def setUp(self):
        self.store, self.tmpdir = _make_store()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_T06_empty_db_stats(self):
        """T06：空数据库请求统计"""
        s = self.store.stats()
        self.assertEqual(s["total"], 0)
        self.assertEqual(s["unique_users"], 0)
        self.assertEqual(s["top_users"], [])
        self.assertEqual(s["timeline"], [])

    def test_T07_five_comments_stats(self):
        """T07：插入5条后统计"""
        comments = [
            {"username": "userA", "content": "a1", "raw_text": "userA:a1"},
            {"username": "userA", "content": "a2", "raw_text": "userA:a2"},
            {"username": "userB", "content": "b1", "raw_text": "userB:b1"},
            {"username": "userC", "content": "c1", "raw_text": "userC:c1"},
            {"username": "userD", "content": "d1", "raw_text": "userD:d1"},
        ]
        self.store.save(comments)
        s = self.store.stats()
        self.assertEqual(s["total"], 5)
        self.assertEqual(s["unique_users"], 4)
        # TOP1 应为 userA（2条）
        self.assertEqual(s["top_users"][0]["name"], "userA")
        self.assertEqual(s["top_users"][0]["count"], 2)
        # timeline 分组总数应等于评论总数
        self.assertGreaterEqual(len(s["timeline"]), 1)
        self.assertEqual(sum(item["count"] for item in s["timeline"]), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
