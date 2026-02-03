"""Instance 配置 + 工具/子代理 API"""

import json
from fastapi import APIRouter, HTTPException, Query
from server.config import INSTANCES_DIR, AVAILABLE_TOOLS, load_instance_config, load_subagents, get_mcp_servers_from_config

router = APIRouter()


@router.get("/api/instances/config")
async def list_instance_configs():
    """列出所有实例配置文件"""
    configs = []
    if INSTANCES_DIR.exists():
        for file in INSTANCES_DIR.glob("*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                configs.append({
                    "instance_id": file.stem,
                    "is_default": file.stem == "_default",
                })
            except Exception:
                pass
    return configs


@router.get("/api/instances/{instance_id}/config")
async def get_instance_config(instance_id: str):
    """获取实例的合并后配置（_default + 实例特定）"""
    config = load_instance_config(instance_id)
    if not config:
        raise HTTPException(status_code=404, detail="Instance config not found")
    return config


@router.put("/api/instances/{instance_id}/config")
async def update_instance_config(instance_id: str, config: dict):
    """更新实例特定配置（只保存与默认不同的部分）"""
    file_path = INSTANCES_DIR / f"{instance_id}.json"
    INSTANCES_DIR.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    return {"status": "ok", "instance_id": instance_id}


@router.get("/api/tools")
async def get_tools():
    """列出所有可用工具"""
    return AVAILABLE_TOOLS


@router.get("/api/subagents")
async def get_subagents():
    """列出所有子代理"""
    return load_subagents()


@router.get("/api/mcp-servers")
async def get_mcp_servers(config_path: str = Query(default=".mcp.json")):
    """列出 MCP servers 配置"""
    return get_mcp_servers_from_config(config_path)
