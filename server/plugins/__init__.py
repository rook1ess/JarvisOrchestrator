"""轻量 Plugin 系统 — 目录扫描 + register() 注册。

每个 plugin 目录结构：
    server/plugins/<name>/
        manifest.json    # {name, version, description, enabled_by_default}
        __init__.py      # 提供 register(mcp, config, context) / shutdown()

加载流程：
1. main.py lifespan 启动时调用 load_plugins(mcp, config, context)
2. 读 data/config.json 的 plugins 字段决定启用/禁用
3. 启用的 plugin 调用 register() 注册 MCP tool / hook / 后台任务
"""

import importlib
import json
from pathlib import Path
from typing import Any


def discover_plugins() -> dict[str, dict]:
    """扫 server/plugins/<name>/manifest.json"""
    plugins_dir = Path(__file__).parent
    found = {}
    for entry in plugins_dir.iterdir():
        if not entry.is_dir() or entry.name.startswith("_") or entry.name.startswith("."):
            continue
        manifest_path = entry / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            name = manifest.get("name", entry.name)
            manifest["_dir"] = entry.name
            found[name] = manifest
        except Exception as e:
            print(f"[Plugin] 读取 manifest 失败 {entry.name}: {e}")
    return found


def load_plugins(mcp, config, context: dict = None) -> dict[str, Any]:
    """根据 config 加载启用的 plugin，返回 {name: module}"""
    discovered = discover_plugins()
    loaded = {}
    for name, manifest in discovered.items():
        default_enabled = manifest.get("enabled_by_default", False)
        enabled = config.is_plugin_enabled(name, default=default_enabled)
        if not enabled:
            print(f"[Plugin] {name} 已禁用，跳过")
            continue
        try:
            mod = importlib.import_module(f"server.plugins.{manifest['_dir']}")
            if hasattr(mod, "register"):
                mod.register(mcp, config, context or {})
                loaded[name] = mod
                print(f"[Plugin] {name} v{manifest.get('version', '?')} 已加载")
            else:
                print(f"[Plugin] {name} 缺少 register() 函数，跳过")
        except Exception as e:
            import traceback
            print(f"[Plugin] {name} 加载失败: {e}")
            traceback.print_exc()
    return loaded


async def shutdown_plugins(loaded: dict[str, Any]):
    for name, mod in loaded.items():
        if hasattr(mod, "shutdown"):
            try:
                result = mod.shutdown()
                if hasattr(result, "__await__"):
                    await result
                print(f"[Plugin] {name} 已关闭")
            except Exception as e:
                print(f"[Plugin] {name} shutdown 失败: {e}")


def get_plugin_module(loaded: dict[str, Any], name: str):
    """从已加载 plugin 里获取 module（供 hook / 其他模块按名查找）"""
    return loaded.get(name)
