"""实例发现与消息传递 API"""

import time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

_agent_manager = None
_ws_channel = None


def init(agent_manager, ws_channel):
    global _agent_manager, _ws_channel
    _agent_manager = agent_manager
    _ws_channel = ws_channel


class SendMessageRequest(BaseModel):
    message: str
    source: str = "api"


@router.get("/api/instances")
async def list_instances():
    """列出所有实例及状态"""
    instances = _agent_manager.get_all_instances()
    configs = _agent_manager._instance_configs

    result = []
    for iid, inst in instances.items():
        health = _agent_manager.check_instance_health(iid)
        result.append({
            "instance_id": iid,
            "status": health["status"],
            "is_processing": inst.is_processing,
            "queue_size": inst.message_queue.qsize(),
            "last_active_at": inst.last_active_at,
            "session_id": inst.current_session_id,
        })

    # 也列出已回收但有配置的实例（stopped 状态）
    for iid, cfg in configs.items():
        if iid not in instances:
            result.append({
                "instance_id": iid,
                "status": "stopped",
                "is_processing": False,
                "queue_size": 0,
                "last_active_at": None,
            })

    return result


@router.post("/api/instances/{instance_id}/send")
async def send_message(instance_id: str, req: SendMessageRequest):
    """向指定实例发送消息（入队）"""
    inst = _agent_manager.get_instance(instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found or stopped")

    # 根据实例类型选择回调渠道
    callback = _ws_channel.send_response if _ws_channel else None

    await inst.enqueue(req.message, source=req.source, response_callback=callback)

    return {
        "status": "queued",
        "queue_position": inst.message_queue.qsize(),
    }
