"""配置读写 API — 供前端设置面板使用。"""

from fastapi import APIRouter
from pydantic import BaseModel

from server.config_store import get_config

router = APIRouter()


class ConfigPatch(BaseModel):
    changes: dict


@router.get("/api/config")
async def get_config_snapshot():
    """读取配置（敏感字段打码）"""
    return get_config().snapshot(mask_sensitive=True)


@router.get("/api/config/raw")
async def get_config_raw():
    """读取配置原文（含明文 API key）— 不推荐暴露给前端，仅后端调试用"""
    return get_config().snapshot(mask_sensitive=False)


@router.post("/api/config")
async def patch_config(payload: ConfigPatch):
    """批量写配置。打码（全 • 字符）的敏感字段会被自动忽略，避免覆盖真实值。"""
    cleaned = _strip_masked_fields(payload.changes)
    get_config().patch(cleaned)
    return {"status": "ok"}


@router.post("/api/config/reload")
async def reload_config():
    """从磁盘重新加载配置（用于外部改了 config.json 后刷新）"""
    get_config().reload()
    return {"status": "ok"}


def _strip_masked_fields(changes: dict) -> dict:
    """移除值为纯打码字符的字段（防止前端打码回写覆盖真实值）"""
    out = {}
    for k, v in changes.items():
        if isinstance(v, dict):
            sub = _strip_masked_fields(v)
            if sub:
                out[k] = sub
        elif isinstance(v, str) and v and all(c == "•" or c.isalnum() for c in v):
            # 检测是否是打码值（•••• + 后 4 位真值）
            if v.startswith("•"):
                continue
            out[k] = v
        else:
            out[k] = v
    return out
