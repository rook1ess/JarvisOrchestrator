"""工具/子代理 API（实例配置相关路由已移至 instances.py）"""

import json
from fastapi import APIRouter, HTTPException, Query
from server.config import INSTANCES_DIR, AVAILABLE_TOOLS, load_subagents

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


# 注意：以下路由已移至 instances.py，这里保留注释供参考
# - GET /api/instances/{instance_id}/config  -> instances.py
# - PUT /api/instances/{instance_id}/config  -> instances.py
# - GET /api/available-tools                 -> instances.py
# - GET /api/mcp-servers                     -> instances.py


@router.get("/api/subagents")
async def get_subagents():
    """列出所有子代理"""
    return load_subagents()
