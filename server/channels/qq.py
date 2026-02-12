"""QQ/NapCat OneBot11 渠道"""

import base64
from typing import Optional, Dict, Tuple, List
import httpx
from server.channels.base import Channel
from server.config import NAPCAT_API_URL, NAPCAT_TOKEN


# NapCat HTTP client（延迟初始化）
_napcat_http: Optional[httpx.AsyncClient] = None


def _get_napcat_http() -> httpx.AsyncClient:
    global _napcat_http
    if _napcat_http is None:
        headers = {"Authorization": f"Bearer {NAPCAT_TOKEN}"} if NAPCAT_TOKEN else {}
        _napcat_http = httpx.AsyncClient(base_url=NAPCAT_API_URL, headers=headers, timeout=15.0)
    return _napcat_http


# QQ 表情 ID → 描述
_FACE_MAP = {
    0: "😮", 1: "😣", 2: "😍", 4: "😎", 5: "😭", 6: "☺️", 7: "🤐",
    8: "😴", 9: "😢", 10: "😳", 11: "😡", 12: "🤪", 13: "😁", 14: "🙂",
    15: "🙁", 16: "😎", 18: "😱", 19: "🤮", 20: "🤭", 21: "😊",
    23: "😔", 24: "😋", 25: "😥", 26: "😨", 27: "😏", 28: "😊",
    29: "😞", 31: "🤬", 32: "🤔", 33: "🤫", 34: "😵", 35: "😣",
    37: "💀", 38: "😤", 39: "👋", 46: "🐷", 49: "🤗", 53: "🎂",
    56: "🔪", 59: "💩", 60: "☕", 63: "🌹", 66: "❤️", 74: "🌞",
    75: "🌙", 76: "👍", 78: "🤝", 79: "✌️", 85: "🎉", 86: "😤",
    89: "🍉", 96: "😅", 97: "😪", 98: "😂", 99: "😢", 100: "😠",
    101: "😃", 102: "😝", 103: "😮", 104: "😱", 106: "😤",
    109: "😙", 111: "🥺", 116: "😒", 118: "😜", 120: "👊",
    122: "😤", 123: "🍻", 124: "🎵", 125: "🛒", 137: "🐔",
    144: "😸", 145: "🙃", 146: "😧", 169: "🤡", 171: "🍵",
    172: "🤥", 173: "😏", 174: "😂", 176: "🤣", 177: "💔",
    178: "🧐", 179: "🤩", 180: "🥰", 181: "😊", 182: "🥲",
    183: "😢", 187: "🤑", 201: "🎤", 203: "🤳", 212: "🥳",
}


def parse_qq_message(message) -> Tuple[str, List[str], List[dict]]:
    """从 OneBot11 消息段提取文本、图片 URL 和文件信息

    Returns:
        (text, image_urls, files): 文本内容、图片 URL 列表、文件列表 [{"url": ..., "name": ...}]
    """
    if isinstance(message, str):
        return message.strip(), [], []
    parts = []
    image_urls = []
    files = []
    for seg in message:
        seg_type = seg.get("type")
        data = seg.get("data", {})
        if seg_type == "text":
            parts.append(data.get("text", ""))
        elif seg_type == "image":
            url = data.get("url", "")
            if url:
                image_urls.append(url)
        elif seg_type == "face":
            face_id = int(data.get("id", -1))
            parts.append(_FACE_MAP.get(face_id, f"[表情:{face_id}]"))
        elif seg_type == "file":
            file_url = data.get("url", "")
            file_name = data.get("name", data.get("file", "未知"))
            if file_url:
                files.append({"url": file_url, "name": file_name})
            else:
                parts.append(f"[文件: {file_name}]")
        elif seg_type == "record":
            parts.append("[语音消息]")
        elif seg_type == "video":
            parts.append("[视频]")
        elif seg_type == "reply":
            pass  # 引用回复，忽略
        elif seg_type == "at":
            parts.append(f"@{data.get('name', data.get('qq', ''))}")
        elif seg_type == "forward":
            parts.append("[合并转发消息]")
    return "".join(parts).strip(), image_urls, files


# 可作为文本读取的文件扩展名
_TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".xml", ".html", ".htm", ".css", ".scss",
    ".sql", ".sh", ".bash", ".zsh", ".bat", ".ps1", ".rb", ".go", ".rs", ".java",
    ".kt", ".c", ".cpp", ".h", ".hpp", ".cs", ".swift", ".r", ".lua", ".pl",
    ".php", ".csv", ".tsv", ".log", ".env", ".gitignore", ".dockerfile",
    ".makefile", ".gradle", ".properties", ".tex", ".rst", ".org", ".vim",
}


async def download_image_as_base64(url: str) -> Optional[dict]:
    """下载图片并转为 base64 attachment 格式"""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                print(f"[QQ] 图片下载失败 ({resp.status_code}): {url[:80]}")
                return None
            content_type = resp.headers.get("content-type", "image/jpeg")
            if "png" in content_type:
                media_type = "image/png"
            elif "gif" in content_type:
                media_type = "image/gif"
            elif "webp" in content_type:
                media_type = "image/webp"
            else:
                media_type = "image/jpeg"
            b64 = base64.b64encode(resp.content).decode("utf-8")
            return {"type": "image", "media_type": media_type, "data": b64}
    except Exception as e:
        print(f"[QQ] 图片下载异常: {e}")
        return None


async def download_file_as_attachment(url: str, filename: str) -> Optional[dict]:
    """下载文件并转为 attachment 格式（文本/PDF/不支持）"""
    import os
    ext = os.path.splitext(filename)[1].lower()

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                print(f"[QQ] 文件下载失败 ({resp.status_code}): {filename}")
                return None

            # PDF → document attachment
            if ext == ".pdf":
                b64 = base64.b64encode(resp.content).decode("utf-8")
                return {"type": "document", "media_type": "application/pdf", "data": b64, "name": filename}

            # 文本文件 → text_file attachment
            if ext in _TEXT_EXTENSIONS:
                try:
                    content = resp.content.decode("utf-8")
                except UnicodeDecodeError:
                    content = resp.content.decode("gbk", errors="replace")
                return {"type": "text_file", "name": filename, "content": content}

            # 其他二进制文件 → 不传给 Claude，只返回提示
            print(f"[QQ] 不支持的文件类型: {filename} ({ext})")
            return None

    except Exception as e:
        print(f"[QQ] 文件下载异常 ({filename}): {e}")
        return None


def qq_message_has_at_bot(message, self_id) -> bool:
    """检查群消息是否 @了机器人"""
    if isinstance(message, str):
        return False
    for seg in message:
        if seg.get("type") == "at" and str(seg.get("data", {}).get("qq")) == str(self_id):
            return True
    return False


async def send_qq_message(user_id: int = None, group_id: int = None, text: str = ""):
    """通过 NapCat API 发送消息到 QQ"""
    if not text.strip():
        return
    http = _get_napcat_http()
    message = [{"type": "text", "data": {"text": text}}]
    try:
        if group_id:
            await http.post("/send_group_msg", json={"group_id": group_id, "message": message})
        elif user_id:
            await http.post("/send_private_msg", json={"user_id": user_id, "message": message})
    except Exception as e:
        print(f"[QQ] 发送消息失败: {e}")


class QQChannel(Channel):
    """QQ 渠道 - 累积文本块，在 done 信号时合并发送"""

    channel_type = "qq"

    def __init__(self):
        # source -> {"chunks": [], "user_id": ..., "group_id": ...}
        self._contexts: Dict[str, dict] = {}
        # 每个 instance_id 最后活跃的 QQ 上下文（用于主动消息的 fallback）
        self._last_active: Dict[str, dict] = {}

    def set_context(self, source: str, user_id: int = None, group_id: int = None,
                    instance_id: str = None):
        self._contexts[source] = {
            "user_id": user_id,
            "group_id": group_id,
            "chunks": []
        }
        # 记录此 instance 最后活跃的 QQ 目标
        if instance_id:
            self._last_active[instance_id] = {
                "user_id": user_id,
                "group_id": group_id,
            }

    def get_last_active(self, instance_id: str) -> Optional[dict]:
        """获取该实例最后一次 QQ 对话的目标用户/群"""
        return self._last_active.get(instance_id)

    async def send_response(self, data: dict, context: dict):
        """累积文本块，done 时合并发送"""
        source = context.get("source", "")
        ctx = self._contexts.get(source)

        # fallback：如果没有精确 source 的 context，用 instance 的 last_active 创建临时 context
        if not ctx:
            instance_id = context.get("instance_id")
            last = self._last_active.get(instance_id) if instance_id else None
            if last:
                ctx = {"user_id": last["user_id"], "group_id": last["group_id"], "chunks": []}
                self._contexts[source] = ctx
            else:
                return

        msg_type = data.get("type")
        if msg_type == "text":
            ctx["chunks"].append(data.get("content", ""))
        elif msg_type in ("done", "cancelled", "error"):
            # 合并发送
            if ctx["chunks"]:
                reply_text = "\n".join(ctx["chunks"])
                await send_qq_message(
                    user_id=ctx.get("user_id"),
                    group_id=ctx.get("group_id"),
                    text=reply_text
                )
            # 清理 context，防止内存泄漏
            del self._contexts[source]
