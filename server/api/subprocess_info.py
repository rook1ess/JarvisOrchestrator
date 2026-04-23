"""子进程容器 + 宿主环境探测 API —— 供设置面板「子进程环境」展示。

数据源：
- 容器：docker inspect / exec 读 settings.json / ~/.claude.json / skills 目录
- 宿主：sys.version + pip 包版本（claude-agent-sdk / mcp / sqlite-vec / llama-cpp-python）

缓存 300 秒（避免频繁 docker exec 卡设置面板）。
前端可 `?refresh=1` 强制重新探测。
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from typing import Any

from fastapi import APIRouter, Query


router = APIRouter()

_cache: dict[str, Any] = {"data": None, "at": 0}
_CACHE_TTL = 300


def _run(cmd: list, timeout: int = 5) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            return False, (r.stderr or r.stdout or "").strip()[:300]
        return True, (r.stdout or "").strip()
    except subprocess.TimeoutExpired:
        return False, f"timeout ({timeout}s)"
    except FileNotFoundError:
        return False, f"command not found: {cmd[0]}"
    except Exception as e:
        return False, str(e)[:200]


# ---------- Container probes ----------

def _probe_container(name: str) -> dict:
    ok, out = _run(
        ["docker", "inspect", "--format",
         "{{.State.Status}}|{{.State.StartedAt}}|{{.Config.Image}}", name],
        timeout=3,
    )
    if not ok:
        return {"name": name, "running": False, "error": out}
    parts = out.split("|", 2)
    status = parts[0] if parts else "unknown"
    started = parts[1] if len(parts) > 1 else ""
    image = parts[2] if len(parts) > 2 else ""
    return {
        "name": name,
        "running": status == "running",
        "status": status,
        "started_at": started,
        "image": image,
    }


def _probe_cli_version(name: str) -> dict:
    ok, out = _run(["docker", "exec", name, "claude", "--version"], timeout=6)
    if not ok:
        return {"version": None, "error": out}
    # Typical: "2.1.40 (Claude Code)" 或纯 "2.1.40"
    token = out.split()[0] if out else ""
    return {"version": token or None, "raw": out}


def _probe_settings(name: str) -> dict:
    ok, out = _run(
        ["docker", "exec", name, "cat", "/home/claude/.claude/settings.json"],
        timeout=3,
    )
    if not ok:
        return {"error": out}
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return {"error": "invalid JSON"}
    return {
        "model": data.get("model"),
        "permission_mode": data.get("permission_mode")
            or ("bypass" if data.get("skipDangerousModePermissionPrompt") else None),
        "hooks": sorted((data.get("hooks") or {}).keys()),
    }


def _probe_mcps(name: str) -> list[str]:
    ok, out = _run(
        ["docker", "exec", name, "cat", "/home/claude/.claude.json"],
        timeout=3,
    )
    if not ok:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    return sorted((data.get("mcpServers") or {}).keys())


def _probe_skills(name: str) -> list[str]:
    ok, out = _run(
        ["docker", "exec", name, "bash", "-c",
         "ls -1 /home/claude/.claude/skills/ 2>/dev/null || true"],
        timeout=3,
    )
    if not ok:
        return []
    return [s.strip() for s in out.split("\n") if s.strip()]


def _probe_oauth(name: str) -> dict:
    host_env = bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))
    ok, _ = _run(
        ["docker", "exec", name, "test", "-f",
         "/home/claude/.claude/.credentials.json"],
        timeout=3,
    )
    return {"host_env": host_env, "container_creds": ok}


# ---------- Host probes ----------

def _pkg_version(mod_name: str) -> str | None:
    try:
        mod = __import__(mod_name)
        return getattr(mod, "__version__", "installed")
    except ImportError:
        return None
    except Exception:
        return "installed"


def _probe_host() -> dict:
    return {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "claude_agent_sdk": _pkg_version("claude_agent_sdk"),
        "fastapi": _pkg_version("fastapi"),
        "mcp": _pkg_version("mcp"),
        "uvicorn": _pkg_version("uvicorn"),
        "sqlite_vec": _pkg_version("sqlite_vec"),
        "llama_cpp_python": _pkg_version("llama_cpp"),
        "cwd": os.getcwd(),
    }


# ---------- Orchestration ----------

async def _probe_all(container_name: str) -> dict:
    loop = asyncio.get_running_loop()
    host = _probe_host()
    container = await loop.run_in_executor(None, _probe_container, container_name)

    result = {
        "container": container,
        "host": host,
        "probed_at": int(time.time()),
    }

    if container.get("running"):
        cli_t = loop.run_in_executor(None, _probe_cli_version, container_name)
        settings_t = loop.run_in_executor(None, _probe_settings, container_name)
        mcps_t = loop.run_in_executor(None, _probe_mcps, container_name)
        skills_t = loop.run_in_executor(None, _probe_skills, container_name)
        oauth_t = loop.run_in_executor(None, _probe_oauth, container_name)
        result["cli"] = await cli_t
        result["settings"] = await settings_t
        result["mcp_servers"] = await mcps_t
        result["skills"] = await skills_t
        result["oauth"] = await oauth_t
    else:
        result["cli"] = None
        result["settings"] = None
        result["mcp_servers"] = []
        result["skills"] = []
        result["oauth"] = None
    return result


@router.get("/api/subprocess-info")
async def get_subprocess_info(refresh: bool = Query(False)):
    """探测子进程容器 + 宿主环境。缓存 300s，refresh=true 强制重探测。"""
    now = time.time()
    if not refresh and _cache["data"] and now - _cache["at"] < _CACHE_TTL:
        return {"cached": True, "age_seconds": int(now - _cache["at"]), **_cache["data"]}

    container_name = os.environ.get("JARVIS_CONTAINER_NAME", "claude-dev")
    data = await _probe_all(container_name)
    _cache["data"] = data
    _cache["at"] = now
    return {"cached": False, "age_seconds": 0, **data}
