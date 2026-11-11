from flask import Flask, render_template, jsonify, request
from store import CommentStore
from analyzer import ask
from capture import CaptureManager

app = Flask(__name__)
store = CommentStore()
# F04：采集由界面动态输入 URL 驱动，不再随服务启动自动开始
manager = CaptureManager(store=store)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/comments")
def api_comments():
    """获取最近 100 条评论"""
    rows = store.fetch_recent(limit=100)
    return jsonify(rows)


@app.route("/api/stats")
def api_stats():
    """获取评论统计数据"""
    return jsonify(store.stats())


@app.route("/api/ask", methods=["POST"])
def api_ask():
    """基于评论的 AI 问答"""
    q = request.json.get("question", "").strip()
    if not q:
        return jsonify({"answer": "请输入问题"}), 400
    answer = ask(q, store=store)
    return jsonify({"answer": answer})


@app.route("/api/capture/start", methods=["POST"])
def api_capture_start():
    """F04：以用户输入的直播页 URL 启动（或重启）采集"""
    url = (request.json or {}).get("url", "").strip()
    if not url:
        return jsonify({"error": "请输入抖音直播页 URL"}), 400
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "URL 格式不正确，需以 http:// 或 https:// 开头"}), 400
    return jsonify(manager.start(url))


@app.route("/api/capture/stop", methods=["POST"])
def api_capture_stop():
    """F04：停止当前采集"""
    return jsonify(manager.stop())


@app.route("/api/capture/status")
def api_capture_status():
    """F04：查询采集状态"""
    return jsonify(manager.status())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
