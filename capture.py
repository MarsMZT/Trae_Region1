import asyncio
import logging
import threading
from playwright.async_api import async_playwright
from config import LIVE_URL, CAPTURE_INTERVAL, HEADLESS
from store import CommentStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("capture")

# 页面评论提取脚本：多选择器兜底 + 系统消息过滤 + 去重
# 评论容器选择器规则见 spaceDD.md「评论提取选择器」：按优先级命中第一个即停止
EXTRACT_JS = r"""
() => {
    // 评论容器选择器（优先级 1→4，命中第一个即停止，见 spaceDD.md）
    //   优先级1 [class*="webcast-chatroom___list"]   抖音直播评论列表容器（2026-10 实测）
    //   优先级2 [data-e2e="chat-list"]               旧版标准 data-e2e 属性
    //   优先级3 [class*="chatroom"][class*="list"]   类名同时含 chatroom 和 list
    //   优先级4 [class*="im-list-content"]           即时消息列表容器
    // 全部未命中时 container 为 null，本轮返回空数组跳过，不报错（对应 T04）
    const container = document.querySelector('[class*="webcast-chatroom___list"]')
        || document.querySelector('[data-e2e="chat-list"]')
        || document.querySelector('[class*="chatroom"][class*="list"]')
        || document.querySelector('[class*="im-list-content"]');
    if (!container) return [];

    const results = [];
    // 评论项：优先匹配 webcast-chatroom___item，兜底容器内所有 div
    let items = container.querySelectorAll('div.webcast-chatroom___item');
    if (!items.length) items = container.querySelectorAll('div');
    items.forEach(item => {
        const text = (item.innerText || '').trim();
        if (!text || text.length < 2) return;
        // 过滤系统消息
        if (text.includes('进入直播间') || text.includes('关注了主播')) return;

        // 抖音评论格式为「用户名：内容」，按第一个冒号分隔；
        // 无冒号的条目（如「xxx来了」系统消息）跳过
        const sep = text.search(/[:：]/);
        if (sep < 0) return;
        const name = text.slice(0, sep).trim();
        const content = text.slice(sep + 1).trim();
        if (content) {
            results.push({ username: name, content: content, raw_text: text });
        }
    });

    // 本地去重
    const seen = new Set();
    return results.filter(r => {
        const k = r.username + '|' + r.content;
        if (seen.has(k)) return false;
        seen.add(k);
        return true;
    });
}
"""


class DouyinCommentCapture:
    """抖音直播间评论采集器"""

    def __init__(self, url=LIVE_URL, store=None):
        self.url = url
        self.store = store or CommentStore()
        self.seen = set()
        # F04：用 threading.Event 以便从 Flask 主线程跨线程停止采集循环
        self._stop = threading.Event()

    def stop(self):
        """请求停止采集（线程安全），循环在下一次检查时退出"""
        self._stop.set()

    async def run(self):
        log.info("启动 Playwright，打开直播间: %s", self.url)
        async with async_playwright() as p:
            # 禁用自动化控制特征，避免抖音风控将页面导航到 about:blank
            browser = await p.chromium.launch(
                headless=HEADLESS,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            # 隐藏 navigator.webdriver，规避自动化检测
            await context.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )
            page = await context.new_page()
            await page.goto(self.url, wait_until="domcontentloaded")
            log.info("页面已加载，等待 10 秒让评论加载（如需登录请在浏览器中手动完成）...")
            # 分段等待，保证等待期间收到 stop 也能及时退出
            for _ in range(10):
                if self._stop.is_set():
                    log.info("收到停止请求，退出采集")
                    return
                await asyncio.sleep(1)

            log.info("开始循环采集评论，间隔 %ss", CAPTURE_INTERVAL)
            while not self._stop.is_set():
                try:
                    comments = await page.evaluate(EXTRACT_JS)
                    new = [c for c in comments
                           if c["username"] + "|" + c["content"] not in self.seen]
                    if new:
                        for c in new:
                            self.seen.add(c["username"] + "|" + c["content"])
                        saved = self.store.save(new)
                        log.info("采集到 %d 条新评论", len(saved))
                except Exception as e:
                    log.warning("采集异常: %s", e)
                await asyncio.sleep(CAPTURE_INTERVAL)
            log.info("采集循环已停止: %s", self.url)


class CaptureManager:
    """F04：管理采集线程的生命周期，支持动态启动/停止/换 URL 重启"""

    def __init__(self, store=None):
        self._lock = threading.Lock()
        self._capture = None
        self._thread = None
        self._url = None
        self._store = store

    def start(self, url, capture_factory=None):
        """以指定 URL 启动采集；若已有任务在运行，先停止再重启"""
        factory = capture_factory or DouyinCommentCapture
        with self._lock:
            self._stop_locked()
            capture = factory(url=url, store=self._store)
            thread = threading.Thread(
                target=self._thread_target, args=(capture,), daemon=True
            )
            thread.start()
            self._capture = capture
            self._thread = thread
            self._url = url
            return self._status_locked()

    def stop(self):
        with self._lock:
            self._stop_locked()
            return self._status_locked()

    def status(self):
        with self._lock:
            return self._status_locked()

    def _status_locked(self):
        running = self._thread is not None and self._thread.is_alive()
        return {"running": running, "url": self._url}

    def _stop_locked(self):
        if self._capture is not None:
            self._capture.stop()
        if self._thread is not None and self._thread.is_alive():
            # 等待采集循环退出并关闭浏览器
            self._thread.join(timeout=CAPTURE_INTERVAL + 15)
        self._capture = None
        self._thread = None

    @staticmethod
    def _thread_target(capture):
        try:
            asyncio.run(capture.run())
        except Exception as e:
            log.warning("采集线程异常退出: %s", e)


def run_capture(url=None):
    """同步入口：独立调试时直接运行采集（Web 模式请使用 CaptureManager）"""
    capture = DouyinCommentCapture(url=url or LIVE_URL)
    asyncio.run(capture.run())


if __name__ == "__main__":
    run_capture()
