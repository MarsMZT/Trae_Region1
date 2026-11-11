from app import app

# F04：采集不再随服务自动启动，由用户在仪表盘输入直播页 URL 后触发
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
