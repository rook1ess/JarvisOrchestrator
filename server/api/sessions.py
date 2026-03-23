"""Claude Session 管理 API"""

import json
import re
from fastapi import APIRouter, HTTPException
from server.config import load_claude_sessions, get_session_title, get_claude_sessions_dir

router = APIRouter()

# 这些会在 main.py 中注入
_agent_manager = None
_ws_channel = None


def init(agent_manager, ws_channel):
    global _agent_manager, _ws_channel
    _agent_manager = agent_manager
    _ws_channel = ws_channel


def _resolve_instance_id(instance_id: str = None) -> str:
    """解析实例 ID，默认 ws-default"""
    return instance_id or "ws-default"


@router.get("/api/claude-sessions")
async def get_claude_sessions(instance_id: str = None):
    target = _resolve_instance_id(instance_id)
    sessions = load_claude_sessions()
    instance = _agent_manager.get_instance(target) if _agent_manager else None
    current_session = instance.current_session_id if instance else None

    # 实例未创建时，从保存的配置中获取 pending session
    pending_session = None
    if not current_session and _agent_manager:
        config = _agent_manager.get_instance_config(target)
        pending_session = config.get("last_session_id")

    result = []
    for s in sessions:
        result.append({
            "id": s.get("sessionId"),
            "title": get_session_title(s),
            "messageCount": s.get("messageCount", 0),
            "created": s.get("created"),
            "modified": s.get("modified"),
        })
    return {
        "sessions": result,
        "current_session": current_session or pending_session,
    }


@router.post("/api/claude-sessions/new")
async def create_new_claude_session(instance_id: str = None):
    target = _resolve_instance_id(instance_id)
    instance = _agent_manager.get_instance(target)
    if instance:
        await instance.restart(resume_session=None)  # 显式 None → 新 session
    # 清除保存的 last_session_id，防止实例被回收后重建时恢复旧 session
    if _agent_manager:
        _agent_manager.clear_instance_config_key(target, "last_session_id")
    if _ws_channel:
        await _ws_channel.send_response(
            {"type": "session_changed", "session_id": None, "is_new": True},
            {"instance_id": target}
        )
    return {"status": "ok", "message": "新会话已创建"}


@router.put("/api/claude-sessions/{session_id}/activate")
async def activate_claude_session(session_id: str, instance_id: str = None):
    target = _resolve_instance_id(instance_id)
    sessions = load_claude_sessions()
    session = next((s for s in sessions if s.get("sessionId") == session_id), None)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    instance = _agent_manager.get_instance(target)
    if instance:
        await instance.restart(resume_session=session_id)

    if _ws_channel:
        await _ws_channel.send_response(
            {"type": "session_changed", "session_id": session_id, "title": get_session_title(session)},
            {"instance_id": target}
        )

    return {
        "status": "ok",
        "session": {
            "id": session_id,
            "title": get_session_title(session),
            "messageCount": session.get("messageCount", 0)
        }
    }


_SYSTEM_STATUS_RE = re.compile(r"<system-status[^>]*>.*?</system-status>", re.DOTALL)


@router.get("/api/claude-sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    sessions_dir = get_claude_sessions_dir()
    jsonl_file = sessions_dir / f"{session_id}.jsonl"
    if not jsonl_file.exists():
        return {"messages": []}

    messages = []
    try:
        with open(jsonl_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = entry.get("type")

                if msg_type == "user":
                    # Skip internal tool results (not real user messages)
                    if entry.get("message", {}).get("parent_tool_use_id"):
                        continue
                    content = entry.get("message", {}).get("content", "")
                    if isinstance(content, list):
                        text_parts = [p.get("text", "") for p in content if p.get("type") == "text"]
                        content = "".join(text_parts)
                    # Strip <system-status> tags
                    content = _SYSTEM_STATUS_RE.sub("", content).strip()
                    if not content:
                        continue
                    msg = {"role": "user", "content": content}
                    # Expose uuid as message_id for rewind
                    if entry.get("uuid"):
                        msg["message_id"] = entry["uuid"]
                    messages.append(msg)

                elif msg_type == "assistant":
                    content_blocks = entry.get("message", {}).get("content", [])
                    blocks = []
                    text_parts = []
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
                                "input": block.get("input", {}),
                            })
                        elif btype == "thinking":
                            blocks.append({"type": "thinking", "text": block.get("text", "")})
                    messages.append({
                        "role": "assistant",
                        "content": "".join(text_parts),
                        "blocks": blocks,
                    })

                elif msg_type == "result":
                    # Attach stats to previous assistant message
                    stats = {}
                    if entry.get("usage"):
                        stats["usage"] = entry["usage"]
                    if entry.get("total_cost_usd") is not None:
                        stats["cost_usd"] = entry["total_cost_usd"]
                    if entry.get("duration_ms") is not None:
                        stats["duration_ms"] = entry["duration_ms"]
                    if entry.get("num_turns") is not None:
                        stats["num_turns"] = entry["num_turns"]
                    if stats and messages and messages[-1].get("role") == "assistant":
                        messages[-1]["stats"] = stats

                # Skip "summary", "system" types
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"messages": messages}


@router.delete("/api/claude-sessions/{session_id}")
async def delete_claude_session(session_id: str):
    sessions_dir = get_claude_sessions_dir()
    jsonl_file = sessions_dir / f"{session_id}.jsonl"

    if jsonl_file.exists():
        try:
            jsonl_file.unlink()
            print(f"[Session] 已删除 session 文件: {session_id}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete session file: {e}")

    # 检查所有实例，清除引用该 session 的实例
    if _agent_manager:
        for iid, inst in _agent_manager.get_all_instances().items():
            if inst.current_session_id == session_id:
                inst.current_session_id = None

    return {"status": "deleted", "session_id": session_id}
