import sqlite3
import json
import threading
from datetime import datetime
from config import DB_PATH, LOG_PATH


class CommentStore:
    """评论存储层：SQLite + JSONL 双写，线程安全"""

    def __init__(self, db_path=DB_PATH, log_path=LOG_PATH):
        self.db_path = db_path
        self.log_path = log_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT,
                    content TEXT,
                    raw_text TEXT,
                    captured_at TEXT,
                    fingerprint TEXT UNIQUE
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_captured_at ON comments(captured_at)"
            )

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    @staticmethod
    def _fingerprint(username, content, raw_text):
        """生成去重指纹：用户名+内容"""
        base = (username or "").strip() + "|" + (content or "").strip()
        if not base.strip("|"):
            base = raw_text or ""
        return base

    def save(self, comments):
        """批量保存评论，自动去重，返回新写入的记录列表"""
        saved = []
        with self._lock:
            with self._get_conn() as conn:
                for c in comments:
                    fp = self._fingerprint(
                        c.get("username"), c.get("content"), c.get("raw_text", "")
                    )
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    try:
                        conn.execute(
                            "INSERT INTO comments(username,content,raw_text,captured_at,fingerprint) VALUES(?,?,?,?,?)",
                            (c.get("username", ""), c.get("content", ""),
                             c.get("raw_text", ""), now, fp),
                        )
                        record = {**c, "captured_at": now}
                        saved.append(record)
                        # 同步写入 JSONL 日志
                        with open(self.log_path, "a", encoding="utf-8") as f:
                            f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    except sqlite3.IntegrityError:
                        # 指纹重复，跳过
                        continue
        return saved

    def fetch_recent(self, limit=100):
        """获取最近的评论（倒序）"""
        with self._get_conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM comments ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def fetch_all_contents(self, limit=500):
        """获取所有评论内容（用于 AI 分析上下文）"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT username, content, captured_at FROM comments ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [{"username": r[0], "content": r[1], "time": r[2]} for r in rows]

    def stats(self):
        """聚合统计：总数、活跃用户、时间趋势"""
        with self._get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
            users = conn.execute(
                "SELECT COUNT(DISTINCT username) FROM comments WHERE username != ''"
            ).fetchone()[0]
            top_users = conn.execute(
                "SELECT username, COUNT(*) c FROM comments WHERE username != '' "
                "GROUP BY username ORDER BY c DESC LIMIT 10"
            ).fetchall()
            timeline = conn.execute(
                "SELECT substr(captured_at,1,16) m, COUNT(*) c FROM comments "
                "GROUP BY m ORDER BY m"
            ).fetchall()
            return {
                "total": total,
                "unique_users": users,
                "top_users": [{"name": u[0], "count": u[1]} for u in top_users],
                "timeline": [{"time": t[0], "count": t[1]} for t in timeline],
            }
