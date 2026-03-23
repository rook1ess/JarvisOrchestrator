"""实例发现与消息传递 API"""

import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from server.config import (
    PROJECT_ROOT, INSTANCES_DIR, AVAILABLE_TOOLS,
    load_instance_config, load_subagents,
)

router = APIRouter()

_agent_manager = None
_ws_channel = None
_qq_channel = None
_message_router = None


def init(agent_manager, ws_channel, qq_channel=None, message_router=None):
    global _agent_manager, _ws_channel, _qq_channel, _message_router
    _agent_manager = agent_manager
    _ws_channel = ws_channel
    _qq_channel = qq_channel
    _message_router = message_router


class SendMessageRequest(BaseModel):
    message: str
    source: str = "api"


class SetModelRequest(BaseModel):
    model: str


class RewindRequest(BaseModel):
    user_message_id: str


class InstanceConfigUpdate(BaseModel):
    model: Optional[str] = None
    permission_mode: Optional[str] = None
    mcp_enabled: Optional[bool] = None
    mcp_servers_disabled: Optional[List[str]] = None
    allowed_tools: Optional[List[str]] = None
    system_prompt: Optional[str] = None


class CreateInstanceRequest(BaseModel):
    instance_id: str
    model: str = "sonnet"
    permission_mode: str = "bypassPermissions"
    mcp_enabled: bool = True
    mcp_servers_disabled: List[str] = []
    allowed_tools: List[str] = []
    system_prompt: str = ""


@router.get("/api/instances")
async def list_instances():
    """列出所有实例及状态"""
    instances = _agent_manager.get_all_instances()
    configs = _agent_manager.get_all_instance_configs()

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

    # channel-aware 回调
    callback = _ws_channel.send_response if _ws_channel else None
    if _message_router:
        channel_type = _message_router.get_channel_type_for_instance(instance_id)
        if channel_type == "qq" and _qq_channel:
            callback = _qq_channel.send_response

    await inst.enqueue(req.message, source=req.source, response_callback=callback)

    return {
        "status": "queued",
        "queue_position": inst.message_queue.qsize(),
    }


@router.get("/api/instances/{instance_id}/config")
async def get_instance_config(instance_id: str):
    """获取实例配置（合并后的完整配置）"""
    config = load_instance_config(instance_id)
    if not config:
        raise HTTPException(status_code=404, detail=f"Config for '{instance_id}' not found")

    # 读取实例特定配置文件（覆盖项）
    instance_file = INSTANCES_DIR / f"{instance_id}.json"
    instance_overrides = {}
    if instance_file.exists():
        try:
            with open(instance_file, "r", encoding="utf-8") as f:
                instance_overrides = json.load(f)
        except Exception:
            pass

    return {
        "merged_config": config,
        "instance_overrides": instance_overrides,
    }


@router.put("/api/instances/{instance_id}/config")
async def update_instance_config(instance_id: str, req: InstanceConfigUpdate):
    """保存实例配置并自动重启"""
    instance_file = INSTANCES_DIR / f"{instance_id}.json"

    # 读取现有配置
    existing = {}
    if instance_file.exists():
        try:
            with open(instance_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    # 更新配置（只更新非 None 字段）
    update_data = req.model_dump(exclude_none=True)
    for key, value in update_data.items():
        existing[key] = value

    # 保存
    INSTANCES_DIR.mkdir(exist_ok=True)
    with open(instance_file, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    # 如果实例正在运行，自动重启
    inst = _agent_manager.get_instance(instance_id)
    restarted = False
    if inst:
        try:
            await inst.restart()
            restarted = True
        except Exception as e:
            print(f"[API] 重启实例失败: {e}")

    return {
        "status": "saved",
        "restarted": restarted,
        "config": existing,
    }


@router.post("/api/instances")
async def create_instance(req: CreateInstanceRequest):
    """创建新实例配置"""
    # 检查是否已存在
    instance_file = INSTANCES_DIR / f"{req.instance_id}.json"
    if instance_file.exists():
        raise HTTPException(status_code=400, detail=f"Instance '{req.instance_id}' already exists")

    # 验证 instance_id 格式
    if not req.instance_id or "/" in req.instance_id or "\\" in req.instance_id:
        raise HTTPException(status_code=400, detail="Invalid instance_id")

    # 创建配置
    config = {
        "model": req.model,
        "permission_mode": req.permission_mode,
        "mcp_enabled": req.mcp_enabled,
        "mcp_servers_disabled": req.mcp_servers_disabled,
        "allowed_tools": req.allowed_tools,
    }
    if req.system_prompt:
        config["system_prompt"] = req.system_prompt

    INSTANCES_DIR.mkdir(exist_ok=True)
    with open(instance_file, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    return {
        "status": "created",
        "instance_id": req.instance_id,
        "config": config,
    }


@router.delete("/api/instances/{instance_id}")
async def delete_instance(instance_id: str):
    """删除实例配置"""
    # 不允许删除默认配置
    if instance_id == "_default":
        raise HTTPException(status_code=400, detail="Cannot delete default config")

    instance_file = INSTANCES_DIR / f"{instance_id}.json"
    if not instance_file.exists():
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found")

    # 如果实例正在运行，先停止
    inst = _agent_manager.get_instance(instance_id)
    if inst:
        try:
            await inst.stop()
            _agent_manager._instances.pop(instance_id, None)
        except Exception as e:
            print(f"[API] 停止实例失败: {e}")

    # 删除配置文件
    instance_file.unlink()

    # 清理 manager 中的配置缓存
    _agent_manager.clear_instance_config_key(instance_id, "last_session_id")

    return {"status": "deleted", "instance_id": instance_id}


@router.post("/api/instances/{instance_id}/model")
async def set_instance_model(instance_id: str, req: SetModelRequest):
    """运行时切换模型，无需重启"""
    inst = _agent_manager.get_instance(instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found")
    try:
        await inst.sdk_set_model(req.model)
        return {"status": "ok", "instance_id": instance_id, "model": req.model}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/instances/{instance_id}/mcp-status")
async def get_instance_mcp_status(instance_id: str):
    """获取 MCP 服务器实时连接状态"""
    inst = _agent_manager.get_instance(instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found")
    try:
        result = await inst.sdk_get_mcp_status()
        return {"status": "ok", "instance_id": instance_id, "mcp_status": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/instances/{instance_id}/rewind")
async def rewind_instance(instance_id: str, req: RewindRequest):
    """回退到指定消息时的文件状态。传入 user_message_id（来自消息历史的 message_id 字段）"""
    inst = _agent_manager.get_instance(instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail=f"Instance '{instance_id}' not found")
    try:
        await inst.sdk_rewind_files(req.user_message_id)
        return {"status": "ok", "instance_id": instance_id, "rewound_to": req.user_message_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/mcp-servers")
async def list_mcp_servers():
    """获取所有可用的 MCP 服务器列表（项目级 + 用户级）"""
    from pathlib import Path
    servers = []

    # 1. 项目级 .mcp.json
    project_mcp_file = PROJECT_ROOT / ".mcp.json"
    if project_mcp_file.exists():
        try:
            with open(project_mcp_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                mcp_servers = data.get("mcpServers", {})
                for name, info in mcp_servers.items():
                    servers.append({
                        "name": name,
                        "type": info.get("type", "http" if "url" in info else "stdio"),
                        "url": info.get("url", ""),
                        "source": "project",
                    })
        except Exception as e:
            print(f"[API] 加载项目级 MCP 配置失败: {e}")

    # 2. 用户级 ~/.claude/mcp_servers.json
    user_mcp_file = Path.home() / ".claude" / "mcp_servers.json"
    if user_mcp_file.exists():
        try:
            with open(user_mcp_file, "r", encoding="utf-8") as f:
                mcp_servers = json.load(f)
                for name, info in mcp_servers.items():
                    # 避免重复（项目级优先）
                    if not any(s["name"] == name for s in servers):
                        servers.append({
                            "name": name,
                            "type": info.get("type", "stdio"),
                            "command": info.get("command", ""),
                            "source": "user",
                        })
        except Exception as e:
            print(f"[API] 加载用户级 MCP 配置失败: {e}")

    return servers


@router.get("/api/available-tools")
async def list_available_tools():
    """获取所有可用工具列表"""
    return AVAILABLE_TOOLS


@router.get("/api/instances/config")
async def list_instance_configs():
    """列出所有实例配置文件"""
    configs = []
    if INSTANCES_DIR.exists():
        for file in INSTANCES_DIR.glob("*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    json.load(f)
                configs.append({
                    "instance_id": file.stem,
                    "is_default": file.stem == "_default",
                })
            except Exception:
                pass
    return configs


@router.get("/api/subagents")
async def get_subagents():
    """列出所有子代理"""
    return load_subagents()
