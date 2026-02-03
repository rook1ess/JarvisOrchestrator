"""AgentInstance：封装单个 ClaudeSDKClient"""

import asyncio
import time
from datetime import datetime
from typing import Optional, List, Callable, Awaitable

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    AssistantMessage,
    TextBlock,
    ToolUseBlock,
    ResultMessage,
    SystemMessage,
)

from server.config import load_instance_config, build_subagents_dict, SERVER_PORT
from server.session_registry import session_registry
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from server.agents.manager import AgentManager


class AgentInstance:
    """封装单个 Claude SDK 客户端实例"""

    def __init__(self, instance_id: str):
        self.instance_id = instance_id
        self.client: Optional[ClaudeSDKClient] = None
        self.current_session_id: Optional[str] = None
        self.is_processing = False
        self.message_queue: asyncio.Queue = asyncio.Queue()
        self._client_context = None
        self._interrupted = False
        self._queue_worker_task = None
        self._task_manager = None  # injected
        self._agent_manager: "AgentManager" = None  # injected
        self.last_active_at: float = time.time()  # 最后活跃时间

    def set_task_manager(self, tm):
        self._task_manager = tm

    def set_agent_manager(self, am: "AgentManager"):
        self._agent_manager = am

    async def start(self, resume_session: str = None):
        """启动 SDK 客户端"""
        # Session 安全检查
        if not await session_registry.acquire(resume_session, self.instance_id):
            raise RuntimeError(f"Session {resume_session} 已被其他实例占用")

        # 加载实例配置（_default.json + {instance_id}.json 合并）
        config = load_instance_config(self.instance_id)
        if not config:
            config = {
                "system_prompt": "你是小克，一个有帮助的AI助手。",
                "allowed_tools": ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "Task"],
                "model": "opus",
                "subagents": []
            }

        subagents = build_subagents_dict(config.get("subagents", []))

        mcp_enabled = config.get("mcp_enabled", False)
        if mcp_enabled:
            setting_sources = ["user", "project"]
            mcp_servers = config.get("mcp_servers")
        else:
            setting_sources = []
            mcp_servers = None

        options = ClaudeAgentOptions(
            system_prompt=config.get("system_prompt", ""),
            allowed_tools=config.get("allowed_tools", []),
            agents=subagents if subagents else None,
            mcp_servers=mcp_servers,
            permission_mode="acceptEdits",
            model=config.get("model", "opus"),
            setting_sources=setting_sources,
            resume=resume_session,
        )

        self._client_context = ClaudeSDKClient(options=options)
        self.client = await self._client_context.__aenter__()
        self.current_session_id = resume_session
        self._queue_worker_task = asyncio.create_task(self._queue_worker())

        label = f"恢复 session: {resume_session[:8]}..." if resume_session else "新 session"
        print(f"[Instance:{self.instance_id}] 已启动 ({label})")

    async def stop(self):
        """停止客户端并释放 session"""
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
                print(f"[Agent:{self.instance_id}] 停止时忽略错误: {e}")
            self.client = None
            self._client_context = None

        await session_registry.release(self.current_session_id, self.instance_id)
        print(f"[Agent:{self.instance_id}] 已停止")

    async def restart(self, resume_session: str = None):
        """重启实例，重新加载配置。默认保留当前 session。"""
        session_to_resume = resume_session if resume_session else self.current_session_id
        await self.stop()
        await self.start(session_to_resume)

    async def enqueue(self, message: str, source: str = "user",
                      attachments: List[dict] = None,
                      response_callback: Callable = None):
        """将消息加入处理队列"""
        self.last_active_at = time.time()
        await self.message_queue.put({
            "message": message,
            "source": source,
            "attachments": attachments,
            "response_callback": response_callback,
        })
        print(f"[Agent:{self.instance_id}] 消息入队 (队列长度: {self.message_queue.qsize()})")

    async def interrupt(self):
        if self.client and self.is_processing:
            self._interrupted = True
            try:
                await self.client.interrupt()
            except Exception:
                pass

    def _build_system_status(self) -> str:
        lines = ['<system-status hint="系统自动添加，供监控任务进度，无需针对此项回复">']
        lines.append(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"服务端口: {SERVER_PORT}")
        lines.append(f"当前实例: {self.instance_id}")
        lines.append(f"API 基址: http://localhost:{SERVER_PORT}")

        if self._task_manager:
            tasks = self._task_manager.get_all_tasks()
            if tasks:
                lines.append(f"运行中的任务 ({len(tasks)}):")
                for t in tasks:
                    progress_str = f"{t.get('progress', 0)}/{t.get('total_steps', '?')}" if t.get('total_steps') else "进行中"
                    remaining = t.get('remaining_seconds', 0)
                    remaining_min = remaining // 60 if remaining else 0
                    lines.append(f"  - [{t['task_id']}] {t.get('description', '无描述')} | 进度: {progress_str} | {remaining_min}分钟后检查")
            else:
                lines.append("运行中的任务: 无")

        # 兄弟实例列表
        if self._agent_manager:
            siblings = []
            for iid, inst in self._agent_manager.get_all_instances().items():
                if iid != self.instance_id:
                    status = "处理中" if inst.is_processing else "空闲"
                    siblings.append(f"  - {iid} ({status})")
            if siblings:
                lines.append(f"其他实例 ({len(siblings)}):")
                lines.extend(siblings)
                lines.append("提示: 可通过 jarvis_send_message 工具向其他实例发消息")

        queue_size = self.message_queue.qsize()
        if queue_size > 0:
            lines.append(f"消息队列: {queue_size} 条待处理")

        lines.append("</system-status>")
        return "\n".join(lines)

    async def _queue_worker(self):
        print(f"[Agent:{self.instance_id}] 队列处理器已启动")
        while True:
            try:
                item = await self.message_queue.get()
                await self._process_message(
                    message=item["message"],
                    source=item["source"],
                    attachments=item.get("attachments"),
                    response_callback=item.get("response_callback"),
                )
                self.message_queue.task_done()
            except asyncio.CancelledError:
                print(f"[Agent:{self.instance_id}] 队列处理器已停止")
                break
            except Exception as e:
                print(f"[Agent:{self.instance_id}] 队列处理器错误: {e}")

    async def _process_message(self, message: str, source: str = "user",
                                attachments: List[dict] = None,
                                response_callback: Callable = None):
        """处理单条消息"""
        if not self.client:
            print(f"[Agent:{self.instance_id}] 客户端未启动")
            return

        async def emit(data: dict):
            if response_callback:
                await response_callback(data, {"instance_id": self.instance_id, "source": source})

        try:
            self.is_processing = True
            self._interrupted = False

            att_count = len(attachments) if attachments else 0
            print(f"[Agent:{self.instance_id}] 收到消息: {message[:50] if message else '(仅附件)'}... (附件: {att_count})")

            await emit({"type": "user_message", "content": message, "source": source})

            system_status = self._build_system_status()

            if attachments:
                content_blocks = []
                for att in attachments:
                    if att.get("type") == "image":
                        content_blocks.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": att.get("media_type", "image/jpeg"),
                                "data": att.get("data", "")
                            }
                        })
                    elif att.get("type") == "document":
                        content_blocks.append({
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": att.get("media_type", "application/pdf"),
                                "data": att.get("data", "")
                            }
                        })
                    elif att.get("type") == "text_file":
                        file_name = att.get("name", "file.txt")
                        file_content = att.get("content", "")
                        content_blocks.append({
                            "type": "text",
                            "text": f"[文件: {file_name}]\n```\n{file_content}\n```"
                        })

                text_content = f"{system_status}\n\n{message}" if message else system_status
                content_blocks.append({"type": "text", "text": text_content})

                async def multimodal_prompt():
                    yield {
                        "type": "user",
                        "message": {"role": "user", "content": content_blocks},
                        "parent_tool_use_id": None,
                    }

                await self.client.query(multimodal_prompt())
            else:
                full_message = f"{system_status}\n\n{message}"
                await self.client.query(full_message)

            async for msg in self.client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            await emit({"type": "text", "content": block.text})
                        elif isinstance(block, ToolUseBlock):
                            await emit({"type": "tool", "name": block.name, "input": block.input})
                elif isinstance(msg, SystemMessage):
                    await emit({"type": "system", "subtype": msg.subtype, "data": msg.data})
                elif isinstance(msg, ResultMessage):
                    # 从 ResultMessage 捕获 session_id
                    if msg.session_id:
                        self.current_session_id = msg.session_id
                    await emit({
                        "type": "result",
                        "session_id": msg.session_id,
                        "cost_usd": msg.total_cost_usd,
                        "duration_ms": msg.duration_ms,
                        "num_turns": msg.num_turns,
                        "usage": msg.usage,
                    })

            if self._interrupted:
                await emit({"type": "cancelled"})
            else:
                await emit({"type": "done"})

        except Exception as e:
            print(f"[Agent:{self.instance_id}] 错误: {e}")
            await emit({"type": "error", "message": str(e)})
        finally:
            self.is_processing = False
