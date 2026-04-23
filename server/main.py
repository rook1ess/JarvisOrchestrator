"""FastAPI app + lifespan + 挂载路由"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from server.config import WEB_DIR, SERVER_SESSION_ID
from server.tasks.manager import TaskManager
from server.tasks.scheduler import ScheduledTaskManager
from server.tasks import daily_digest
from server.agents.manager import AgentManager
from server.channels.websocket import WebSocketChannel
from server.channels.qq import QQChannel
from server.router import MessageRouter

from server.api import pages, sessions, tasks, status, instances, config as config_api, subprocess_info
from server.mcp_server import mcp as mcp_server, init as mcp_init, shutdown as mcp_shutdown
from server.plugins import load_plugins, shutdown_plugins
from server.config_store import get_config

# 预先创建 MCP streamable HTTP app（触发 session_manager 的 lazy init）
_mcp_app = mcp_server.streamable_http_app()

# ============== 全局组件 ==============
task_manager = TaskManager()
scheduler = ScheduledTaskManager()
agent_manager = AgentManager()
ws_channel = WebSocketChannel()
qq_channel = QQChannel()
message_router = MessageRouter(agent_manager)


async def _handle_timeout(task_id: str, description: str, instance_id: str = None):
    """处理任务超时，通知发起任务的实例或所有活跃实例"""
    message = f"[任务超时] 任务 {task_id}（{description}）已到达超时时间。请 jarvis_check_output 检查子进程状态，如果仍在正常运行，jarvis_renew_task 续期即可。"

    if instance_id:
        targets = [agent_manager.get_instance(instance_id)]
        targets = [t for t in targets if t is not None]
    else:
        targets = list(agent_manager.get_all_instances().values())

    for inst in targets:
        channel_type = message_router.get_channel_type_for_instance(inst.instance_id)
        if channel_type == "qq" and qq_channel:
            callback = qq_channel.send_response
        else:
            callback = ws_channel.send_response
        await inst.enqueue(message, source="timeout", response_callback=callback)


async def _broadcast_for_tasks(data: dict):
    """任务状态变化广播给所有 WS 连接"""
    await ws_channel.broadcast_all(data)


async def _fire_scheduled(message: str, instance_id: str = None):
    """定时任务触发回调：向目标实例发送消息"""
    target_id = instance_id or "ws-default"
    inst = agent_manager.get_instance(target_id)
    if not inst:
        # 按需创建实例（_ensure_instance 需要 route dict）
        channel_type = message_router.get_channel_type_for_instance(target_id)
        route = message_router.resolve(channel_type) or {"instance_id": target_id, "channel": channel_type}
        inst = await message_router._ensure_instance(route)
    if not inst:
        print(f"[Scheduler] 无法获取实例 {target_id}，跳过")
        return

    channel_type = message_router.get_channel_type_for_instance(target_id)
    if channel_type == "qq" and qq_channel:
        callback = qq_channel.send_response
    else:
        callback = ws_channel.send_response
    await inst.enqueue(message, source="scheduler", response_callback=callback)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动
    agent_manager.set_task_manager(task_manager)
    message_router.load_config()
    # 不预创建实例，首条消息到达时按需创建

    task_manager.set_broadcast_callback(_broadcast_for_tasks)
    await task_manager.start_checker(_handle_timeout)
    await scheduler.start(_fire_scheduled)
    await agent_manager.start_health_checker(interval=30, idle_timeout_minutes=message_router.idle_timeout_minutes)
    await daily_digest.start()

    # 加载启用的 plugin（根据 data/config.json 的 plugins.* 开关）
    config = get_config()
    plugin_context = {
        "agent_manager": agent_manager,
        "task_manager": task_manager,
        "scheduler": scheduler,
    }
    loaded_plugins = load_plugins(mcp_server, config, plugin_context)
    app.state.loaded_plugins = loaded_plugins

    # 启动 MCP Server 的 session manager（StreamableHTTP 需要 task group 初始化）
    async with mcp_server.session_manager.run():
        yield

    # 关闭
    await shutdown_plugins(app.state.loaded_plugins)
    await mcp_shutdown()
    await daily_digest.stop()
    await scheduler.stop()
    await agent_manager.stop_health_checker()
    await task_manager.stop_checker()
    await agent_manager.stop_all()


app = FastAPI(title="JARVIS Server v2", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

# ============== 注入依赖并挂载路由 ==============
sessions.init(agent_manager, ws_channel)
tasks.init(task_manager, scheduler=scheduler)
status.init(agent_manager, task_manager, ws_channel, qq_channel, message_router)
instances.init(agent_manager, ws_channel, qq_channel=qq_channel, message_router=message_router)
mcp_init(agent_manager, ws_channel, task_manager, scheduler=scheduler, qq_channel=qq_channel, message_router=message_router)

app.include_router(pages.router)
app.include_router(sessions.router)
app.include_router(tasks.router)
app.include_router(status.router)
app.include_router(instances.router)
app.include_router(config_api.router)
app.include_router(subprocess_info.router)

# 挂载 MCP Server 到 /mcp
# MCP Server 挂载（FastMCP 内部路由是 /mcp，mount 后完整路径 /mcp/mcp）
# 使用预创建的 _mcp_app（session_manager 已在 lifespan 中管理）
app.mount("/mcp", _mcp_app)


# ============== WebSocket ==============

@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket, instance: str = "ws-default"):
    """WebSocket 聊天 - 连接到指定实例（默认 ws-default）"""
    await websocket.accept()
    instance_id = instance
    ws_channel.subscribe(instance_id, websocket)

    # 先立即发 connected（不等实例创建），让前端知道 WS 已通
    await websocket.send_json({
        "type": "connected",
        "message": "已连接到小克",
        "instance_id": instance_id,
        "server_session_id": SERVER_SESSION_ID
    })

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "message")

            if msg_type == "message":
                message = data.get("message", "").strip()
                attachments = data.get("attachments", [])
                message_id = data.get("message_id")
                if message or attachments:
                    # 第一条消息时按需创建实例（route_message 内部 _ensure_instance）
                    await message_router.route_message(
                        channel=ws_channel,
                        channel_type="websocket",
                        message=message,
                        context={"instance_id": instance_id, "source": "browser"},
                        attachments=attachments if attachments else None,
                        message_id=message_id,
                    )

            elif msg_type == "cancel":
                inst = agent_manager.get_instance(instance_id)
                if inst:
                    await inst.interrupt()

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WS] 错误: {e}")
    finally:
        ws_channel.unsubscribe(instance_id, websocket)
        # 所有浏览器断开时：不再自动中断，因为非浏览器来源的消息（scheduler/callback）不应被中断
        # 如果需要中断，用户可以在重连后手动取消
