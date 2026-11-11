import asyncio
import threading
import time
import unittest
from unittest.mock import patch, MagicMock

from capture import CaptureManager


class FakeCapture:
    """假采集器：模拟 DouyinCommentCapture 生命周期，不开浏览器"""

    instances = []

    def __init__(self, url=None, store=None):
        self.url = url
        self.store = store
        self._stop = threading.Event()
        self.stopped = False
        FakeCapture.instances.append(self)

    def stop(self):
        self.stopped = True
        self._stop.set()

    async def run(self):
        while not self._stop.is_set():
            await asyncio.sleep(0.05)


def _make_manager():
    FakeCapture.instances = []
    return CaptureManager(store=MagicMock())


class TestCaptureManager(unittest.TestCase):
    """F04：动态输入 URL 后的采集生命周期管理"""

    def test_start_sets_running_status(self):
        """start 后状态为 running 且记录 URL"""
        m = _make_manager()
        try:
            status = m.start("https://live.douyin.com/aaa", capture_factory=FakeCapture)
            self.assertTrue(status["running"])
            self.assertEqual(status["url"], "https://live.douyin.com/aaa")
            self.assertEqual(m.status()["url"], "https://live.douyin.com/aaa")
        finally:
            m.stop()

    def test_stop_clears_running_status(self):
        """stop 后状态为 not running"""
        m = _make_manager()
        m.start("https://live.douyin.com/aaa", capture_factory=FakeCapture)
        status = m.stop()
        self.assertFalse(status["running"])
        self.assertTrue(FakeCapture.instances[0].stopped, "旧采集器应收到 stop")

    def test_restart_with_new_url_stops_old(self):
        """换 URL 重新 start：旧采集器停止，新 URL 生效"""
        m = _make_manager()
        try:
            m.start("https://live.douyin.com/aaa", capture_factory=FakeCapture)
            old = FakeCapture.instances[0]
            m.start("https://live.douyin.com/bbb", capture_factory=FakeCapture)
            self.assertTrue(old.stopped, "重启前应先停止旧采集")
            self.assertEqual(m.status()["url"], "https://live.douyin.com/bbb")
            self.assertTrue(m.status()["running"])
        finally:
            m.stop()

    def test_status_not_running_initially(self):
        """初始状态：未启动"""
        m = _make_manager()
        s = m.status()
        self.assertFalse(s["running"])
        self.assertIsNone(s["url"])


class TestCaptureApi(unittest.TestCase):
    """F04：URL 输入相关 API 校验"""

    def setUp(self):
        import app as app_module
        self.app_module = app_module
        self.client = app_module.app.test_client()
        # 替换模块级 manager，避免路由触发真实浏览器线程
        self.manager_mock = MagicMock()
        self.manager_mock.start.return_value = {"running": True, "url": "https://live.douyin.com/x"}
        self.manager_mock.stop.return_value = {"running": False, "url": None}
        self.manager_mock.status.return_value = {"running": False, "url": None}
        patcher = patch.object(app_module, "manager", self.manager_mock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_start_empty_url_returns_400(self):
        """空 URL → 400"""
        r = self.client.post("/api/capture/start", json={"url": "  "})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(self.manager_mock.start.called)

    def test_start_invalid_url_returns_400(self):
        """非 http(s) URL → 400"""
        r = self.client.post("/api/capture/start", json={"url": "not-a-url"})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(self.manager_mock.start.called)

    def test_start_valid_url_calls_manager(self):
        """合法 URL → 200，调用 manager.start"""
        url = "https://live.douyin.com/12345"
        r = self.client.post("/api/capture/start", json={"url": url})
        self.assertEqual(r.status_code, 200)
        self.manager_mock.start.assert_called_once_with(url)
        self.assertTrue(r.get_json()["running"])

    def test_stop_calls_manager(self):
        """POST /api/capture/stop → 200 并调用 manager.stop"""
        r = self.client.post("/api/capture/stop")
        self.assertEqual(r.status_code, 200)
        self.manager_mock.stop.assert_called_once()

    def test_status_returns_manager_status(self):
        """GET /api/capture/status → 返回 manager 状态"""
        r = self.client.get("/api/capture/status")
        self.assertEqual(r.status_code, 200)
        self.assertIn("running", r.get_json())


if __name__ == "__main__":
    unittest.main(verbosity=2)
