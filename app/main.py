"""私人厨师 —— FastAPI 后端入口。

启动方式（在项目根目录 d:/agent实战 下）：
    /d/AIanaconda/envs/edu/python.exe -m uvicorn app.main:app --reload --port 8000
然后浏览器打开 http://127.0.0.1:8000

接口一览：
    POST /api/upload            上传图片到 OSS，返回 {url}
    POST /api/chat              流式对话（返回 text/plain 逐字流）
    GET  /api/history/{thread}  查询会话历史
    DELETE /api/history/{thread} 清空对话
    GET  /api/sessions          会话列表
"""
import os

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import oss_client
from app.agents.personal_chief import (
    clear_messages,
    get_messages,
    list_threads,
    search_recipes,
)

app = FastAPI(title="私人厨师")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    thread_id: str
    message: str = ""
    image_url: str | None = None


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as f:
        return f.read()


@app.post("/api/upload")
async def upload(image: UploadFile = File(...)):
    raw = await image.read()
    if not raw:
        raise HTTPException(status_code=400, detail="图片为空")
    up = oss_client.upload_image(raw, image.filename or "")
    return {"url": up["url"]}


@app.post("/api/chat")
def chat(req: ChatRequest):
    text = (req.message or "").strip()
    image_url = req.image_url
    if image_url and not text:
        text = "请识别图片中的食材，并给出评估。"
    if not text and not image_url:
        raise HTTPException(status_code=400, detail="消息和图片不能同时为空")

    return StreamingResponse(
        search_recipes(prompt=text, image=image_url or "", thread_id=req.thread_id),
        media_type="text/plain; charset=utf-8",
    )


@app.get("/api/history/{thread_id}")
def history(thread_id: str):
    return {"messages": get_messages(thread_id)}


@app.delete("/api/history/{thread_id}")
def clear(thread_id: str):
    clear_messages(thread_id)
    return {"ok": True}


@app.get("/api/sessions")
def sessions():
    return {"sessions": list_threads()}
