"""
Claude Agent SDK - JARVIS Server v2
常驻小克 + 多浏览器共享 + 回调支持 + 任务超时检查
端口: 6789
"""

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Optional, List, Set, Dict
from contextlib import asynccontextmanager

# 服务启动时生成唯一 ID，用于前端判断是否需要清空历史
SERVER_SESSION_ID = str(uuid.uuid4())

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import uvicorn
import httpx
import os
import sys
import subprocess

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    AssistantMessage,
    TextBlock,
    ToolUseBlock,
    ResultMessage,
    AgentDefinition,
    UserMessage,
    SystemMessage,
)

# ============== 配置 ==============
AGENTS_DIR = Path(__file__).parent / "agents"
SUBAGENTS_DIR = Path(__file__).parent / ".claude" / "agents"
WEB_DIR = Path(__file__).parent / "web"
PROJECT_PATH = Path(__file__).parent.resolve()

# ============== QQ (NapCat OneBot11) 配置 ==============
NAPCAT_API_URL = os.getenv("NAPCAT_API_URL", "http://localhost:3000")
NAPCAT_TOKEN = os.getenv("NAPCAT_TOKEN", "")
QQ_ALLOWED_USERS = [int(x) for x in os.getenv("QQ_ALLOWED_USERS", "").split(",") if x.strip()]
QQ_ALLOWED_GROUPS = [int(x) for x in os.getenv("QQ_ALLOWED_GROUPS", "").split(",") if x.strip()]
QQ_GROUP_AT_ONLY = os.getenv("QQ_GROUP_AT_ONLY", "true").lower() == "true"  # 群聊是否仅响应@消息

# QQ 消息上下文追踪（source → 回复目标）
_qq_contexts: Dict[str, dict] = {}

# NapCat HTTP client（延迟初始化）
_napcat_http: Optional[httpx.AsyncClient] = None

def _get_napcat_http() -> httpx.AsyncClient:
    global _napcat_http
    if _napcat_http is None:
        headers = {"Authorization": f"Bearer {NAPCAT_TOKEN}"} if NAPCAT_TOKEN else {}
        _napcat_http = httpx.AsyncClient(base_url=NAPCAT_API_URL, headers=headers, timeout=15.0)
    return _napcat_http

def _parse_qq_message(message) -> str:
    """从 OneBot11 消息段提取纯文本"""
    if isinstance(message, str):
        return message.strip()
    parts = []
    for seg in message:
        if seg.get("type") == "text":
            parts.append(seg["data"].get("text", ""))
        elif seg.get("type") == "image":
            parts.append("[图片]")
        elif seg.get("type") == "face":
            parts.append("[表情]")
    return "".join(parts).strip()

def _qq_message_has_at_bot(message, self_id) -> bool:
    """检查群消息是否 @了机器人"""
    if isinstance(message, str):
        return False
    for seg in message:
        if seg.get("type") == "at" and str(seg.get("data", {}).get("qq")) == str(self_id):
            return True
    return False

async def _send_qq_message(user_id: int = None, group_id: int = None, text: str = ""):
    """通过 NapCat API 发送消息到 QQ"""
    if not text.strip():
        return
    http = _get_napcat_http()
    message = [{"type": "text", "data": {"text": text}}]
    try:
        if group_id:
            await http.post("/send_group_msg", json={"group_id": group_id, "message": message})
        elif user_id:
            await http.post("/send_private_msg", json={"user_id": user_id, "message": message})
    except Exception as e:
        print(f"[QQ] 发送消息失败: {e}")

# Claude Code session 存储路径
def get_claude_sessions_dir() -> Path:
    """获取 Claude Code 的 session 存储目录"""
    # Claude 使用项目路径的转义形式作为目录名
    escaped_path = str(PROJECT_PATH).replace("/", "-")
    return Path.home() / ".claude" / "projects" / escaped_path

def get_claude_sessions_index() -> Path:
    """获取 Claude Code 的 sessions-index.json 路径"""
    return get_claude_sessions_dir() / "sessions-index.json"

# ============== Claude Session 管理 ==============

def load_claude_sessions() -> list:
    """加载 Claude Code 的 session 列表"""
    index_file = get_claude_sessions_index()
    sessions_dir = get_claude_sessions_dir()
    if not index_file.exists():
        return []

    try:
        with open(index_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            entries = data.get("entries", [])
            # 过滤掉 JSONL 文件不存在的 session（已删除）
            valid_entries = []
            for entry in entries:
                session_id = entry.get("sessionId", "")
                jsonl_file = sessions_dir / f"{session_id}.jsonl"
                if jsonl_file.exists():
                    valid_entries.append(entry)
            # 按修改时间降序排序
            valid_entries.sort(key=lambda x: x.get("modified", ""), reverse=True)
            return valid_entries
    except Exception as e:
        print(f"[Error] Failed to load Claude sessions: {e}")
        return []

def get_session_title(session: dict) -> str:
    """从 session 获取标题（使用 firstPrompt 的前30个字符）"""
    first_prompt = session.get("firstPrompt", "New Chat")
    # 移除 system-status 标签
    if "<system-status" in first_prompt:
        import re
        first_prompt = re.sub(r'<system-status[^>]*>.*?</system-status>\s*', '', first_prompt, flags=re.DOTALL)
    # 清理并截断
    title = first_prompt.strip()[:40]
    return title if title else "New Chat"


AVAILABLE_TOOLS = [
    # 文件系统
    {"id": "Read", "name": "Read", "description": "读取文件内容"},
    {"id": "Write", "name": "Write", "description": "创建新文件"},
    {"id": "Edit", "name": "Edit", "description": "修改现有文件"},
    {"id": "MultiEdit", "name": "MultiEdit", "description": "批量编辑多个文件"},
    {"id": "Glob", "name": "Glob", "description": "匹配文件路径"},
    {"id": "Grep", "name": "Grep", "description": "搜索文件内容"},
    {"id": "LS", "name": "LS", "description": "列出目录内容"},
    # 命令执行
    {"id": "Bash", "name": "Bash", "description": "执行 shell 命令"},
    {"id": "BashOutput", "name": "BashOutput", "description": "检查后台进程输出"},
    {"id": "KillShell", "name": "KillShell", "description": "终止后台进程"},
    # 任务管理
    {"id": "Task", "name": "Task", "description": "调用子代理执行任务"},
    {"id": "TodoRead", "name": "TodoRead", "description": "读取 todo 列表"},
    {"id": "TodoWrite", "name": "TodoWrite", "description": "写入 todo 列表"},
    # Notebook
    {"id": "NotebookRead", "name": "NotebookRead", "description": "读取 Jupyter Notebook 单元格"},
    {"id": "NotebookEdit", "name": "NotebookEdit", "description": "编辑 Jupyter Notebook 单元格"},
    # 网络
    {"id": "WebSearch", "name": "WebSearch", "description": "搜索网页"},
    {"id": "WebFetch", "name": "WebFetch", "description": "获取网页内容"},
    # 技能
    {"id": "Skill", "name": "Skill", "description": "执行自定义技能"},
]


# ============== 工具函数 ==============

def load_agent_configs():
    configs = {}
    if AGENTS_DIR.exists():
        for file in AGENTS_DIR.glob("*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    
                    # 检查是否有外部 prompt 文件（优先使用 .md 文件）
                    prompt_file = AGENTS_DIR / "prompts" / f"{config['id']}.md"
                    if prompt_file.exists():
                        config["system_prompt"] = prompt_file.read_text(encoding="utf-8")
                    
                    configs[config["id"]] = config
            except Exception as e:
                print(f"[Error] Failed to load {file}: {e}")
    return configs


def load_subagents():
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


def build_subagents_dict(subagent_ids: List[str]):
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


def get_mcp_servers_from_config(mcp_config_path: Optional[str]):
    """从 MCP 配置文件获取 MCP 服务器列表"""
    if not mcp_config_path:
        return []

    config_file = Path(__file__).parent / mcp_config_path
    if not config_file.exists():
        return []

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config = json.load(f)
            servers = config.get("mcpServers", {})
            return [{"id": name, "name": name, "url": info.get("url", "")}
                    for name, info in servers.items()]
    except Exception:
        return []


# ============== Pydantic Models ==============

class AgentConfig(BaseModel):
    id: str
    name: str
    description: str
    system_prompt: str
    allowed_tools: List[str]
    mcp_enabled: bool = False
    mcp_servers: Optional[str] = None
    model: str = "opus"
    subagents: List[str] = []


# ============== 任务管理器 ==============

class TaskManager:
    """管理已注册的任务和超时检查"""

    def __init__(self):
        self.tasks: Dict[str, dict] = {}  # task_id -> task_info
        self._check_task: Optional[asyncio.Task] = None
        self._broadcast_callback = None  # 用于广播任务状态变化

    def set_broadcast_callback(self, callback):
        """设置广播回调函数"""
        self._broadcast_callback = callback

    async def _broadcast_task_update(self, task_info: dict, event_type: str):
        """广播任务状态更新"""
        if self._broadcast_callback:
            await self._broadcast_callback({
                "type": "task_update",
                "event": event_type,
                "task": task_info,
                "all_tasks": self.get_all_tasks()
            })

    def register(self, task_id: str, timeout_minutes: int, description: str = "", total_steps: int = 0):
        """注册任务"""
        task_info = {
            "task_id": task_id,
            "description": description,
            "timeout_minutes": timeout_minutes,
            "registered_at": time.time(),
            "expires_at": time.time() + timeout_minutes * 60,
            "status": "running",
            "progress": 0,
            "total_steps": total_steps,
            "current_step": ""
        }
        self.tasks[task_id] = task_info
        print(f"[TaskManager] 注册任务: {task_id} (超时: {timeout_minutes}分钟)")
        return task_info

    async def register_async(self, task_id: str, timeout_minutes: int, description: str = "", total_steps: int = 0):
        """注册任务（异步版本，支持广播）"""
        task_info = self.register(task_id, timeout_minutes, description, total_steps)
        await self._broadcast_task_update(task_info, "registered")
        return task_info

    def complete(self, task_id: str):
        """标记任务完成"""
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = "done"
            self.tasks[task_id]["progress"] = self.tasks[task_id].get("total_steps", 1) or 1
            print(f"[TaskManager] 任务完成: {task_id}")
            return self.tasks[task_id]
        return None

    async def complete_async(self, task_id: str):
        """标记任务完成（异步版本）"""
        task_info = self.complete(task_id)
        if task_info:
            await self._broadcast_task_update(task_info, "completed")
        return task_info

    def update_progress(self, task_id: str, progress: int = None, current_step: str = "", status: str = None):
        """更新任务进度"""
        if task_id in self.tasks:
            if progress is not None:
                self.tasks[task_id]["progress"] = progress
            if current_step:
                self.tasks[task_id]["current_step"] = current_step
            if status:
                self.tasks[task_id]["status"] = status
            return self.tasks[task_id]
        return None

    async def update_progress_async(self, task_id: str, progress: int = None, current_step: str = "", status: str = None):
        """更新任务进度（异步版本）"""
        task_info = self.update_progress(task_id, progress, current_step, status)
        if task_info:
            await self._broadcast_task_update(task_info, "progress")
        return task_info

    def block(self, task_id: str, reason: str = ""):
        """标记任务阻塞"""
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = "blocked"
            self.tasks[task_id]["block_reason"] = reason
            print(f"[TaskManager] 任务阻塞: {task_id} - {reason}")
            return self.tasks[task_id]
        return None

    async def block_async(self, task_id: str, reason: str = ""):
        """标记任务阻塞（异步版本）"""
        task_info = self.block(task_id, reason)
        if task_info:
            await self._broadcast_task_update(task_info, "blocked")
        return task_info

    def renew(self, task_id: str, extra_minutes: int = None):
        """续期任务（延长超时时间）"""
        if task_id in self.tasks:
            task = self.tasks[task_id]
            # 如果没指定额外时间，使用原来的 timeout_minutes
            minutes = extra_minutes or task.get("timeout_minutes", 20)
            task["expires_at"] = time.time() + minutes * 60
            task["status"] = "running"  # 续期后重置为运行中
            print(f"[TaskManager] 任务续期: {task_id} (+{minutes}分钟)")
            return task
        return None

    async def renew_async(self, task_id: str, extra_minutes: int = None):
        """续期任务（异步版本）"""
        task_info = self.renew(task_id, extra_minutes)
        if task_info:
            await self._broadcast_task_update(task_info, "renewed")
        return task_info

    def remove(self, task_id: str):
        """移除任务"""
        if task_id in self.tasks:
            task_info = self.tasks.pop(task_id)
            print(f"[TaskManager] 移除任务: {task_id}")
            return task_info
        return None

    async def remove_async(self, task_id: str):
        """移除任务（异步版本）"""
        task_info = self.remove(task_id)
        if task_info:
            await self._broadcast_task_update(task_info, "removed")
        return task_info

    def get_expired_tasks(self) -> List[dict]:
        """获取已超时的任务"""
        now = time.time()
        expired = []
        for task_id, info in self.tasks.items():
            if info["status"] == "running" and now > info["expires_at"]:
                expired.append(info)
        return expired

    def get_all_tasks(self) -> List[dict]:
        """获取所有任务"""
        now = time.time()
        tasks = []
        for task in self.tasks.values():
            task_copy = task.copy()
            # 计算剩余时间
            if task_copy["status"] == "running":
                remaining = task_copy["expires_at"] - now
                task_copy["remaining_seconds"] = max(0, int(remaining))
            tasks.append(task_copy)
        return tasks

    async def start_checker(self, on_timeout_callback):
        """启动超时检查器"""
        async def check_loop():
            while True:
                await asyncio.sleep(30)  # 每30秒检查一次
                expired = self.get_expired_tasks()
                for task in expired:
                    task["status"] = "timeout"
                    print(f"[TaskManager] 任务超时: {task['task_id']}")
                    await self._broadcast_task_update(task, "timeout")
                    await on_timeout_callback(task["task_id"], task["description"])

        self._check_task = asyncio.create_task(check_loop())
        print("[TaskManager] 超时检查器已启动")

    async def stop_checker(self):
        """停止超时检查器"""
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
            print("[TaskManager] 超时检查器已停止")


# 全局任务管理器
task_manager = TaskManager()


# ============== JARVIS 核心 ==============

class JarvisCore:
    """常驻小克核心 - 单例"""

    def __init__(self):
        self.client: Optional[ClaudeSDKClient] = None
        self.subscribers: Set[WebSocket] = set()  # WebSocket 订阅者
        self.message_queue: asyncio.Queue = asyncio.Queue()  # 消息队列
        self.is_processing = False  # 是否正在处理消息
        self.current_agent = "default"
        self.current_session_id: Optional[str] = None  # 当前 Claude session ID
        self._client_context = None
        self._interrupted = False  # 是否被用户中断
        self._queue_worker_task = None  # 队列处理任务

    async def start(self, agent_id: str = "default", resume_session: str = None):
        """启动常驻小克

        Args:
            agent_id: Agent 配置 ID
            resume_session: 要恢复的 Claude session ID（可选）
        """
        configs = load_agent_configs()
        config = configs.get(agent_id, {
            "system_prompt": "你是小克，一个有帮助的AI助手。",
            "allowed_tools": ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Task"],
            "model": "opus",
            "subagents": []
        })

        subagents = build_subagents_dict(config.get("subagents", []))

        # 根据 mcp_enabled 决定是否加载 MCP 配置
        mcp_enabled = config.get("mcp_enabled", False)
        if mcp_enabled:
            setting_sources = ["user", "project"]  # 加载 ~/.claude/ 和 .claude/ 的配置
            mcp_servers = config.get("mcp_servers")
        else:
            setting_sources = []  # 不加载任何外部配置
            mcp_servers = None

        options = ClaudeAgentOptions(
            system_prompt=config.get("system_prompt", ""),
            allowed_tools=config.get("allowed_tools", []),
            agents=subagents if subagents else None,
            mcp_servers=mcp_servers,
            permission_mode="acceptEdits",
            model=config.get("model", "opus"),
            setting_sources=setting_sources,
            resume=resume_session,  # 恢复指定的 session
        )

        self._client_context = ClaudeSDKClient(options=options)
        self.client = await self._client_context.__aenter__()
        self.current_agent = agent_id
        self.current_session_id = resume_session

        # 启动消息队列处理器
        self._queue_worker_task = asyncio.create_task(self._queue_worker())

        if resume_session:
            print(f"[JARVIS] 小克已启动 (agent: {agent_id}, 恢复 session: {resume_session[:8]}...)")
        else:
            print(f"[JARVIS] 小克已启动 (agent: {agent_id}, 新 session)")

    async def stop(self):
        """停止小克"""
        # 停止队列处理器
        if self._queue_worker_task:
            self._queue_worker_task.cancel()
            try:
                await self._queue_worker_task
            except asyncio.CancelledError:
                pass
            self._queue_worker_task = None

        if self._client_context:
            try:
                await self._client_context.__aexit__(None, None, None)
            except (AttributeError, RuntimeError) as e:
                # SDK 内部兼容性问题，忽略
                print(f"[JARVIS] 停止时忽略错误: {e}")
            self.client = None
            self._client_context = None
            print("[JARVIS] 小克已停止")

    async def restart(self, agent_id: str = None, resume_session: str = None):
        """重启小克（切换 agent 或 session）

        Args:
            agent_id: Agent 配置 ID（可选，默认使用当前 agent）
            resume_session: 要恢复的 session ID（可选，None 表示新建 session）
        """
        await self.stop()
        await self.start(agent_id or self.current_agent, resume_session)

    def subscribe(self, ws: WebSocket):
        """添加 WebSocket 订阅者"""
        self.subscribers.add(ws)
        print(f"[JARVIS] 浏览器连接 (当前 {len(self.subscribers)} 个)")

    def unsubscribe(self, ws: WebSocket):
        """移除 WebSocket 订阅者"""
        self.subscribers.discard(ws)
        print(f"[JARVIS] 浏览器断开 (当前 {len(self.subscribers)} 个)")

    async def broadcast(self, data: dict):
        """广播消息给所有订阅者"""
        dead = set()
        for ws in self.subscribers:
            try:
                await ws.send_json(data)
            except:
                dead.add(ws)
        self.subscribers -= dead

    async def enqueue_message(self, message: str, source: str = "user", attachments: List[dict] = None):
        """将消息加入队列（不阻塞，立即返回）"""
        await self.message_queue.put({
            "message": message,
            "source": source,
            "attachments": attachments
        })
        queue_size = self.message_queue.qsize()
        print(f"[JARVIS] 消息入队 (队列长度: {queue_size})")

    async def _queue_worker(self):
        """后台队列处理器 - 依次处理队列中的消息"""
        print("[JARVIS] 队列处理器已启动")
        while True:
            try:
                # 从队列获取消息（阻塞等待）
                item = await self.message_queue.get()

                # 处理消息
                await self.send_message(
                    message=item["message"],
                    source=item["source"],
                    attachments=item.get("attachments")
                )

                # 标记任务完成
                self.message_queue.task_done()

            except asyncio.CancelledError:
                print("[JARVIS] 队列处理器已停止")
                break
            except Exception as e:
                print(f"[JARVIS] 队列处理器错误: {e}")

    def _build_system_status(self) -> str:
        """构建当前系统状态信息"""
        from datetime import datetime

        lines = ["<system-status hint=\"系统自动添加，供监控任务进度，无需针对此项回复\">"]
        lines.append(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # 获取任务列表
        tasks = task_manager.get_all_tasks()
        if tasks:
            lines.append(f"运行中的任务 ({len(tasks)}):")
            for t in tasks:
                progress_str = f"{t.get('progress', 0)}/{t.get('total_steps', '?')}" if t.get('total_steps') else "进行中"
                remaining = t.get('remaining_seconds', 0)
                remaining_min = remaining // 60 if remaining else 0
                lines.append(f"  - [{t['task_id']}] {t.get('description', '无描述')} | 进度: {progress_str} | {remaining_min}分钟后检查")
        else:
            lines.append("运行中的任务: 无")

        # 队列状态
        queue_size = self.message_queue.qsize()
        if queue_size > 0:
            lines.append(f"消息队列: {queue_size} 条待处理")

        lines.append("</system-status>")
        return "\n".join(lines)

    async def send_message(self, message: str, source: str = "user", attachments: List[dict] = None):
        """发送消息给小克（统一入口）

        Args:
            message: 文本消息
            source: 消息来源 (browser, callback, timeout)
            attachments: 附件列表，每个附件格式:
                - 图片: {"type": "image", "media_type": "image/jpeg", "data": "base64..."}
                - PDF: {"type": "document", "media_type": "application/pdf", "data": "base64..."}
                - 文本文件: {"type": "text_file", "name": "file.txt", "content": "..."}
        """
        if not self.client:
            print("[JARVIS] 小克未启动")
            return

        try:
            self.is_processing = True
            self._interrupted = False  # 重置中断标志

            att_count = len(attachments) if attachments else 0
            print(f"[JARVIS] 收到消息: {message[:50] if message else '(仅附件)'}... (附件: {att_count})")

            # 通知所有浏览器：收到消息（不包含系统状态）
            await self.broadcast({
                "type": "user_message",
                "content": message,  # 原始消息，不含 system-status
                "source": source
            })

            # 构建带状态的消息
            system_status = self._build_system_status()

            # 构建 Claude SDK 格式的 content
            if attachments:
                # 多模态消息：使用 content blocks 列表
                content_blocks = []

                for att in attachments:
                    if att.get("type") == "image":
                        # 图片: {"type": "image", "source": {"type": "base64", "media_type": "...", "data": "..."}}
                        content_blocks.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": att.get("media_type", "image/jpeg"),
                                "data": att.get("data", "")
                            }
                        })
                    elif att.get("type") == "document":
                        # PDF: {"type": "document", "source": {"type": "base64", "media_type": "...", "data": "..."}}
                        content_blocks.append({
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": att.get("media_type", "application/pdf"),
                                "data": att.get("data", "")
                            }
                        })
                    elif att.get("type") == "text_file":
                        # 文本文件：转换为文本块
                        file_name = att.get("name", "file.txt")
                        file_content = att.get("content", "")
                        content_blocks.append({
                            "type": "text",
                            "text": f"[文件: {file_name}]\n```\n{file_content}\n```"
                        })

                # 添加系统状态和用户消息文本
                text_content = f"{system_status}\n\n{message}" if message else system_status
                content_blocks.append({
                    "type": "text",
                    "text": text_content
                })

                # 使用 AsyncIterable 发送多模态消息
                async def multimodal_prompt():
                    yield {
                        "type": "user",
                        "message": {"role": "user", "content": content_blocks},
                        "parent_tool_use_id": None,
                    }

                await self.client.query(multimodal_prompt())
            else:
                # 纯文本消息
                full_message = f"{system_status}\n\n{message}"
                await self.client.query(full_message)

            # 接收响应并广播
            qq_text_chunks = []  # 收集 QQ 回复文本
            is_qq_source = source.startswith("qq:")

            async for msg in self.client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            await self.broadcast({
                                "type": "text",
                                "content": block.text
                            })
                            if is_qq_source:
                                qq_text_chunks.append(block.text)
                        elif isinstance(block, ToolUseBlock):
                            await self.broadcast({
                                "type": "tool",
                                "name": block.name,
                                "input": block.input
                            })
                # UserMessage 是内部消息（工具结果等），不需要显示给用户
                elif isinstance(msg, SystemMessage):
                    # 处理系统消息
                    await self.broadcast({
                        "type": "system",
                        "subtype": msg.subtype,
                        "data": msg.data
                    })
                elif isinstance(msg, ResultMessage):
                    await self.broadcast({"type": "result"})

            # 根据是否被中断发送不同消息
            if self._interrupted:
                await self.broadcast({"type": "cancelled"})
            else:
                await self.broadcast({"type": "done"})

            # QQ 回复路由：合并所有文本块，一次性发回 QQ
            if is_qq_source and qq_text_chunks:
                ctx = _qq_contexts.get(source)
                if ctx:
                    reply_text = "\n".join(qq_text_chunks)
                    await _send_qq_message(
                        user_id=ctx.get("user_id"),
                        group_id=ctx.get("group_id"),
                        text=reply_text
                    )

        except Exception as e:
            print(f"[JARVIS] 错误: {e}")
            await self.broadcast({"type": "error", "message": str(e)})

        finally:
            self.is_processing = False

    async def handle_callback(self, task_id: str, status: str, reason: str = "",
                               progress: int = None, current_step: str = ""):
        """处理子进程回调（仅通知，不直接更新状态）

        子 Claude 的汇报仅作参考，主 Claude 需要自行判断是否更新任务状态。
        可以通过以下方式更新任务：
        - task_manager.update_progress_async(task_id, progress, current_step, status)
        - task_manager.complete_async(task_id)
        - task_manager.block_async(task_id, reason)
        """
        print(f"[JARVIS] 收到子进程汇报: task={task_id}, status={status}")

        # 构建汇报信息，通知主 Claude（通过队列）
        if status == "done":
            message = f"[子进程汇报] 任务 {task_id} 报告已完成当前阶段任务。请确认当前所处步骤/剩余步骤，并下发下一阶段任务。若已经完成所有步骤，将当前任务标记为 done。"
            await self.enqueue_message(message, source="callback")
        elif status == "blocked":
            message = f"[子进程汇报] 任务 {task_id} 报告遇到阻塞: {reason}。请核实并决定下一步。"
            await self.enqueue_message(message, source="callback")
        elif status == "progress":
            # 进度汇报记录日志，不打扰主 Claude
            progress_info = f"progress={progress}" if progress else ""
            step_info = f"step={current_step}" if current_step else ""
            print(f"[JARVIS] 任务 {task_id} 进度汇报: {progress_info} {step_info}")

    async def handle_timeout(self, task_id: str, description: str):
        """处理任务超时"""
        print(f"[JARVIS] 任务超时: task={task_id}")
        message = f"[系统通知] 任务 {task_id} ({description}) 到达超时时间，请确认任务是否在正常进行。若原因是子进程没有正确发送回调，请手动注册/延长任务时间，每隔 15 分钟监督进度，并下发下一步任务，直到达到目标步骤。"
        await self.enqueue_message(message, source="timeout")


# 全局单例
jarvis = JarvisCore()


# ============== FastAPI 应用 ==============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    await jarvis.start("default")
    # 设置任务管理器的广播回调
    task_manager.set_broadcast_callback(jarvis.broadcast)
    await task_manager.start_checker(jarvis.handle_timeout)
    yield
    # 关闭时
    await task_manager.stop_checker()
    await jarvis.stop()


app = FastAPI(title="JARVIS Server v2", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


# ============== 页面路由 ==============

@app.get("/", response_class=HTMLResponse)
async def index():
    html_file = WEB_DIR / "index.html"
    return html_file.read_text(encoding="utf-8")


@app.get("/settings", response_class=HTMLResponse)
async def settings():
    html_file = WEB_DIR / "settings.html"
    if html_file.exists():
        return html_file.read_text(encoding="utf-8")
    return "<h1>Settings page not found</h1>"


# ============== REST API ==============

@app.get("/api/agents")
async def get_agents():
    configs = load_agent_configs()
    return [{"id": c["id"], "name": c["name"], "description": c.get("description", "")}
            for c in configs.values()]


@app.get("/api/agents/{agent_id}")
async def get_agent(agent_id: str):
    configs = load_agent_configs()
    if agent_id not in configs:
        raise HTTPException(status_code=404, detail="Agent not found")
    return configs[agent_id]


@app.get("/api/tools")
async def get_tools():
    return AVAILABLE_TOOLS


@app.get("/api/subagents")
async def get_subagents():
    return load_subagents()


@app.post("/api/agents")
async def create_agent(config: AgentConfig):
    """创建新 agent"""
    file_path = AGENTS_DIR / f"{config.id}.json"
    if file_path.exists():
        raise HTTPException(status_code=400, detail="Agent already exists")

    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(config.dict(), f, ensure_ascii=False, indent=2)

    return {"status": "ok", "id": config.id}


@app.put("/api/agents/{agent_id}")
async def update_agent(agent_id: str, config: AgentConfig):
    """更新 agent 配置"""
    file_path = AGENTS_DIR / f"{agent_id}.json"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Agent not found")

    config_dict = config.dict()
    config_dict["id"] = agent_id

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(config_dict, f, ensure_ascii=False, indent=2)

    return {"status": "ok", "id": agent_id}


@app.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str):
    """删除 agent"""
    if agent_id == "default":
        raise HTTPException(status_code=400, detail="Cannot delete default agent")

    file_path = AGENTS_DIR / f"{agent_id}.json"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Agent not found")

    file_path.unlink()
    return {"status": "ok"}


@app.get("/api/mcp-servers")
async def get_mcp_servers(config_path: str = Query(default=".mcp.json")):
    """获取 MCP 服务器列表"""
    return get_mcp_servers_from_config(config_path)


# ============== 会话管理 API (Claude Session) ==============

@app.get("/api/claude-sessions")
async def get_claude_sessions():
    """获取 Claude Code 的历史会话列表"""
    sessions = load_claude_sessions()
    # 转换为前端友好的格式
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
        "current_session": jarvis.current_session_id
    }


@app.post("/api/claude-sessions/new")
async def create_new_claude_session():
    """创建新的 Claude 会话（重启小克，不带 resume）"""
    await jarvis.restart(resume_session=None)
    # 通知所有客户端
    await jarvis.broadcast({
        "type": "session_changed",
        "session_id": None,
        "is_new": True
    })
    return {"status": "ok", "message": "新会话已创建"}


@app.put("/api/claude-sessions/{session_id}/activate")
async def activate_claude_session(session_id: str):
    """切换到指定的 Claude 会话"""
    # 验证 session 存在
    sessions = load_claude_sessions()
    session = next((s for s in sessions if s.get("sessionId") == session_id), None)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 重启小克并恢复 session
    await jarvis.restart(resume_session=session_id)

    # 通知所有客户端
    await jarvis.broadcast({
        "type": "session_changed",
        "session_id": session_id,
        "title": get_session_title(session)
    })

    return {
        "status": "ok",
        "session": {
            "id": session_id,
            "title": get_session_title(session),
            "messageCount": session.get("messageCount", 0)
        }
    }


@app.get("/api/claude-sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    """获取指定会话的消息历史（从 JSONL 文件读取）"""
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
                        # 只提取用户消息和助手消息
                        if msg_type == "user":
                            content = entry.get("message", {}).get("content", "")
                            if isinstance(content, list):
                                # 提取文本内容
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
        print(f"[Error] Failed to read session messages: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"messages": messages}


@app.delete("/api/claude-sessions/{session_id}")
async def delete_claude_session(session_id: str):
    """删除指定的 Claude session（只删除 JSONL 文件，索引在加载时会自动过滤）"""
    sessions_dir = get_claude_sessions_dir()
    jsonl_file = sessions_dir / f"{session_id}.jsonl"

    # 删除 JSONL 文件
    if jsonl_file.exists():
        try:
            jsonl_file.unlink()
            print(f"[JARVIS] 已删除 session 文件: {session_id}")
        except Exception as e:
            print(f"[Error] Failed to delete session file: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to delete session file: {e}")
    else:
        print(f"[JARVIS] Session 文件不存在: {session_id}")

    # 如果删除的是当前 session，清空引用
    if jarvis.current_session_id == session_id:
        jarvis.current_session_id = None

    return {"status": "deleted", "session_id": session_id}


@app.get("/api/status")
async def get_status():
    """获取 JARVIS 状态"""
    return {
        "running": jarvis.client is not None,
        "agent": jarvis.current_agent,
        "subscribers": len(jarvis.subscribers),
        "processing": jarvis.is_processing
    }


@app.post("/api/restart")
async def restart_jarvis(agent_id: str = Query(default=None)):
    """重启小克（可选切换 agent）"""
    await jarvis.restart(agent_id)
    return {"status": "ok", "agent": jarvis.current_agent}


@app.post("/api/restart-server")
async def restart_server():
    """重启整个服务器"""
    def do_restart():
        import time as _time
        _time.sleep(1)
        python = sys.executable
        script = sys.argv[0]
        if sys.platform == "win32":
            subprocess.Popen([python, script], creationflags=subprocess.CREATE_NEW_CONSOLE)
            os._exit(0)
        else:
            os.execv(python, [python] + sys.argv)

    import threading
    t = threading.Thread(target=do_restart)
    t.daemon = True
    t.start()

    return {"status": "ok", "message": "Server restarting..."}


# ============== 任务管理端点 ==============

class TaskRegisterData(BaseModel):
    task_id: str
    timeout_minutes: int = 20
    description: str = ""
    total_steps: int = 0


class TaskProgressData(BaseModel):
    progress: Optional[int] = None
    current_step: str = ""
    status: Optional[str] = None


@app.post("/task/register")
async def register_task(data: TaskRegisterData):
    """注册任务（启用超时检查）"""
    task_info = await task_manager.register_async(
        data.task_id,
        data.timeout_minutes,
        data.description,
        data.total_steps
    )
    return {
        "status": "ok",
        "task_id": data.task_id,
        "expires_in_minutes": data.timeout_minutes,
        "task": task_info
    }


@app.get("/task/list")
async def list_tasks():
    """获取所有注册的任务"""
    return {"tasks": task_manager.get_all_tasks()}


@app.put("/task/{task_id}/progress")
async def update_task_progress(task_id: str, data: TaskProgressData):
    """更新任务进度"""
    task_info = await task_manager.update_progress_async(
        task_id,
        data.progress,
        data.current_step,
        data.status
    )
    if not task_info:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "ok", "task": task_info}


@app.delete("/task/{task_id}")
async def remove_task(task_id: str):
    """移除任务"""
    await task_manager.remove_async(task_id)
    return {"status": "ok"}


class TaskRenewData(BaseModel):
    extra_minutes: Optional[int] = None  # 不指定则使用原 timeout_minutes


@app.put("/task/{task_id}/renew")
async def renew_task(task_id: str, data: TaskRenewData = None):
    """续期任务（延长超时时间）"""
    extra_minutes = data.extra_minutes if data else None
    task_info = await task_manager.renew_async(task_id, extra_minutes)
    if not task_info:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "ok", "task": task_info}


# ============== 回调端点 ==============

class CallbackData(BaseModel):
    task_id: str
    status: str  # done, blocked, progress, running
    reason: Optional[str] = ""
    progress: Optional[int] = None
    current_step: Optional[str] = ""


@app.post("/callback")
async def task_callback(data: CallbackData):
    """接收 Claude Code 子进程的回调（仅通知，不直接更新状态）"""
    print(f"[Callback] 收到子进程汇报: task={data.task_id}, status={data.status}, reason={data.reason}")

    # 只通知 JARVIS，由主 Claude 决定是否更新任务状态
    # 子 Claude 的汇报仅作参考，不直接修改 TaskManager
    await jarvis.handle_callback(
        data.task_id,
        data.status,
        data.reason or "",
        progress=data.progress,
        current_step=data.current_step
    )
    return {"status": "ok", "message": f"Callback received for task {data.task_id}"}


# ============== QQ (NapCat OneBot11) 端点 ==============

@app.post("/qq/webhook")
async def qq_webhook(request: Request):
    """接收 NapCat 推送的 QQ 消息（OneBot11 HTTP Client 模式）"""
    data = await request.json()
    post_type = data.get("post_type")

    # 只处理消息事件
    if post_type != "message":
        return {"status": "ignored"}

    user_id = data.get("user_id")
    group_id = data.get("group_id")
    message_type = data.get("message_type")  # "private" 或 "group"
    raw_message = data.get("message", "")
    self_id = data.get("self_id")  # 机器人自己的 QQ 号

    # 白名单检查
    if QQ_ALLOWED_USERS and user_id not in QQ_ALLOWED_USERS:
        return {"status": "denied", "reason": "user not in allowlist"}
    if group_id and QQ_ALLOWED_GROUPS and group_id not in QQ_ALLOWED_GROUPS:
        return {"status": "denied", "reason": "group not in allowlist"}

    # 群聊 @机器人 检查
    if message_type == "group" and QQ_GROUP_AT_ONLY:
        if not _qq_message_has_at_bot(raw_message, self_id):
            return {"status": "ignored", "reason": "not mentioned"}

    # 提取文本
    text = _parse_qq_message(raw_message)
    if not text:
        return {"status": "ignored", "reason": "empty message"}

    # 构造来源标识
    if message_type == "group":
        source = f"qq:group:{group_id}"
    else:
        source = f"qq:private:{user_id}"

    # 存储上下文用于回复路由
    _qq_contexts[source] = {
        "user_id": user_id,
        "group_id": group_id if message_type == "group" else None,
        "message_type": message_type,
    }

    sender = data.get("sender", {})
    nickname = sender.get("card") or sender.get("nickname") or str(user_id)
    print(f"[QQ] 收到消息: [{message_type}] {nickname}: {text[:50]}")

    # 入队处理（复用现有 JarvisCore 队列）
    await jarvis.enqueue_message(message=text, source=source)
    return {"status": "ok"}


# ============== WebSocket ==============

@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket 聊天 - 连接到常驻小克"""
    await websocket.accept()
    jarvis.subscribe(websocket)

    # 发送连接成功消息（包含 server_session_id 供前端判断是否清空历史）
    await websocket.send_json({
        "type": "connected",
        "message": f"已连接到小克 ({jarvis.current_agent})",
        "agent": jarvis.current_agent,
        "server_session_id": SERVER_SESSION_ID
    })

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "message")

            if msg_type == "message":
                message = data.get("message", "").strip()
                attachments = data.get("attachments", [])
                # 有消息或有附件时才处理
                if message or attachments:
                    # 消息入队（由队列处理器依次处理）
                    await jarvis.enqueue_message(
                        message,
                        source="browser",
                        attachments=attachments if attachments else None
                    )

            elif msg_type == "cancel":
                if jarvis.client and jarvis.is_processing:
                    jarvis._interrupted = True
                    try:
                        await jarvis.client.interrupt()
                    except:
                        pass

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS] 错误: {e}")
    finally:
        jarvis.unsubscribe(websocket)
        # 如果正在处理消息且没有其他订阅者，中断当前处理
        if jarvis.is_processing and len(jarvis.subscribers) == 0 and jarvis.client:
            print("[WS] 所有浏览器断开，中断当前消息处理")
            try:
                await jarvis.client.interrupt()
            except:
                pass


# ============== 主入口 ==============

if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  JARVIS Server v2")
    print("  http://localhost:6789")
    print("")
    print("  端点:")
    print("    POST /task/register  - 注册任务（启用超时检查）")
    print("    GET  /task/list      - 查看所有任务")
    print("    POST /callback       - 任务完成回调")
    print("    POST /qq/webhook     - QQ 消息接收（NapCat OneBot11）")
    print("")
    print(f"  QQ 配置:")
    print(f"    NapCat API: {NAPCAT_API_URL}")
    print(f"    用户白名单: {QQ_ALLOWED_USERS or '全部放行'}")
    print(f"    群白名单: {QQ_ALLOWED_GROUPS or '全部放行'}")
    print(f"    群聊仅@响应: {QQ_GROUP_AT_ONLY}")
    print("=" * 50 + "\n")

    uvicorn.run("server:app", host="0.0.0.0", port=6789, reload=True)
