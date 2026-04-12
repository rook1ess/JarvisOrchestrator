"""MCP Server - 挂载到 FastAPI，提供实例发现、消息传递、子进程管理、浏览器自动化工具"""

import asyncio
import base64
import json
import os
import subprocess
import time

from mcp.server.fastmcp import FastMCP

from server.config import SERVER_PORT
from server.browser import BrowserManager

mcp = FastMCP("jarvis", stateless_http=True)

_agent_manager = None
_ws_channel = None
_task_manager = None
_scheduler = None
_qq_channel = None
_message_router = None

# 浏览器管理器单例（lazy init）
_browser_manager = BrowserManager()


async def shutdown():
    """清理 MCP Server 资源（供 main.py lifespan 调用）"""
    await _browser_manager.close_all()


# 容器配置（可通过环境变量覆盖）
CONTAINER_NAME = os.environ.get("JARVIS_CONTAINER_NAME", "claude-dev")
HOST_PROJECTS = os.environ.get("JARVIS_HOST_PROJECTS", "/Users/huang/Projects/Jarvis-Work")
CONTAINER_WORKSPACE = os.environ.get("JARVIS_CONTAINER_WORKSPACE", "/home/claude/workspace")


def init(agent_manager, ws_channel, task_manager=None, scheduler=None, qq_channel=None, message_router=None):
    global _agent_manager, _ws_channel, _task_manager, _scheduler, _qq_channel, _message_router
    _agent_manager = agent_manager
    _ws_channel = ws_channel
    _task_manager = task_manager
    _scheduler = scheduler
    _qq_channel = qq_channel
    _message_router = message_router


def _resolve_instance(instance_id: str = None):
    """解析实例：传 instance_id 则查找，否则自动检测当前正在处理消息的实例（即调用者自身）"""
    if instance_id:
        return _agent_manager.get_instance(instance_id)
    for iid, inst in _agent_manager.get_all_instances().items():
        if inst.is_processing:
            return inst
    return None


# ============== 实例发现与通信 ==============

@mcp.tool()
async def jarvis_list_instances() -> list[dict]:
    """列出所有 Jarvis 实例及其状态。用于发现其他实例以便通信。"""
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
        })

    for iid, cfg in configs.items():
        if iid not in instances:
            result.append({
                "instance_id": iid,
                "status": "stopped",
                "is_processing": False,
                "queue_size": 0,
            })

    return result


@mcp.tool()
async def jarvis_restart_instance(instance_id: str) -> dict:
    """重启指定实例，重新加载配置。保留对话历史。
    如果目标实例正在处理消息（包括自身调用），重启会延迟到当前消息处理完成后执行。

    Args:
        instance_id: 要重启的实例 ID
    """
    inst = _agent_manager.get_instance(instance_id)
    if not inst:
        return {"status": "error", "message": f"Instance '{instance_id}' not found"}

    if inst.is_processing:
        # 实例正在处理消息（可能是自身调用），使用延迟重启避免死锁
        inst.schedule_restart()
        return {
            "status": "scheduled",
            "instance_id": instance_id,
            "message": "Restart scheduled after current message completes",
        }
    else:
        # 实例空闲，直接重启
        await inst.restart()
        return {"status": "ok", "instance_id": instance_id}


@mcp.tool()
async def jarvis_clear_session(instance_id: str = None) -> dict:
    """清除当前对话上下文，开启全新会话。当前回复完成后自动执行。
    调用后你的记忆将被清空，请在调用前完成所有需要的回复。

    Args:
        instance_id: 要清除的实例 ID，不传则清除调用者自身
    """
    # 获取所有实例，找到匹配的或正在处理的
    if instance_id:
        inst = _agent_manager.get_instance(instance_id)
        if not inst:
            return {"status": "error", "message": f"Instance '{instance_id}' not found"}
    else:
        # 找当前正在处理消息的实例（即调用者自身）
        inst = None
        for iid, i in _agent_manager.get_all_instances().items():
            if i.is_processing:
                inst = i
                break
        if not inst:
            return {"status": "error", "message": "No active instance found"}

    inst.schedule_clear()
    return {
        "status": "scheduled",
        "instance_id": inst.instance_id,
        "message": "Session will be cleared after current response completes",
    }


@mcp.tool()
async def jarvis_toggle_mcp(
    servers: dict[str, bool],
    instance_id: str = None,
) -> dict:
    """开关 MCP 服务器，支持一次切换多个。变更在当前回复结束后自动重启生效。

    Args:
        servers: 服务器开关映射。True=启用, False=禁用。如 {"xiaohongshu": false, "github": true}
        instance_id: 目标实例 ID，不传则自动检测调用者
    """
    if instance_id:
        inst = _agent_manager.get_instance(instance_id)
    else:
        inst = None
        for iid, i in _agent_manager.get_all_instances().items():
            if i.is_processing:
                inst = i
                break

    if not inst:
        return {"status": "error", "message": "Instance not found"}

    status = inst.toggle_mcp_servers(servers)
    return {
        "status": "scheduled",
        "instance_id": inst.instance_id,
        "message": "MCP changes will take effect after current response completes",
        **status,
    }


@mcp.tool()
async def jarvis_send_message(instance_id: str, message: str) -> dict:
    """向指定的 Jarvis Agent 实例发送消息（异步入队，不等待回复）。
    消息将进入目标实例的处理队列，目标实例会通过其原有渠道回复。
    如需得到回复，目标实例需主动使用此工具发回消息。

    Args:
        instance_id: 目标实例 ID，如 "ws-default"、"qq-default"
        message: 要发送的消息内容
    """
    inst = _agent_manager.get_instance(instance_id)
    if not inst:
        return {"status": "error", "message": f"Instance '{instance_id}' not found or stopped"}

    # 根据实例的 channel 类型选择正确的回调
    callback = _ws_channel.send_response if _ws_channel else None
    if _message_router:
        channel_type = _message_router.get_channel_type_for_instance(instance_id)
        if channel_type == "qq" and _qq_channel:
            callback = _qq_channel.send_response

    await inst.enqueue(message, source="instance:mcp", response_callback=callback)

    return {
        "status": "queued",
        "queue_position": inst.message_queue.qsize(),
    }


@mcp.tool()
async def jarvis_send_to_qq(
    message: str,
    user_id: int = None,
    group_id: int = None,
    instance_id: str = None,
) -> dict:
    """直接向 QQ 用户或群发送消息，不经过实例处理。
    可指定 user_id/group_id，或通过 instance_id 自动使用该实例最后对话的 QQ 用户。

    Args:
        message: 要发送的消息文本
        user_id: QQ 用户 ID（私聊）
        group_id: QQ 群 ID（群聊）
        instance_id: 可选，自动获取该实例最后活跃的 QQ 目标
    """
    from server.channels.qq import send_qq_message

    # 如果没指定具体目标，从 instance 的 last_active 推断
    if not user_id and not group_id and instance_id and _qq_channel:
        last = _qq_channel.get_last_active(instance_id)
        if last:
            user_id = last.get("user_id")
            group_id = last.get("group_id")

    if not user_id and not group_id:
        return {"status": "error", "message": "Must specify user_id, group_id, or instance_id with QQ history"}

    await send_qq_message(user_id=user_id, group_id=group_id, text=message)
    return {"status": "ok", "sent_to": {"user_id": user_id, "group_id": group_id}}


# ============== tmux 子进程管理 ==============

def _run(cmd: str, timeout: int = 10) -> str:
    """执行 shell 命令并返回输出"""
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=timeout
    )
    return result.stdout.strip()


def _tmux_send(session: str, text: str, extra_enters: int = 2):
    """向 tmux session 发送文本 + 多次 Enter 确保送达"""
    subprocess.run(["tmux", "send-keys", "-t", session, text, "Enter"])
    time.sleep(1)
    for _ in range(extra_enters):
        subprocess.run(["tmux", "send-keys", "-t", session, "Enter"])
        time.sleep(0.3)


def _host_to_container_path(host_path: str) -> str:
    """宿主机路径转容器路径"""
    if host_path.startswith(HOST_PROJECTS):
        return host_path.replace(HOST_PROJECTS, CONTAINER_WORKSPACE, 1)
    return host_path


def _wait_for_ready(task_id: str, timeout: int = 30, poll_interval: float = 2.0) -> dict:
    """轮询 tmux 输出，等待 Claude 就绪或检测到确认提示并自动应答。

    Returns: {"ready": True/False, "output": str, "auto_answered": list}
    """
    # 文本输入型提示：(检测模式, 自动应答内容)
    TEXT_PROMPT_PATTERNS = [
        ("Yes, proceed", "Yes, proceed"),      # trust dialog 选项
        ("[Y/n]", "y"),                         # 通用 Y/n 提示
        ("(y/N)", "y"),                         # 通用 y/N 提示
        ("yes/no", "yes"),                      # yes/no 提示
    ]
    # 方向键选择型提示：(检测模式, 按键序列)
    # Claude Code >= 2.1.39 的 --dangerously-skip-permissions 确认对话框
    ARROW_PROMPT_PATTERNS = [
        ("Yes, I accept", ["Down", "Enter"]),   # bypass permissions 确认
    ]
    # Claude 已就绪的标志：出现输入提示符
    READY_PATTERNS = ["❯", "Claude Code", ">"]
    # 排除误判：这些出现在对话框中，不算就绪
    NOT_READY_PATTERNS = ["Yes, I accept", "No, exit", "Enter to confirm"]

    auto_answered = []
    output = ""
    start = time.time()

    while time.time() - start < timeout:
        output = _run(f"tmux capture-pane -t {task_id} -p -S -30")
        if not output:
            time.sleep(poll_interval)
            continue

        # 检测方向键选择型对话框并自动应答
        for pattern, keys in ARROW_PROMPT_PATTERNS:
            if pattern in output and pattern not in [a[0] for a in auto_answered]:
                for key in keys:
                    subprocess.run(["tmux", "send-keys", "-t", task_id, key])
                    time.sleep(0.5)
                auto_answered.append((pattern, "arrow-select"))
                time.sleep(2)
                break

        # 检测文本输入型提示并自动应答
        for pattern, answer in TEXT_PROMPT_PATTERNS:
            if pattern in output and pattern not in [a[0] for a in auto_answered]:
                subprocess.run(["tmux", "send-keys", "-t", task_id, answer, "Enter"])
                auto_answered.append((pattern, answer))
                time.sleep(2)
                break

        # 检测就绪状态（排除对话框中的误判）
        last_lines = output.strip().split("\n")[-5:]
        last_text = "\n".join(last_lines)
        if any(p in last_text for p in NOT_READY_PATTERNS):
            # 还在对话框里，不算就绪
            time.sleep(poll_interval)
            continue
        if any(p in last_text for p in READY_PATTERNS):
            return {"ready": True, "output": output, "auto_answered": auto_answered}

        time.sleep(poll_interval)

    return {"ready": False, "output": output, "auto_answered": auto_answered}


@mcp.tool()
async def jarvis_spawn_task(
    task_id: str,
    prompt: str,
    description: str = "",
    working_dir: str = HOST_PROJECTS,
    timeout_minutes: int = 15,
    use_container: bool = True,
    instance_id: str = None,
) -> dict:
    """一键派生 Claude Code 子进程执行任务。
    自动完成：创建 tmux → 启动 Claude → 等待就绪 → 发送任务 → 注册超时监控。

    任务生命周期：spawn_task → [renew_task] → complete_task。
    长任务使用同一个 task_id，通过 renew_task 延长时间，不要按轮次命名（如 task-r1, task-r2），
    直接用任务名（如 poker-dev）。超时后任务不会被删除，等待 renew 或 complete。

    Args:
        task_id: (必填) 任务唯一标识，也用作 tmux session 名
        prompt: (必填) 发送给子 Claude 的完整任务描述
        description: 任务简短描述（前端展示用），不传则截取 prompt 前 100 字符
        working_dir: 宿主机工作目录绝对路径
        timeout_minutes: 超时分钟数，到期后通知中控检查
        use_container: True 用 Docker 容器模式（推荐），False 用本地模式
        instance_id: 发起任务的实例 ID，用于超时通知路由
    """
    loop = asyncio.get_running_loop()

    def _do_spawn():
        # 1. 确认 tmux session 不存在
        check = subprocess.run(
            ["tmux", "has-session", "-t", task_id],
            capture_output=True
        )
        if check.returncode == 0:
            return {"status": "error", "message": f"tmux session '{task_id}' already exists"}

        if use_container:
            # 确保容器运行
            subprocess.run(["docker", "start", CONTAINER_NAME], capture_output=True)

            # 创建 tmux session
            subprocess.run([
                "tmux", "new-session", "-d", "-s", task_id, "-x", "200", "-y", "50"
            ])

            # 获取 OAuth token
            token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
            if not token:
                return {"status": "error", "message": "CLAUDE_CODE_OAUTH_TOKEN not set"}

            container_dir = _host_to_container_path(working_dir)

            # 跳过 onboarding + 信任项目目录（避免交互式初始化卡住）
            onboarding = json.dumps({
                "hasCompletedOnboarding": True,
                "projects": {
                    container_dir: {
                        "hasTrustDialogAccepted": True,
                        "hasCompletedProjectOnboarding": True,
                    }
                }
            })
            subprocess.run(
                ["docker", "exec", "-i", CONTAINER_NAME, "bash", "-c", "cat > ~/.claude.json"],
                input=onboarding, capture_output=True, text=True,
            )

            cmd = f'docker exec -it -e CLAUDE_CODE_OAUTH_TOKEN="{token}" {CONTAINER_NAME} bash -c "cd {container_dir} && claude --dangerously-skip-permissions"'
            subprocess.run(["tmux", "send-keys", "-t", task_id, cmd, "Enter"])

            readiness = _wait_for_ready(task_id, timeout=30)
            if not readiness["ready"]:
                return {"status": "error", "message": f"Claude did not become ready within 30s. Output: {readiness['output'][-300:]}"}

            callback_host = "host.docker.internal"
            noproxy = "--noproxy '*'"
        else:
            # 本地模式
            subprocess.run([
                "tmux", "new-session", "-d", "-s", task_id,
                "-x", "200", "-y", "50", "-c", working_dir
            ])
            subprocess.run(["tmux", "send-keys", "-t", task_id, "claude --dangerously-skip-permissions", "Enter"])

            readiness = _wait_for_ready(task_id, timeout=20)
            if not readiness["ready"]:
                return {"status": "error", "message": f"Claude did not become ready within 20s. Output: {readiness['output'][-300:]}"}

            callback_host = "localhost"
            noproxy = ""

        # 2. 构建完整 prompt（含 callback 协议）
        inst_id = instance_id or ""
        noproxy_flag = f" {noproxy}" if noproxy else ""
        callback_protocol = f"""
---
<任务完成协议>
完成后执行：
curl{noproxy_flag} -X POST http://{callback_host}:{SERVER_PORT}/callback -H "Content-Type: application/json" -d '{{"task_id":"{task_id}","status":"done","instance_id":"{inst_id}"}}'

遇到问题时执行：
curl{noproxy_flag} -X POST http://{callback_host}:{SERVER_PORT}/callback -H "Content-Type: application/json" -d '{{"task_id":"{task_id}","status":"blocked","reason":"问题描述","instance_id":"{inst_id}"}}'
注意：作为子进程，你的消息可能会进入服务器的消息队列，只需要发送 curl 命令即可，发送完立马停止，不要检查服务器端的响应情况。"""

        full_prompt = prompt + callback_protocol

        # 5. 发送任务 + 多次 Enter
        _tmux_send(task_id, full_prompt, extra_enters=2)

        # 6. 等待确认 Claude 开始处理
        time.sleep(5)
        final_output = _run(f"tmux capture-pane -t {task_id} -p -S -10")

        return {
            "status": "ok",
            "task_id": task_id,
            "mode": "container" if use_container else "local",
            "recent_output": final_output[-500:] if final_output else "",
            "auto_answered_prompts": readiness.get("auto_answered", []),
        }

    result = await loop.run_in_executor(None, _do_spawn)

    # 7. 注册任务超时监控
    if result.get("status") == "ok" and _task_manager:
        await _task_manager.register_async(
            task_id, timeout_minutes,
            description=description or prompt[:100],
            instance_id=instance_id,
            mode="container" if use_container else "local",
            prompt=prompt,
        )
        result["timeout_registered"] = True

    return result


@mcp.tool()
async def jarvis_check_output(task_id: str, lines: int = 100) -> dict:
    """查看 tmux 子进程的最近输出，用于监控任务进度。

    Args:
        task_id: tmux session 名 / 任务 ID
        lines: 捕获最近多少行输出，默认 100
    """
    loop = asyncio.get_running_loop()

    def _do():
        # 检查 session 是否存在
        check = subprocess.run(
            ["tmux", "has-session", "-t", task_id], capture_output=True
        )
        if check.returncode != 0:
            return {"status": "error", "message": f"tmux session '{task_id}' not found"}

        output = _run(f"tmux capture-pane -t {task_id} -p -S -{lines}", timeout=5)
        return {
            "status": "ok",
            "task_id": task_id,
            "output": output,
        }

    return await loop.run_in_executor(None, _do)


@mcp.tool()
async def jarvis_send_input(task_id: str, text: str, extra_enters: int = 2) -> dict:
    """向 tmux 子进程发送输入（自动处理多次 Enter 确保送达）。

    Args:
        task_id: tmux session 名 / 任务 ID
        text: 要发送的文本内容
        extra_enters: 额外按 Enter 的次数，默认 2 次，确保消息送达
    """
    loop = asyncio.get_running_loop()

    def _do():
        check = subprocess.run(
            ["tmux", "has-session", "-t", task_id], capture_output=True
        )
        if check.returncode != 0:
            return {"status": "error", "message": f"tmux session '{task_id}' not found"}

        _tmux_send(task_id, text, extra_enters=extra_enters)
        time.sleep(2)
        output = _run(f"tmux capture-pane -t {task_id} -p -S -10", timeout=5)
        return {
            "status": "ok",
            "task_id": task_id,
            "recent_output": output,
        }

    return await loop.run_in_executor(None, _do)


@mcp.tool()
async def jarvis_kill_task(task_id: str) -> dict:
    """终止 tmux 子进程并清理任务注册。

    Args:
        task_id: tmux session 名 / 任务 ID
    """
    loop = asyncio.get_running_loop()

    def _do():
        result = subprocess.run(
            ["tmux", "kill-session", "-t", task_id], capture_output=True
        )
        killed = result.returncode == 0
        return killed

    killed = await loop.run_in_executor(None, _do)

    # 清理任务注册
    if _task_manager:
        await _task_manager.remove_async(task_id)

    return {
        "status": "ok",
        "task_id": task_id,
        "session_killed": killed,
        "task_removed": True,
    }


@mcp.tool()
async def jarvis_list_tasks() -> dict:
    """列出所有活跃的 tmux 子任务，包括 tmux session 状态和服务器注册的任务信息。"""
    loop = asyncio.get_running_loop()

    def _get_tmux_sessions():
        try:
            output = _run("tmux list-sessions -F '#{session_name}:#{session_created}'", timeout=5)
            if not output:
                return []
            sessions = []
            for line in output.strip().split("\n"):
                if ":" in line:
                    name, created = line.rsplit(":", 1)
                    sessions.append({"session": name, "created_at": created})
                else:
                    sessions.append({"session": line})
            return sessions
        except Exception:
            return []

    tmux_sessions = await loop.run_in_executor(None, _get_tmux_sessions)
    registered_tasks = _task_manager.get_all_tasks() if _task_manager else []

    return {
        "tmux_sessions": tmux_sessions,
        "registered_tasks": registered_tasks,
    }


# ============== 任务完成 ==============

@mcp.tool()
async def jarvis_complete_task(task_id: str, kill_tmux: bool = True) -> dict:
    """结束任务生命周期：归档任务并终止子进程。

    确保当前子进程任务完全完成，多轮开发应确认子进程完成最后一轮开发。
    调用后会清理任务，并 kill 子进程。注意，这会导致子进程上下文完全丢失，
    请确认开发已经完全完成后，再调用此工具。

    Args:
        task_id: 任务 ID
        kill_tmux: 是否终止 tmux session，默认 True
    """
    if not _task_manager:
        return {"status": "error", "message": "TaskManager not available"}

    task_info = await _task_manager.complete_async(task_id)
    if not task_info:
        return {"status": "error", "message": f"Task '{task_id}' not found in active tasks"}

    tmux_killed = False
    if kill_tmux:
        loop = asyncio.get_running_loop()
        def _kill():
            result = subprocess.run(
                ["tmux", "kill-session", "-t", task_id], capture_output=True
            )
            return result.returncode == 0
        tmux_killed = await loop.run_in_executor(None, _kill)

    return {
        "status": "ok",
        "task_id": task_id,
        "task_completed": True,
        "tmux_killed": tmux_killed,
    }


@mcp.tool()
async def jarvis_renew_task(task_id: str, extra_minutes: int = 20) -> dict:
    """延长子进程的工作时间。

    当子进程超时但仍在正常工作时使用。调用前建议先通过 jarvis_check_output
    确认子进程仍在活跃工作。

    Args:
        task_id: 任务 ID
        extra_minutes: 延长的分钟数
    """
    if not _task_manager:
        return {"status": "error", "message": "TaskManager not available"}
    task_info = await _task_manager.renew_async(task_id, extra_minutes)
    if not task_info:
        return {"status": "error", "message": f"Task '{task_id}' not found"}
    return {"status": "ok", "task_id": task_id, "extra_minutes": extra_minutes, "new_expires_at": task_info.get("expires_at")}


# ============== 定时任务 ==============

@mcp.tool()
async def jarvis_schedule_task(
    schedule_id: str,
    expression: str,
    message: str,
    instance_id: str = None,
) -> dict:
    """注册定时/周期/延迟任务。

    支持三种表达式格式:
    - Cron: "0 9 * * *" (每天 9 点)
    - Interval: "every 5 minutes" / "every 1 hour"
    - One-shot: "after 30 minutes" / "after 2 hours"

    Args:
        schedule_id: 任务唯一标识
        expression: 调度表达式
        message: 触发时发送给目标实例的消息内容
        instance_id: 目标实例 ID，不传则默认 ws-default
    """
    if not _scheduler:
        return {"status": "error", "message": "Scheduler not available"}
    try:
        task = _scheduler.register(schedule_id, expression, message, instance_id)
        return {"status": "ok", "task": task}
    except ValueError as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
async def jarvis_list_scheduled_tasks() -> dict:
    """列出所有定时任务及其状态。"""
    if not _scheduler:
        return {"status": "error", "message": "Scheduler not available"}
    return {"status": "ok", "tasks": _scheduler.list_all()}


@mcp.tool()
async def jarvis_cancel_scheduled_task(schedule_id: str) -> dict:
    """取消指定的定时任务。

    Args:
        schedule_id: 要取消的任务 ID
    """
    if not _scheduler:
        return {"status": "error", "message": "Scheduler not available"}
    task = _scheduler.cancel(schedule_id)
    if not task:
        return {"status": "error", "message": f"Scheduled task '{schedule_id}' not found"}
    return {"status": "ok", "cancelled": task}


# ============== 浏览器自动化 ==============

@mcp.tool()
async def browser_navigate(url: str, session: str = "default") -> dict:
    """导航到指定 URL。首次调用会自动启动 headless Chromium。

    Args:
        url: 目标 URL
        session: 浏览器 session 名称，默认 "default"，不同 session 有独立 cookies
    """
    s = await _browser_manager.get_session(session)
    resp = await s.page.goto(url, wait_until="domcontentloaded", timeout=30000)
    title = await s.page.title()
    return {
        "status": "ok",
        "url": s.page.url,
        "title": title,
        "http_status": resp.status if resp else None,
    }


@mcp.tool()
async def browser_snapshot(session: str = "default", interactive_only: bool = False) -> str:
    """获取当前页面的 accessibility tree 结构。
    可交互元素会标注 [ref=eN]，后续可用 ref 进行 click/fill 操作。
    导航到新页面后 ref 失效，需重新调用 snapshot。

    Args:
        session: 浏览器 session 名称
        interactive_only: 仅返回可交互元素
    """
    return await _browser_manager.snapshot(session, interactive_only)


@mcp.tool()
async def browser_screenshot(session: str = "default", full_page: bool = False) -> dict:
    """截取当前页面的屏幕截图，返回 base64 编码的 PNG。

    Args:
        session: 浏览器 session 名称
        full_page: True 截取整个页面（含滚动），False 只截可视区域
    """
    s = await _browser_manager.get_session(session)
    data = await s.page.screenshot(full_page=full_page, type="png")
    return {
        "status": "ok",
        "url": s.page.url,
        "image_base64": base64.b64encode(data).decode(),
        "format": "png",
    }


@mcp.tool()
async def browser_click(ref: str, session: str = "default") -> dict:
    """点击页面上由 ref 标识的元素。ref 来自 browser_snapshot 的 [ref=eN] 标注。

    Args:
        ref: 元素引用，如 "e1"、"e5"
        session: 浏览器 session 名称
    """
    s = await _browser_manager.get_session(session)
    locator = s.ref_map.get(ref)
    if not locator:
        return {"status": "error", "message": f"ref '{ref}' not found. Call browser_snapshot first."}
    await locator.click(timeout=5000)
    await s.page.wait_for_load_state("domcontentloaded", timeout=10000)
    title = await s.page.title()
    return {
        "status": "ok",
        "url": s.page.url,
        "title": title,
        "note": "Refs are now stale. Call browser_snapshot to get updated refs.",
    }


@mcp.tool()
async def browser_fill(ref: str, text: str, submit: bool = False, session: str = "default") -> dict:
    """在输入框中填入文本。可选提交（按 Enter）。

    Args:
        ref: 元素引用，如 "e3"
        text: 要输入的文本
        submit: 填入后是否按 Enter 提交
        session: 浏览器 session 名称
    """
    s = await _browser_manager.get_session(session)
    locator = s.ref_map.get(ref)
    if not locator:
        return {"status": "error", "message": f"ref '{ref}' not found. Call browser_snapshot first."}
    await locator.fill(text, timeout=5000)
    if submit:
        await locator.press("Enter")
        await s.page.wait_for_load_state("domcontentloaded", timeout=10000)
    title = await s.page.title()
    return {
        "status": "ok",
        "url": s.page.url,
        "title": title,
        "note": "Refs may be stale after input. Call browser_snapshot to refresh." if submit else "",
    }


@mcp.tool()
async def browser_select(ref: str, value: str, session: str = "default") -> dict:
    """在下拉选择框中选择选项。

    Args:
        ref: 元素引用
        value: 要选择的值（option value 或 label）
        session: 浏览器 session 名称
    """
    s = await _browser_manager.get_session(session)
    locator = s.ref_map.get(ref)
    if not locator:
        return {"status": "error", "message": f"ref '{ref}' not found."}
    await locator.select_option(value, timeout=5000)
    return {"status": "ok", "selected": value}


@mcp.tool()
async def browser_evaluate(code: str, session: str = "default") -> dict:
    """在页面上下文中执行 JavaScript 代码并返回结果。

    Args:
        code: 要执行的 JavaScript 代码
        session: 浏览器 session 名称
    """
    s = await _browser_manager.get_session(session)
    result = await s.page.evaluate(code)
    return {"status": "ok", "result": result}


@mcp.tool()
async def browser_wait(condition: str, value: str = "", timeout: int = 10000, session: str = "default") -> dict:
    """等待页面满足指定条件。

    Args:
        condition: 等待条件，可选 "selector"（CSS 选择器出现）、"url"（URL 包含指定字符串）、"load"（页面加载完成）
        value: 条件参数（selector 的 CSS 选择器，或 url 的子串）
        timeout: 超时毫秒数，默认 10000
        session: 浏览器 session 名称
    """
    s = await _browser_manager.get_session(session)
    if condition == "selector":
        await s.page.wait_for_selector(value, timeout=timeout)
    elif condition == "url":
        await s.page.wait_for_url(f"**{value}**", timeout=timeout)
    elif condition == "load":
        await s.page.wait_for_load_state("networkidle", timeout=timeout)
    else:
        return {"status": "error", "message": f"Unknown condition: {condition}. Use 'selector', 'url', or 'load'."}
    return {"status": "ok", "url": s.page.url}


@mcp.tool()
async def browser_get_content(session: str = "default", selector: str = "body") -> dict:
    """提取页面或指定元素的文本内容。

    Args:
        session: 浏览器 session 名称
        selector: CSS 选择器，默认 "body" 提取整个页面文本
    """
    s = await _browser_manager.get_session(session)
    text = await s.page.locator(selector).inner_text(timeout=5000)
    # 截断过长内容
    if len(text) > 50000:
        text = text[:50000] + "\n... [truncated]"
    return {"status": "ok", "url": s.page.url, "text": text}


@mcp.tool()
async def browser_close(session: str = "") -> dict:
    """关闭浏览器 session。不传 session 则关闭所有 session 和浏览器。

    Args:
        session: 要关闭的 session 名称，留空关闭所有
    """
    if session:
        await _browser_manager.close_session(session)
        return {"status": "ok", "closed": session}
    else:
        await _browser_manager.close_all()
        return {"status": "ok", "closed": "all"}
