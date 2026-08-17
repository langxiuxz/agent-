"""阿里云 OSS 图片上传封装。

读取 .env 中的 OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET / OSS_BUCKET / OSS_ENDPOINT，
把图片压缩后上传到 Bucket，返回公开访问 URL。
"""
import io
import os
import uuid
from datetime import datetime

import oss2
from PIL import Image, ImageOps

# 图片压缩：最长边限制，避免把手机原图整张塞给大模型
MAX_SIDE = 1600
JPEG_QUALITY = 88


def _host() -> str:
    """去掉 endpoint 里的 scheme，得到纯主机名，如 oss-cn-beijing.aliyuncs.com"""
    return os.getenv("OSS_ENDPOINT", "").replace("https://", "").replace("http://", "").rstrip("/")


def _bucket() -> oss2.Bucket:
    return oss2.Bucket(
        oss2.Auth(os.getenv("OSS_ACCESS_KEY_ID"), os.getenv("OSS_ACCESS_KEY_SECRET")),
        _host(),
        os.getenv("OSS_BUCKET"),
    )


def _process(file_bytes: bytes) -> bytes:
    """纠正 EXIF 方向 + 转 RGB + 缩放，统一输出 JPEG 字节流。"""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(file_bytes))).convert("RGB")
    if max(img.size) > MAX_SIDE:
        ratio = MAX_SIDE / max(img.size)
        img = img.resize((int(img.width * ratio), int(img.height * ratio)))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()


def upload_image(file_bytes: bytes, filename: str = "") -> dict:
    """上传图片到 OSS，返回 {url, bytes, mime, key}。"""
    data = _process(file_bytes)
    key = f"food/{datetime.now().strftime('%Y%m%d')}/{uuid.uuid4().hex}.jpg"
    _bucket().put_object(key, data, headers={"Content-Type": "image/jpeg"})
    url = f"https://{os.getenv('OSS_BUCKET')}.{_host()}/{key}"
    return {"url": url, "bytes": data, "mime": "image/jpeg", "key": key}
