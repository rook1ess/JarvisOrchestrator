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
    ThinkingBlock,
    ToolUseBlock,
    ToolResultBlock,
    ResultMessage,
    SystemMessage,
    RateLimitEvent,
    HookMatcher,
)
from claude_agent_sdk.types import StreamEvent

from server.config import load_instance_config, build_subagents_dict, SERVER_PORT, get_claude_sessions_dir, update_session_index
from server.session_registry import session_registry
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from server.agents.manager import AgentManager

_UNSET = object()  # 哨兵值：区分"未传参"和"显式传 None"

# 客户端死亡需要恢复的错误关键词
_DEAD_CLIENT_PATTERNS = [
    "terminated process",
    "exit code",
    "Command failed",
    "Fatal error in message reader",
]


def _is_dead_client_error(error: Exception) -> bool:
    """判断异常是否表示 CLI 子进程已死"""
    msg = str(error)
    return any(p in msg for p in _DEAD_CLIENT_PATTERNS)


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
        self._pending_clear = False  # 标记：当前消息处理完后清除 session
        self._pending_restart = False  # 标记：当前消息处理完后重启（保留 session）
        self._pending_session: object = _UNSET  # 延迟切换 session（_UNSET=无变更, None=新session, str=指定session）
        self._lifecycle_lock = asyncio.Lock()  # 保护 start/stop/restart 并发
        self._mcp_toggles: dict[str, bool] = {}  # 运行时 MCP 开关覆盖
        self._queue_worker_task = None
        self._task_manager = None  # injected
        self._agent_manager: "AgentManager" = None  # injected
        self.last_active_at: float = time.time()  # 最后活跃时间

    def set_task_manager(self, tm):
        self._task_manager = tm

    def set_agent_manager(self, am: "AgentManager"):
        self._agent_manager = am

    def _load_mcp_servers_from_file(self, mcp_config_path: str) -> dict | None:
        """从文件路径加载 MCP 服务器配置为 dict，解决 cwd 不同导致相对路径找不到的问题"""
        import json
        from server.config import PROJECT_ROOT

        config_path = PROJECT_ROOT / mcp_config_path
        if not config_path.exists():
            print(f"[Instance:{self.instance_id}] MCP 配置文件不存在: {config_path}")
            return None
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                servers = data.get("mcpServers", {})
            print(f"[Instance:{self.instance_id}] MCP 配置已加载: {list(servers.keys())}")
            return servers if servers else None
        except Exception as e:
            print(f"[Instance:{self.instance_id}] MCP 配置加载失败: {e}")
            return None

    def _filter_mcp_servers(self, mcp_config, only_list, disabled_list):
        """过滤 MCP 服务器：支持白名单和黑名单"""
        import json
        from server.config import PROJECT_ROOT

        # 如果是文件路径，加载内容
        if isinstance(mcp_config, str):
            config_path = PROJECT_ROOT / mcp_config
            if not config_path.exists():
                print(f"[Instance:{self.instance_id}] MCP 配置文件不存在: {mcp_config}")
                return None
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    servers = data.get("mcpServers", {})
            except Exception as e:
                print(f"[Instance:{self.instance_id}] MCP 配置加载失败: {e}")
                return None
        elif isinstance(mcp_config, dict):
            servers = mcp_config
        else:
            return mcp_config

        # 应用白名单
        if only_list:
            servers = {k: v for k, v in servers.items() if k in only_list}
            print(f"[Instance:{self.instance_id}] MCP 白名单过滤: {list(servers.keys())}")

        # 应用黑名单
        if disabled_list:
            servers = {k: v for k, v in servers.items() if k not in disabled_list}
            print(f"[Instance:{self.instance_id}] MCP 黑名单过滤后: {list(servers.keys())}")

        return servers if servers else None

    def _session_jsonl_exists(self, session_id: str) -> bool:
        """检查 session JSONL 文件是否存在（SDK 不会预检，我们在此拦截）"""
        if not session_id:
            return False
        jsonl_file = get_claude_sessions_dir() / f"{session_id}.jsonl"
        return jsonl_file.exists()

    async def start(self, resume_session: str = None):
        """启动 SDK 客户端"""
        # Pre-flight: 检查 resume session 的 JSONL 是否存在（必须在 acquire 之前，
        # 否则 acquire 注册了不存在的 session 导致 registry 泄漏）
        if resume_session and not self._session_jsonl_exists(resume_session):
            print(f"[Instance:{self.instance_id}] Session {resume_session[:8]}... 的 JSONL 不存在，改为新 session")
            resume_session = None

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
            mcp_servers_config = config.get("mcp_servers")

            # setting_sources 让 CLI 从 CWD 的项目目录和用户配置发现 MCP servers
            # 但如果配置指定了额外的 MCP 文件路径（如 .mcp.json），CWD 可能不在同一个目录
            # 需要显式加载并传给 SDK，确保这些 server 始终可用
            if isinstance(mcp_servers_config, str):
                mcp_servers = self._load_mcp_servers_from_file(mcp_servers_config)
            elif isinstance(mcp_servers_config, dict):
                mcp_servers = mcp_servers_config
            else:
                mcp_servers = None

            # 收集需要启动后禁用的 server 列表
            self._mcp_disabled_on_start = set(config.get("mcp_servers_disabled", []))
            for name, enabled in self._mcp_toggles.items():
                if enabled:
                    self._mcp_disabled_on_start.discard(name)
                else:
                    self._mcp_disabled_on_start.add(name)
        else:
            setting_sources = []
            mcp_servers = None
            self._mcp_disabled_on_start = set()

        # Bash 沙箱配置
        sandbox_config = config.get("sandbox")
        cwd = config.get("cwd")

        permission_mode = config.get("permission_mode", "bypassPermissions")
        # When bypassing permissions, all tools are available — skip whitelist
        allowed_tools = [] if permission_mode == "bypassPermissions" else config.get("allowed_tools", [])

        # 全局信息通过 system_prompt append 注入（只发一次，不随消息重复）
        static_context = f"\n\n---\n实例: {self.instance_id} | 端口: {SERVER_PORT} | API: http://localhost:{SERVER_PORT}"

        raw_prompt = config.get("system_prompt", "")
        if isinstance(raw_prompt, dict):
            system_prompt = raw_prompt  # 已经是 preset/file 格式
        else:
            system_prompt = (raw_prompt + static_context) if raw_prompt else static_context

        options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            allowed_tools=allowed_tools,
            disallowed_tools=config.get("disallowed_tools", []),
            agents=subagents if subagents else None,
            mcp_servers=mcp_servers,
            permission_mode=permission_mode,
            model=config.get("model", "opus"),
            effort=config.get("effort", "max"),
            setting_sources=setting_sources,
            resume=resume_session,
            sandbox=sandbox_config,
            cwd=cwd,
            include_partial_messages=True,
            hooks={
                "UserPromptSubmit": [HookMatcher(hooks=[self._build_prompt_hook()])],
            },
        )

        # Optional resource limits from config
        if config.get("max_turns"):
            options.max_turns = config["max_turns"]
        if config.get("max_budget_usd"):
            options.max_budget_usd = config["max_budget_usd"]

        self._client_context = ClaudeSDKClient(options=options)
        self.client = await self._client_context.__aenter__()
        self.current_session_id = resume_session
        self._queue_worker_task = asyncio.create_task(self._queue_worker())

        # 启动后禁用配置中标记为 disabled 的 MCP servers
        if self._mcp_disabled_on_start:
            for name in self._mcp_disabled_on_start:
                try:
                    await self.client.toggle_mcp_server(name, False)
                    print(f"[Instance:{self.instance_id}] MCP disabled: {name}")
                except Exception as e:
                    print(f"[Instance:{self.instance_id}] MCP disable failed ({name}): {e}")

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

    async def restart(self, resume_session=_UNSET):
        """重启实例，重新加载配置。
        - 不传参：保留当前 session
        - 传 None：创建全新 session
        - 传 session_id：恢复指定 session
        """
        async with self._lifecycle_lock:
            if resume_session is _UNSET:
                session_to_resume = self.current_session_id
            else:
                session_to_resume = resume_session
            await self.stop()
            try:
                await self.start(session_to_resume)
            except Exception:
                self.client = None  # 标记为死亡，让健康检查器处理
                raise

    def schedule_session_switch(self, session_id):
        """延迟切换 session — 不立即重启，等当前消息处理完或下一条消息时生效。
        传 None 表示新建 session，传 session_id 表示恢复指定 session。
        """
        self._pending_session = session_id
        if self.is_processing:
            print(f"[Agent:{self.instance_id}] Session 切换已排队（等待当前消息完成）: {session_id}")
        else:
            print(f"[Agent:{self.instance_id}] Session 切换已排队（下条消息时生效）: {session_id}")

    async def enqueue(self, message: str, source: str = "user",
                      attachments: List[dict] = None,
                      response_callback: Callable = None,
                      message_id: str = None):
        """将消息加入处理队列"""
        self.last_active_at = time.time()
        await self.message_queue.put({
            "message": message,
            "source": source,
            "attachments": attachments,
            "response_callback": response_callback,
            "message_id": message_id,
        })
        print(f"[Agent:{self.instance_id}] 消息入队 (队列长度: {self.message_queue.qsize()})")

    async def interrupt(self):
        if self.client and self.is_processing:
            self._interrupted = True
            try:
                await self.client.interrupt()
            except Exception:
                pass

    def _build_hook_context(self) -> str:
        """构建 UserPromptSubmit hook 注入的动态上下文（时间 + 任务列表）"""
        lines = [f"[时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"]

        if self._task_manager:
            tasks = self._task_manager.get_all_tasks()
            if tasks:
                lines.append(f"[运行中的任务 ({len(tasks)}):")
                for t in tasks:
                    progress_str = f"{t.get('progress', 0)}/{t.get('total_steps', '?')}" if t.get('total_steps') else "进行中"
                    remaining = t.get('remaining_seconds', 0)
                    remaining_min = remaining // 60 if remaining else 0
                    lines.append(f"  - [{t['task_id']}] {t.get('description', '无描述')} | 进度: {progress_str} | {remaining_min}分钟后检查")
                lines.append("]")

        return "\n".join(lines)

    def _build_prompt_hook(self):
        """UserPromptSubmit hook：每条消息注入动态上下文（时间 + 任务 + 触发式记忆召回）"""
        instance = self  # closure capture

        async def on_prompt_submit(input_data, tool_use_id, context):
            base_ctx = instance._build_hook_context()

            # 触发式记忆召回（轻量：命中关键词才搜，返回标题列表约 80-150 tokens）
            try:
                user_text = ""
                if isinstance(input_data, dict):
                    user_text = input_data.get("prompt") or input_data.get("user_prompt") or ""
                    if not user_text and isinstance(input_data.get("messages"), list):
                        # fallback 从 messages 取最后一条 user
                        for m in reversed(input_data["messages"]):
                            if m.get("role") == "user":
                                c = m.get("content")
                                if isinstance(c, str):
                                    user_text = c
                                elif isinstance(c, list):
                                    user_text = "\n".join(
                                        p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text"
                                    )
                                break
                if user_text:
                    from server.memory_recall import build_recall_context
                    recall_ctx = await build_recall_context(user_text)
                    if recall_ctx:
                        base_ctx = f"{base_ctx}\n\n{recall_ctx}"
            except Exception as e:
                print(f"[Agent:{instance.instance_id}] 触发式召回失败（非致命）: {e}")

            return {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": base_ctx,
                }
            }

        return on_prompt_submit

    def schedule_clear(self):
        """标记：当前消息处理完后清除 session，开启全新对话"""
        self._pending_clear = True
        print(f"[Agent:{self.instance_id}] 已标记清除 session（将在当前消息处理完后执行）")

    def schedule_restart(self):
        """标记：当前消息处理完后重启实例（保留 session，重载配置）"""
        self._pending_restart = True
        print(f"[Agent:{self.instance_id}] 已标记重启（将在当前消息处理完后执行）")

    def toggle_mcp_servers(self, toggles: dict[str, bool]) -> dict:
        """切换 MCP 服务器开关并触发延迟重启。
        Args:
            toggles: {server_name: True/False} — True=启用, False=禁用
        Returns: 变更后的 MCP 状态
        """
        for name, enabled in toggles.items():
            self._mcp_toggles[name] = enabled
        self.schedule_restart()
        return self.get_mcp_status_info()

    def get_mcp_status_info(self) -> dict:
        """获取 MCP 服务器状态（含运行时覆盖）"""
        config = load_instance_config(self.instance_id)
        if not config.get("mcp_enabled", False):
            return {"mcp_enabled": False, "servers": {}}

        mcp_servers = config.get("mcp_servers")
        if isinstance(mcp_servers, str):
            mcp_servers = self._load_mcp_servers_from_file(mcp_servers)
        if not isinstance(mcp_servers, dict):
            return {"mcp_enabled": True, "servers": {}}

        # 合并文件配置 + 运行时覆盖
        disabled = set(config.get("mcp_servers_disabled", []))
        for name, enabled in self._mcp_toggles.items():
            if enabled:
                disabled.discard(name)
            else:
                disabled.add(name)

        servers = {}
        for name in mcp_servers:
            servers[name] = "enabled" if name not in disabled else "disabled"
        return {"mcp_enabled": True, "servers": servers}

    # ---- SDK Runtime API delegates ----

    async def sdk_set_model(self, model: str):
        """Switch model at runtime without restart"""
        if self.client:
            await self.client.set_model(model)
            print(f"[Agent:{self.instance_id}] Model changed to: {model}")

    async def sdk_get_mcp_status(self) -> dict | None:
        """Get live MCP server connection status from SDK"""
        if self.client:
            return await self.client.get_mcp_status()
        return None

    async def sdk_get_context_usage(self) -> dict | None:
        """Get detailed context window usage from SDK"""
        if self.client:
            return await self.client.get_context_usage()
        return None

    async def sdk_toggle_mcp(self, server_name: str, enabled: bool):
        """Toggle MCP server at runtime without restart"""
        if self.client:
            await self.client.toggle_mcp_server(server_name, enabled)
            print(f"[Agent:{self.instance_id}] MCP '{server_name}' → {'enabled' if enabled else 'disabled'}")

    async def sdk_set_permission_mode(self, mode: str):
        """Switch permission mode at runtime"""
        if self.client:
            await self.client.set_permission_mode(mode)
            print(f"[Agent:{self.instance_id}] Permission mode → {mode}")

    async def _queue_worker(self):
        print(f"[Agent:{self.instance_id}] 队列处理器已启动")
        while True:
            item = None
            try:
                item = await self.message_queue.get()

                # 在处理消息前，检查是否需要切换 session
                if self._pending_session is not _UNSET:
                    target_session = self._pending_session
                    self._pending_session = _UNSET
                    print(f"[Agent:{self.instance_id}] 执行延迟 session 切换: {target_session}")
                    try:
                        await self.restart(resume_session=target_session)
                    except Exception as e:
                        print(f"[Agent:{self.instance_id}] Session 切换失败: {e}")

                try:
                    await self._process_message(
                        message=item["message"],
                        source=item["source"],
                        attachments=item.get("attachments"),
                        response_callback=item.get("response_callback"),
                        message_id=item.get("message_id"),
                    )
                except asyncio.CancelledError:
                    # restart() 导致的取消 — 通知前端
                    cb = item.get("response_callback")
                    if cb:
                        try:
                            await cb({"type": "cancelled", "message_id": item.get("message_id")},
                                     {"instance_id": self.instance_id, "source": item.get("source", "")})
                        except Exception:
                            pass
                    raise
                except Exception as e:
                    if _is_dead_client_error(e):
                        print(f"[Agent:{self.instance_id}] 检测到客户端死亡: {e}")
                        await self._recover_and_retry(item)
                    else:
                        raise
                self.message_queue.task_done()

                # 检查是否需要清除 session
                if self._pending_clear:
                    self._pending_clear = False
                    self._pending_restart = False
                    print(f"[Agent:{self.instance_id}] 执行 session 清除...")
                    await self.restart(resume_session=None)
                    if self._agent_manager:
                        self._agent_manager.clear_instance_config_key(self.instance_id, "last_session_id")
                    print(f"[Agent:{self.instance_id}] 新 session 已就绪")

                # 检查延迟 session 切换（消息处理完后执行）
                elif self._pending_session is not _UNSET:
                    target_session = self._pending_session
                    self._pending_session = _UNSET
                    print(f"[Agent:{self.instance_id}] 执行延迟 session 切换: {target_session}")
                    await self.restart(resume_session=target_session)

                # 检查是否需要重启（保留 session，重载配置）
                elif self._pending_restart:
                    self._pending_restart = False
                    print(f"[Agent:{self.instance_id}] 执行延迟重启...")
                    await self.restart()
                    print(f"[Agent:{self.instance_id}] 重启完成，配置已重载")
            except asyncio.CancelledError:
                print(f"[Agent:{self.instance_id}] 队列处理器已停止")
                break
            except Exception as e:
                print(f"[Agent:{self.instance_id}] 队列处理器错误: {e}")
                cb = item.get("response_callback") if item else None
                if cb:
                    try:
                        await cb({"type": "error", "message": str(e), "message_id": item.get("message_id")},
                                 {"instance_id": self.instance_id, "source": item.get("source", "")})
                    except Exception:
                        pass

    async def _recover_and_retry(self, item: dict):
        """客户端死亡后：重启新 session 并重试消息"""
        print(f"[Agent:{self.instance_id}] 尝试恢复：重启新 session 并重试消息")
        try:
            await self.restart(resume_session=None)
            if self._agent_manager:
                self._agent_manager.clear_instance_config_key(self.instance_id, "last_session_id")
            await self._process_message(
                message=item["message"],
                source=item["source"],
                attachments=item.get("attachments"),
                response_callback=item.get("response_callback"),
                message_id=item.get("message_id"),
            )
        except Exception as e2:
            print(f"[Agent:{self.instance_id}] 恢复失败: {e2}")

    async def _process_message(self, message: str, source: str = "user",
                                attachments: List[dict] = None,
                                response_callback: Callable = None,
                                message_id: str = None):
        """处理单条消息"""
        if not self.client:
            print(f"[Agent:{self.instance_id}] 客户端未启动")
            return

        async def emit(data: dict):
            if message_id:
                data["message_id"] = message_id
            if response_callback:
                await response_callback(data, {"instance_id": self.instance_id, "source": source})

        try:
            self.is_processing = True
            self._interrupted = False

            att_count = len(attachments) if attachments else 0
            print(f"[Agent:{self.instance_id}] 收到消息: {message[:50] if message else '(仅附件)'}... (附件: {att_count})")

            await emit({"type": "user_message", "content": message, "source": source})

            query_start = time.time()
            print(f"[Agent:{self.instance_id}] 发送 query...")

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

                content_blocks.append({"type": "text", "text": message or ""})

                async def multimodal_prompt():
                    yield {
                        "type": "user",
                        "message": {"role": "user", "content": content_blocks},
                        "parent_tool_use_id": None,
                    }

                await self.client.query(multimodal_prompt())
            else:
                await self.client.query(message)

            msg_count = 0
            last_msg_time = time.time()
            streaming_text_sent = False  # Track if text was sent via streaming deltas

            async for msg in self.client.receive_response():
                now = time.time()
                gap = now - last_msg_time
                last_msg_time = now
                msg_count += 1

                if isinstance(msg, StreamEvent):
                    event = msg.event
                    event_type = event.get("type", "")

                    if event_type == "content_block_start":
                        block = event.get("content_block", {})
                        block_type = block.get("type", "")
                        if block_type == "tool_use":
                            await emit({"type": "tool_start", "name": block.get("name", ""), "id": block.get("id", "")})
                        elif block_type == "text":
                            await emit({"type": "text_start"})

                    elif event_type == "content_block_delta":
                        delta = event.get("delta", {})
                        delta_type = delta.get("type", "")
                        if delta_type == "text_delta":
                            streaming_text_sent = True
                            await emit({"type": "text_delta", "content": delta.get("text", "")})
                        elif delta_type == "thinking_delta":
                            await emit({"type": "thinking_delta", "content": delta.get("thinking", "")})

                    elif event_type == "content_block_stop":
                        await emit({"type": "block_stop"})

                elif isinstance(msg, AssistantMessage):
                    tool_names = [b.name for b in msg.content if isinstance(b, ToolUseBlock)]
                    text_len = sum(len(b.text) for b in msg.content if isinstance(b, TextBlock))
                    print(f"[Agent:{self.instance_id}] msg#{msg_count} AssistantMessage (text:{text_len}c tools:{tool_names}) +{gap:.1f}s")
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            # Only send full text if streaming didn't already send it
                            if not streaming_text_sent:
                                await emit({"type": "text", "content": block.text})
                        elif isinstance(block, ToolUseBlock):
                            await emit({"type": "tool", "name": block.name, "input": block.input})
                        elif isinstance(block, ToolResultBlock):
                            content_preview = ""
                            if isinstance(block.content, str):
                                content_preview = block.content[:200]
                            elif isinstance(block.content, list):
                                for item in block.content:
                                    if isinstance(item, dict) and item.get("type") == "text":
                                        content_preview = item.get("text", "")[:200]
                                        break
                            await emit({
                                "type": "tool_result",
                                "tool_use_id": block.tool_use_id,
                                "is_error": block.is_error or False,
                                "content_preview": content_preview,
                            })
                    # Reset streaming flag for next turn
                    streaming_text_sent = False

                elif isinstance(msg, SystemMessage):
                    print(f"[Agent:{self.instance_id}] msg#{msg_count} System:{msg.subtype} +{gap:.1f}s")
                    if msg.subtype == "init":
                        # Capture session_id early from init message
                        init_data = msg.data if isinstance(msg.data, dict) else {}
                        if init_data.get("session_id"):
                            self.current_session_id = init_data["session_id"]
                        await emit({
                            "type": "init",
                            "session_id": init_data.get("session_id"),
                            "model": init_data.get("model"),
                            "version": init_data.get("version"),
                            "tools": init_data.get("tools"),
                            "mcp_servers": init_data.get("mcp_servers"),
                        })
                    else:
                        await emit({"type": "system", "subtype": msg.subtype, "data": msg.data})
                elif isinstance(msg, ResultMessage):
                    elapsed = now - query_start
                    print(f"[Agent:{self.instance_id}] msg#{msg_count} Result (turns:{msg.num_turns} ${msg.total_cost_usd:.4f} {elapsed:.1f}s total)")
                    if msg.session_id:
                        self.current_session_id = msg.session_id
                        update_session_index(msg.session_id, first_prompt=message, message_count=msg.num_turns)
                    await emit({
                        "type": "result",
                        "session_id": msg.session_id,
                        "cost_usd": msg.total_cost_usd,
                        "duration_ms": msg.duration_ms,
                        "num_turns": msg.num_turns,
                        "usage": msg.usage,
                    })
                elif isinstance(msg, RateLimitEvent):
                    info = msg.rate_limit_info
                    print(f"[Agent:{self.instance_id}] msg#{msg_count} RateLimit +{gap:.1f}s")
                    await emit({
                        "type": "rate_limit",
                        "info": {
                            "type": getattr(info, "type", None),
                            "retry_after_ms": getattr(info, "retry_after_ms", None),
                        },
                    })

            if self._interrupted:
                await emit({"type": "cancelled"})
            else:
                await emit({"type": "done"})

        except Exception as e:
            print(f"[Agent:{self.instance_id}] 错误: {e}")
            await emit({"type": "error", "message": str(e)})
            # 客户端死亡错误需要向上传播，触发 queue worker 的恢复机制
            if _is_dead_client_error(e):
                raise
        finally:
            self.is_processing = False
