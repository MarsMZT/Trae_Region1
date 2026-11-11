import os

# 抖音直播间地址（格式：https://live.douyin.com/房间号）
LIVE_URL = os.getenv("DOUYIN_LIVE_URL", "https://live.douyin.com/请替换为真实房间号")

# 通义千问 API Key（从环境变量读取，也可直接填入）
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")

# 评论采集间隔（秒）
CAPTURE_INTERVAL = 2

# 数据存储路径
DB_PATH = os.path.join(os.path.dirname(__file__), "comments.db")
LOG_PATH = os.path.join(os.path.dirname(__file__), "comments.jsonl")

# 是否无头模式运行浏览器（False = 有头，便于手动登录）
HEADLESS = False

# 通义千问模型名称（可通过环境变量 LLM_MODEL 切换，如 qwen-plus / qwen-max）
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-plus")
