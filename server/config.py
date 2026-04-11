"""配置加载、常量、工具列表"""

import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from claude_agent_sdk import AgentDefinition

# ============== 路径配置（提前定义，供后续使用）==============
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
DATA_DIR = PROJECT_ROOT / "data"

# 注：不再使用 JARVIS_CONFIG_DIR 隔离 session，SDK 直接用 ~/.claude

# ============== 持久化 SERVER_SESSION_ID ==============
def _get_or_create_server_session_id() -> str:
    """获取或创建服务器 session ID，持久化到文件避免 reload 时变化"""
    DATA_DIR.mkdir(exist_ok=True)
    session_file = DATA_DIR / ".server_session_id"

    if session_file.exists():
        try:
            stored_id = session_file.read_text().strip()
            if stored_id:
                return stored_id
        except Exception:
            pass

    # 创建新的
    new_id = str(uuid.uuid4())
    try:
        session_file.write_text(new_id)
        print(f"[Config] 创建新的 SERVER_SESSION_ID: {new_id[:8]}...")
    except Exception as e:
        print(f"[Config] 无法保存 SERVER_SESSION_ID: {e}")
    return new_id

SERVER_SESSION_ID = _get_or_create_server_session_id()

# ============== 服务配置 ==============
SERVER_HOST = os.getenv("JARVIS_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("JARVIS_PORT", "6790"))

# ============== 其他路径配置 ==============
INSTANCES_DIR = PROJECT_ROOT / "instances"
SUBAGENTS_DIR = PROJECT_ROOT / ".claude" / "agents"
WEB_DIR = PROJECT_ROOT / "web"

# ============== QQ (NapCat OneBot11) 配置 ==============
NAPCAT_API_URL = os.getenv("NAPCAT_API_URL", "http://localhost:3000")
NAPCAT_TOKEN = os.getenv("NAPCAT_TOKEN", "")
def _parse_int_list(env_key: str) -> list:
    result = []
    for x in os.getenv(env_key, "").split(","):
        x = x.strip()
        if x:
            try:
                result.append(int(x))
            except ValueError:
                print(f"[Config] 警告: {env_key} 中的 '{x}' 不是有效数字，已跳过")
    return result

QQ_ALLOWED_USERS = _parse_int_list("QQ_ALLOWED_USERS")
QQ_ALLOWED_GROUPS = _parse_int_list("QQ_ALLOWED_GROUPS")
QQ_GROUP_AT_ONLY = os.getenv("QQ_GROUP_AT_ONLY", "true").lower() == "true"

# ============== 可用工具列表 ==============
AVAILABLE_TOOLS = [
    {"id": "Read", "name": "Read", "description": "读取文件内容"},
    {"id": "Write", "name": "Write", "description": "创建新文件"},
    {"id": "Edit", "name": "Edit", "description": "修改现有文件"},
    {"id": "MultiEdit", "name": "MultiEdit", "description": "批量编辑多个文件"},
    {"id": "Glob", "name": "Glob", "description": "匹配文件路径"},
    {"id": "Grep", "name": "Grep", "description": "搜索文件内容"},
    {"id": "LS", "name": "LS", "description": "列出目录内容"},
    {"id": "Bash", "name": "Bash", "description": "执行 shell 命令"},
    {"id": "BashOutput", "name": "BashOutput", "description": "检查后台进程输出"},
    {"id": "KillShell", "name": "KillShell", "description": "终止后台进程"},
    {"id": "Task", "name": "Task", "description": "调用子代理执行任务"},
    {"id": "TodoRead", "name": "TodoRead", "description": "读取 todo 列表"},
    {"id": "TodoWrite", "name": "TodoWrite", "description": "写入 todo 列表"},
    {"id": "NotebookRead", "name": "NotebookRead", "description": "读取 Jupyter Notebook 单元格"},
    {"id": "NotebookEdit", "name": "NotebookEdit", "description": "编辑 Jupyter Notebook 单元格"},
    {"id": "WebSearch", "name": "WebSearch", "description": "搜索网页"},
    {"id": "WebFetch", "name": "WebFetch", "description": "获取网页内容"},
    {"id": "Skill", "name": "Skill", "description": "执行自定义技能"},
]


# ============== Claude Session 路径 ==============

def _get_instance_cwd() -> Optional[str]:
    """从 _default.json 读取实例 cwd（CLI 用此路径作为项目根，影响 session 存储位置）"""
    default_file = INSTANCES_DIR / "_default.json"
    if default_file.exists():
        try:
            with open(default_file, "r", encoding="utf-8") as f:
                return json.load(f).get("cwd")
        except Exception:
            pass
    return None


def get_claude_sessions_dir() -> Path:
    """Claude session 目录（~/.claude/projects/...），不再隔离"""
    cwd = _get_instance_cwd()
    base_path = cwd if cwd else str(PROJECT_ROOT)
    escaped_path = base_path.replace("/", "-")
    return Path.home() / ".claude" / "projects" / escaped_path


def get_claude_sessions_index() -> Path:
    return get_claude_sessions_dir() / "sessions-index.json"


def update_session_index(session_id: str, first_prompt: str = "", message_count: int = 0):
    """更新 sessions-index.json（SDK 不维护索引，JARVIS 自行更新）"""
    index_file = get_claude_sessions_index()
    sessions_dir = get_claude_sessions_dir()
    jsonl_file = sessions_dir / f"{session_id}.jsonl"

    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    mtime = int(jsonl_file.stat().st_mtime * 1000) if jsonl_file.exists() else int(time.time() * 1000)

    try:
        if index_file.exists():
            with open(index_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            cwd = _get_instance_cwd()
            data = {"version": 1, "entries": [], "originalPath": cwd or str(PROJECT_ROOT)}

        entries = data.get("entries", [])
        existing = next((e for e in entries if e.get("sessionId") == session_id), None)

        if existing:
            existing["fileMtime"] = mtime
            existing["modified"] = now
            if message_count:
                existing["messageCount"] = message_count
            if first_prompt and existing.get("firstPrompt", "").startswith("No prompt"):
                existing["firstPrompt"] = first_prompt
        else:
            entries.append({
                "sessionId": session_id,
                "fullPath": str(sessions_dir / session_id),
                "fileMtime": mtime,
                "firstPrompt": first_prompt or "No prompt",
                "summary": "",
                "messageCount": message_count or 1,
                "created": now,
                "modified": now,
                "gitBranch": "",
                "projectPath": _get_instance_cwd() or str(PROJECT_ROOT),
                "isSidechain": False,
            })

        data["entries"] = entries
        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        print(f"[Config] Failed to update session index: {e}")


# ============== Instance 配置加载 ==============

def load_instance_config(instance_id: str) -> dict:
    """加载实例配置：先读 _default.json，再用 {instance_id}.json 覆盖"""
    config = {}

    # 1. 加载默认配置
    default_file = INSTANCES_DIR / "_default.json"
    if default_file.exists():
        try:
            with open(default_file, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            print(f"[Config] Failed to load _default.json: {e}")

    # 2. 加载实例特定配置并覆盖
    instance_file = INSTANCES_DIR / f"{instance_id}.json"
    if instance_file.exists():
        try:
            with open(instance_file, "r", encoding="utf-8") as f:
                instance_config = json.load(f)
                for key, value in instance_config.items():
                    if not key.startswith("_"):  # 忽略 _comment 等
                        config[key] = value
        except Exception as e:
            print(f"[Config] Failed to load {instance_id}.json: {e}")

    # 3. 如果指定了 system_prompt_file，从文件加载
    if config.get("system_prompt_file"):
        prompt_path = PROJECT_ROOT / config["system_prompt_file"]
        if prompt_path.exists():
            try:
                config["system_prompt"] = prompt_path.read_text(encoding="utf-8")
            except Exception as e:
                print(f"[Config] Failed to load prompt file: {e}")

    return config


def load_subagents() -> list:
    subagents = []
    if SUBAGENTS_DIR.exists():
        for file in SUBAGENTS_DIR.glob("*.md"):
            try:
                content = file.read_text(encoding="utf-8")
                if content.startswith("---"):
                    end = content.find("---", 3)
                    if end != -1:
                        frontmatter = content[3:end].strip()
                        name = file.stem
                        description = ""
                        tools = []
                        model = "sonnet"
                        for line in frontmatter.split("\n"):
                            if line.startswith("name:"):
                                name = line.split(":", 1)[1].strip()
                            elif line.startswith("description:"):
                                description = line.split(":", 1)[1].strip()
                            elif line.startswith("tools:"):
                                tools = [t.strip() for t in line.split(":", 1)[1].split(",")]
                            elif line.startswith("model:"):
                                model = line.split(":", 1)[1].strip()
                        subagents.append({
                            "id": file.stem,
                            "name": name,
                            "description": description,
                            "tools": tools,
                            "model": model,
                            "file": str(file)
                        })
            except Exception as e:
                print(f"[Error] Failed to load subagent {file}: {e}")
    return subagents


def build_subagents_dict(subagent_ids: List[str]) -> dict:
    subagents = {}
    all_subagents = load_subagents()
    subagent_map = {s["id"]: s for s in all_subagents}
    for sid in subagent_ids:
        if sid in subagent_map:
            info = subagent_map[sid]
            try:
                prompt = Path(info["file"]).read_text(encoding="utf-8")
                subagents[sid] = AgentDefinition(
                    description=info["description"],
                    prompt=prompt,
                    tools=info["tools"],
                    model=info["model"]
                )
            except Exception as e:
                print(f"[Error] Failed to load subagent {sid}: {e}")
    return subagents



# load_claude_sessions / get_session_title 已迁移到 SDK 接口（sessions.py）
