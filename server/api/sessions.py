"""Claude Session 管理 API — 基于 SDK 接口"""

import json
import re
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from claude_agent_sdk import (
    list_sessions,
    get_session_messages as sdk_get_session_messages,
    get_session_info,
    rename_session,
    tag_session,
    fork_session,
    delete_session as sdk_delete_session,
)
from server.config import _get_instance_cwd, PROJECT_ROOT, get_claude_sessions_dir

router = APIRouter()

_agent_manager = None
_ws_channel = None


def init(agent_manager, ws_channel):
    global _agent_manager, _ws_channel
    _agent_manager = agent_manager
    _ws_channel = ws_channel


def _get_directory() -> str:
    """获取 session 存储的 directory（实例的 CWD）"""
    return _get_instance_cwd() or str(PROJECT_ROOT)


def _resolve_instance_id(instance_id: str = None) -> str:
    return instance_id or "ws-default"


_SYSTEM_STATUS_RE = re.compile(r"<system-status[^>]*>.*?</system-status>", re.DOTALL)


@router.get("/api/claude-sessions")
async def get_claude_sessions(instance_id: str = None):
    target = _resolve_instance_id(instance_id)
    instance = _agent_manager.get_instance(target) if _agent_manager else None
    current_session = instance.current_session_id if instance else None

    # 实例未创建时，从保存的配置中获取 pending session
    pending_session = None
    if not current_session and _agent_manager:
        config = _agent_manager.get_instance_config(target)
        pending_session = config.get("last_session_id")

    try:
        sessions = list_sessions(directory=_get_directory(), limit=50)
    except Exception as e:
        print(f"[Session] list_sessions failed: {e}")
        sessions = []

    result = []
    for s in sessions:
        title = s.custom_title or s.first_prompt or "(untitled)"
        title = _SYSTEM_STATUS_RE.sub("", title).strip()
        if not title:
            title = "(untitled)"
        result.append({
            "id": s.session_id,
            "title": title[:80],
            "created": s.created_at,
            "modified": s.last_modified,
            "tag": s.tag,
            "branch": s.git_branch,
        })

    return {
        "sessions": result,
        "current_session": current_session or pending_session,
    }


@router.post("/api/claude-sessions/new")
async def create_new_claude_session(instance_id: str = None):
    target = _resolve_instance_id(instance_id)

    # 先更新配置（持久化），再触发切换
    if _agent_manager:
        _agent_manager.clear_instance_config_key(target, "last_session_id")
        _agent_manager._save_instance_sessions()

    instance = _agent_manager.get_instance(target) if _agent_manager else None
    if instance:
        instance.schedule_session_switch(None)  # None = 新 session

    if _ws_channel:
        await _ws_channel.send_response(
            {"type": "session_changed", "session_id": None, "is_new": True},
            {"instance_id": target}
        )
    return {"status": "ok", "message": "新会话已创建"}


@router.put("/api/claude-sessions/{session_id}/activate")
async def activate_claude_session(session_id: str, instance_id: str = None):
    target = _resolve_instance_id(instance_id)

    # 验证 session 存在
    info = get_session_info(session_id, directory=_get_directory())
    if not info:
        raise HTTPException(status_code=404, detail="Session not found")

    # 先持久化（无论实例是否存在，确保按需创建时也用正确的 session）
    if _agent_manager:
        _agent_manager.update_instance_config(target, "last_session_id", session_id)
        _agent_manager._save_instance_sessions()

    # 延迟切换（不立即 restart，等下一条消息时再切）
    instance = _agent_manager.get_instance(target) if _agent_manager else None
    if instance:
        instance.schedule_session_switch(session_id)

    title = info.custom_title or info.first_prompt or ""
    title = _SYSTEM_STATUS_RE.sub("", title).strip()

    if _ws_channel:
        await _ws_channel.send_response(
            {"type": "session_changed", "session_id": session_id, "title": title},
            {"instance_id": target}
        )

    return {"status": "ok", "session": {"id": session_id, "title": title}}


@router.get("/api/claude-sessions/{session_id}/messages")
async def get_session_messages_api(session_id: str, limit: int = None, offset: int = 0):
    try:
        raw_messages = sdk_get_session_messages(
            session_id, directory=_get_directory(), limit=limit, offset=offset
        )
    except Exception as e:
        return {"messages": []}

    messages = []
    for msg in raw_messages:
        role = msg.type
        content_blocks = msg.message.get("content", "") if isinstance(msg.message, dict) else ""

        if role == "user":
            if msg.parent_tool_use_id:
                continue
            if isinstance(content_blocks, list):
                text_parts = [p.get("text", "") for p in content_blocks if isinstance(p, dict) and p.get("type") == "text"]
                content = "".join(text_parts)
            elif isinstance(content_blocks, str):
                content = content_blocks
            else:
                content = str(content_blocks)
            content = _SYSTEM_STATUS_RE.sub("", content).strip()
            if not content:
                continue
            m = {"role": "user", "content": content}
            if msg.uuid:
                m["message_id"] = msg.uuid
            messages.append(m)

        elif role == "assistant":
            blocks = []
            text_parts = []
            if isinstance(content_blocks, list):
                for block in content_blocks:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type")
                    if btype == "text":
                        text_parts.append(block.get("text", ""))
                        blocks.append({"type": "text", "text": block.get("text", "")})
                    elif btype == "tool_use":
                        blocks.append({
                            "type": "tool_use",
                            "name": block.get("name", ""),
                            "id": block.get("id", ""),
                        })
                    elif btype == "thinking":
                        blocks.append({"type": "thinking", "text": block.get("text", "")})
            messages.append({
                "role": "assistant",
                "content": "".join(text_parts),
                "blocks": blocks,
            })

    return {"messages": messages}


class RenameRequest(BaseModel):
    title: str


@router.put("/api/claude-sessions/{session_id}/rename")
async def rename_session_api(session_id: str, req: RenameRequest):
    try:
        rename_session(session_id, req.title, directory=_get_directory())
        return {"status": "ok", "session_id": session_id, "title": req.title}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class TagRequest(BaseModel):
    tag: Optional[str] = None


@router.put("/api/claude-sessions/{session_id}/tag")
async def tag_session_api(session_id: str, req: TagRequest):
    try:
        tag_session(session_id, req.tag, directory=_get_directory())
        return {"status": "ok", "session_id": session_id, "tag": req.tag}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/claude-sessions/{session_id}/fork")
async def fork_session_api(session_id: str, instance_id: str = None):
    try:
        result = fork_session(session_id, directory=_get_directory())
        new_id = result.session_id
        target = _resolve_instance_id(instance_id)

        # 持久化 + 延迟切换
        if _agent_manager:
            _agent_manager.update_instance_config(target, "last_session_id", new_id)
            _agent_manager._save_instance_sessions()

        instance = _agent_manager.get_instance(target) if _agent_manager else None
        if instance:
            instance.schedule_session_switch(new_id)

        if _ws_channel:
            await _ws_channel.send_response(
                {"type": "session_changed", "session_id": new_id, "title": f"Fork of {session_id[:8]}"},
                {"instance_id": target}
            )

        return {"status": "ok", "original_session_id": session_id, "forked_session_id": new_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/claude-sessions/{session_id}")
async def delete_claude_session(session_id: str):
    try:
        sdk_delete_session(session_id, directory=_get_directory())
        print(f"[Session] 已删除: {session_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if _agent_manager:
        for iid, inst in _agent_manager.get_all_instances().items():
            if inst.current_session_id == session_id:
                inst.current_session_id = None
                inst.schedule_session_switch(None)  # 切到新 session
        for iid, cfg in _agent_manager.get_all_instance_configs().items():
            if cfg.get("last_session_id") == session_id:
                _agent_manager.clear_instance_config_key(iid, "last_session_id")
        _agent_manager._save_instance_sessions()

    return {"status": "deleted", "session_id": session_id}


# ==================================================================
# Fork from a specific message (for edit-resend / retry)
# ==================================================================

class ForkFromMessageRequest(BaseModel):
    before_message_id: str      # 在这条消息"之前"分叉（即新 session 不包含这条消息）
    delete_source: bool = False  # 是否删除原 session（edit/retry 通常 True）
    instance_id: Optional[str] = None


def _find_parent_uuid(session_id: str, message_uuid: str) -> tuple[Optional[str], bool]:
    """读 session jsonl，找到 message_uuid 这条消息的 parentUuid。

    Returns: (parent_uuid, found)
        - found=False: 消息未找到
        - found=True, parent_uuid=None: 消息存在但是第一条（无 parent）
        - found=True, parent_uuid=<uuid>: 正常 parent
    """
    jsonl_path = get_claude_sessions_dir() / f"{session_id}.jsonl"
    if not jsonl_path.exists():
        return None, False

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("uuid") == message_uuid:
                return obj.get("parentUuid"), True
    return None, False


@router.post("/api/claude-sessions/{session_id}/fork-from-message")
async def fork_from_message_api(session_id: str, req: ForkFromMessageRequest):
    """从指定消息处分叉出新 session（支持"编辑重发"和"重试"）。

    流程：
    1. 读 session jsonl 找到 before_message_id 的 parentUuid
    2. SDK fork_session(up_to_message_id=parentUuid) 创建新 session，只保留到 parent 为止
    3. 可选删除原 session
    4. 更新实例绑定到新 session（前端后续 sendMessage 会进新 session）
    """
    parent_uuid, found = _find_parent_uuid(session_id, req.before_message_id)
    if not found:
        raise HTTPException(
            status_code=404,
            detail=f"Message {req.before_message_id} not found in session {session_id}",
        )
    if not parent_uuid:
        raise HTTPException(
            status_code=400,
            detail="This is the first message in the session; nothing to fork from. Create a new session instead.",
        )

    # Fork — SDK up_to_message_id 是 inclusive，传 parentUuid 就能切到"在当前消息之前"
    try:
        result = fork_session(
            session_id,
            directory=_get_directory(),
            up_to_message_id=parent_uuid,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fork failed: {e}")

    new_session_id = result.session_id

    # 更新实例的 session 绑定（持久化 + 延迟切换）
    target_instance = _resolve_instance_id(req.instance_id)
    if _agent_manager:
        _agent_manager.update_instance_config(target_instance, "last_session_id", new_session_id)
        _agent_manager._save_instance_sessions()
    instance = _agent_manager.get_instance(target_instance) if _agent_manager else None
    if instance:
        instance.schedule_session_switch(new_session_id)

    # 广播给前端（同步多设备）
    if _ws_channel:
        await _ws_channel.send_response(
            {"type": "session_changed", "session_id": new_session_id, "title": f"Fork from {session_id[:8]}"},
            {"instance_id": target_instance},
        )

    # 可选删除原 session
    source_deleted = False
    if req.delete_source:
        try:
            sdk_delete_session(session_id, directory=_get_directory())
            source_deleted = True
            # 清理实例 config 里残留的 last_session_id 引用
            if _agent_manager:
                for iid, cfg in _agent_manager.get_all_instance_configs().items():
                    if cfg.get("last_session_id") == session_id:
                        _agent_manager.update_instance_config(iid, "last_session_id", new_session_id)
            print(f"[fork-from-message] Deleted source session {session_id[:8]}..., new={new_session_id[:8]}...")
        except Exception as e:
            # 即使删失败也不中断（新 session 已就绪）
            print(f"[fork-from-message] Failed to delete source session: {e}")

    return {
        "status": "ok",
        "new_session_id": new_session_id,
        "source_session_id": session_id,
        "source_deleted": source_deleted,
        "parent_uuid": parent_uuid,
    }
