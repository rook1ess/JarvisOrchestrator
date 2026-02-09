"""QQ/NapCat OneBot11 渠道"""

from typing import Optional, Dict
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


def parse_qq_message(message) -> str:
    """从 OneBot11 消息段提取纯文本"""
    if isinstance(message, str):
        return message.strip()
    parts = []
    for seg in message:
        if seg.get("type") == "text":
            parts.append(seg["data"].get("text", ""))
        elif seg.get("type") == "image":
            parts.append("[图片]")
        elif seg.get("type") == "face":
            parts.append("[表情]")
    return "".join(parts).strip()


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

    def set_context(self, source: str, user_id: int = None, group_id: int = None):
        self._contexts[source] = {
            "user_id": user_id,
            "group_id": group_id,
            "chunks": []
        }

    async def send_response(self, data: dict, context: dict):
        """累积文本块，done 时合并发送"""
        source = context.get("source", "")
        ctx = self._contexts.get(source)
        if not ctx:
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
