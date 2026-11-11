import time

import dashscope
from dashscope import Generation
from config import DASHSCOPE_API_KEY, LLM_MODEL
from store import CommentStore

dashscope.api_key = DASHSCOPE_API_KEY

SYSTEM_PROMPT = (
    "你是一个直播间评论分析助手。用户会给你一段直播间评论记录，"
    "请你基于这些评论内容回答问题。如果评论中没有相关信息，请如实说明。"
    "回答要简洁、准确，可以用条目列出。"
)


def build_context(store, limit=300):
    """从数据库提取评论，拼成 LLM 上下文文本"""
    rows = store.fetch_all_contents(limit=limit)
    if not rows:
        return "（暂无评论数据）"
    lines = [f"[{r['time']}] {r['username']}: {r['content']}" for r in rows]
    return "\n".join(lines)


def ask(question, store=None, limit=300, max_retries=3):
    """基于评论数据回答用户问题；限流（Throttling）时指数退避重试"""
    store = store or CommentStore()
    context = build_context(store, limit=limit)
    # T08：无评论时短路返回，不调用模型
    if context == "（暂无评论数据）":
        return "暂无评论数据，无法回答问题。"
    prompt = f"以下是直播间评论记录：\n{context}\n\n请回答问题：{question}"
    for attempt in range(max_retries + 1):
        try:
            resp = Generation.call(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                result_format="message",
            )
            if resp.status_code == 200:
                return resp.output.choices[0].message.content
            # 限流：暂时性错误，退避后重试
            if "Throttling" in str(getattr(resp, "code", "")):
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                return "请求过于频繁，请稍后再试。"
            return f"调用失败: {resp.code} - {resp.message}"
        except Exception as e:
            return f"调用异常: {e}"
    return "请求过于频繁，请稍后再试。"
