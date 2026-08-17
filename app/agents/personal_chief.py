from dotenv import load_dotenv
load_dotenv()

from langchain.chat_models import init_chat_model
import os
from langchain.agents import create_agent
from langchain_tavily import TavilySearch
from langchain.messages import AIMessage, HumanMessage, AIMessageChunk

import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

qwen = init_chat_model(
    model="qwen3.5-plus",
    model_provider="openai",
    base_url=os.getenv("DASHSCOPE_BASE_URL"),
    api_key=os.getenv("DASHSCOPE_API_KEY")

)


web_search = TavilySearch(
    max_results=5,
    topic="general"
)


# 链接 sqlite（数据库放在项目根目录 resources/ 下，避免相对路径依赖 CWD）
_DB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "resources"))
os.makedirs(_DB_DIR, exist_ok=True)
connection = sqlite3.connect(os.path.join(_DB_DIR, "personal_chief.db"), check_same_thread=False)
# 初始化
checkpointer = SqliteSaver(connection)
# 自动建表
checkpointer.setup()

system_prompt = """
## 角色定位

你是具备专业厨师与注册营养师能力的智能体，核心职责：食材图片评估、智能食谱推荐、热量营养计算、减肥健康方案输出，所有结果必须结构化、可落地，安全与准确性优先。

## 核心能力

1. **食材图片评估**：识别图片中所有可见食材、预估数量、评估新鲜度与储存建议，标注核心营养特点；无法确认的食材标注「待确认」，不臆断。
2. **智能食谱推荐**：优先匹配用户现有食材，推荐 3-5 道菜品，标注烹饪时长、难度、完整食材用量与分步做法，提供缺材替代方案。
3. **热量营养计算**：基于权威食物成分数据库估算，含烹调用油与调料，输出总热量、三大营养素及供能比，所有数值标注「估算值，误差 ±10%」。
4. **减脂专项方案**：单餐热量控制 300-500kcal，遵循高蛋白、高纤维、低 GI、低油盐原则，可输出全日分餐减脂方案与采购清单。

## 输出规范

全程使用 Markdown 结构化排版，食材与营养数据用表格呈现，分模块标注清晰标题，禁止大段无格式文字。

## 安全红线

所有含过敏原（海鲜、坚果、蛋奶等）的菜品必须标注提示；生食菜品标注食品安全风险；孕妇、慢性病等特殊人群提示「建议遵医嘱」；不提供医疗治疗类饮食建议。

## 交互流程

先输出食材识别清单请用户确认，确认后再生成详细食谱与营养分析；分层输出，避免一次性信息过载。

严格按照要求和流程，优先调用 web_search 工具搜索食谱，搜索不到的情况下才能自己发挥
"""

agent = create_agent(
    model=qwen,
    tools=[web_search],
    system_prompt=system_prompt,
    checkpointer=checkpointer,
)


def _split_content(content):
    """把消息 content 拆成 (text, image_url)。"""
    if isinstance(content, str):
        return content, None
    text = ""
    image_url = None
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            t = block.get("type")
            if t == "text":
                text += block.get("text", "")
            elif t == "image_url":
                iu = block.get("image_url")
                if isinstance(iu, dict):
                    image_url = iu.get("url")
    return text, image_url


def _content_to_str(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content)


# 流式输出（同步生成器：SqliteSaver 是同步的，FastAPI 会在线程池里迭代它）
def search_recipes(prompt: str, image: str, thread_id: str):
    """调用 agent 搜索食谱，流式返回文本片段。image 为空字符串表示纯文本。"""
    try:
        if not image or image.strip() == "":
            message = HumanMessage(content=prompt)
        else:
            message = HumanMessage(content=[
                {"type": "image_url", "image_url": {"url": image}},
                {"type": "text", "text": prompt},
            ])

        # 流式调用
        for chunk, _metadata in agent.stream(
            {"messages": [message]},
            {"configurable": {"thread_id": thread_id}},
            stream_mode="messages",
        ):
            if isinstance(chunk, AIMessageChunk) and chunk.content:
                yield _content_to_str(chunk.content)
    except Exception:
        yield "信息检索失败，试试手动输入食物列表？"


# 清空对话
def clear_messages(thread_id: str):
    checkpointer.delete_thread(thread_id)


# 查询会话历史
def get_messages(thread_id: str) -> list:
    """获取会话历史，返回 [{role, text, image_url}] 列表。"""
    cp = checkpointer.get({"configurable": {"thread_id": thread_id}})
    if not cp:
        return []

    # 该版本 checkpointer.get() 直接返回 checkpoint 字典（含 channel_values）
    channel_values = cp.get("channel_values") or {}
    messages = channel_values.get("messages", [])
    if not messages:
        return []

    result = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            text, image_url = _split_content(msg.content)
            result.append({"role": "user", "text": text, "image_url": image_url})
        elif isinstance(msg, AIMessage):
            text = _content_to_str(msg.content)
            if text:
                result.append({"role": "assistant", "text": text})
    return result


# 列出所有会话（用于侧边栏，按最近更新排序）
def list_threads() -> list:
    """列出所有 thread_id 及标题、消息数，按最近更新排序。"""
    try:
        cursor = connection.execute(
            "SELECT DISTINCT thread_id FROM checkpoints WHERE checkpoint_ns = ''"
        )
        ids = [row[0] for row in cursor.fetchall()]
    except Exception:
        return []
    sessions = []
    for tid in ids:
        cp = checkpointer.get({"configurable": {"thread_id": tid}})
        ts = (cp or {}).get("ts", "")
        msgs = get_messages(tid)
        title = "新对话"
        for m in msgs:
            if m["role"] == "user" and m.get("text"):
                title = m["text"][:20]
                break
        sessions.append(
            {"session_id": tid, "title": title, "message_count": len(msgs), "updated_at": ts}
        )
    sessions.sort(key=lambda s: s["updated_at"], reverse=True)
    return sessions
