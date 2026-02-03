"""Claude Session 管理 API"""

import json
from fastapi import APIRouter, HTTPException
from server.config import load_claude_sessions, get_session_title, get_claude_sessions_dir

router = APIRouter()

# 这些会在 main.py 中注入
_agent_manager = None
_ws_channel = None

DEFAULT_INSTANCE = "ws-default"


def init(agent_manager, ws_channel):
    global _agent_manager, _ws_channel
    _agent_manager = agent_manager
    _ws_channel = ws_channel


@router.get("/api/claude-sessions")
async def get_claude_sessions():
    sessions = load_claude_sessions()
    instance = _agent_manager.get_instance(DEFAULT_INSTANCE) if _agent_manager else None
    current_session = instance.current_session_id if instance else None

    result = []
    for s in sessions:
        result.append({
            "id": s.get("sessionId"),
            "title": get_session_title(s),
            "messageCount": s.get("messageCount", 0),
            "created": s.get("created"),
            "modified": s.get("modified"),
        })
    return {"sessions": result, "current_session": current_session}


@router.post("/api/claude-sessions/new")
async def create_new_claude_session():
    instance = _agent_manager.get_instance(DEFAULT_INSTANCE)
    if instance:
        await instance.restart(resume_session=None)
    if _ws_channel:
        await _ws_channel.send_response(
            {"type": "session_changed", "session_id": None, "is_new": True},
            {"instance_id": DEFAULT_INSTANCE}
        )
    return {"status": "ok", "message": "新会话已创建"}


@router.put("/api/claude-sessions/{session_id}/activate")
async def activate_claude_session(session_id: str):
    sessions = load_claude_sessions()
    session = next((s for s in sessions if s.get("sessionId") == session_id), None)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    instance = _agent_manager.get_instance(DEFAULT_INSTANCE)
    if instance:
        await instance.restart(resume_session=session_id)

    if _ws_channel:
        await _ws_channel.send_response(
            {"type": "session_changed", "session_id": session_id, "title": get_session_title(session)},
            {"instance_id": DEFAULT_INSTANCE}
        )

    return {
        "status": "ok",
        "session": {
            "id": session_id,
            "title": get_session_title(session),
            "messageCount": session.get("messageCount", 0)
        }
    }


@router.get("/api/claude-sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    sessions_dir = get_claude_sessions_dir()
    jsonl_file = sessions_dir / f"{session_id}.jsonl"
    if not jsonl_file.exists():
        raise HTTPException(status_code=404, detail="Session file not found")

    messages = []
    try:
        with open(jsonl_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        msg_type = entry.get("type")
                        if msg_type == "user":
                            content = entry.get("message", {}).get("content", "")
                            if isinstance(content, list):
                                text_parts = [p.get("text", "") for p in content if p.get("type") == "text"]
                                content = "".join(text_parts)
                            messages.append({"role": "user", "content": content})
                        elif msg_type == "assistant":
                            content = entry.get("message", {}).get("content", [])
                            text_parts = []
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    text_parts.append(block.get("text", ""))
                            messages.append({"role": "assistant", "content": "".join(text_parts)})
                    except json.JSONDecodeError:
                        continue
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

    instance = _agent_manager.get_instance(DEFAULT_INSTANCE) if _agent_manager else None
    if instance and instance.current_session_id == session_id:
        instance.current_session_id = None

    return {"status": "deleted", "session_id": session_id}
