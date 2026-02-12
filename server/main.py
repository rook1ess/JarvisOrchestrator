"""FastAPI app + lifespan + 挂载路由"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from server.config import WEB_DIR, SERVER_SESSION_ID
from server.tasks.manager import TaskManager
from server.agents.manager import AgentManager
from server.channels.websocket import WebSocketChannel
from server.channels.qq import QQChannel
from server.router import MessageRouter

from server.api import pages, sessions, tasks, status, instances
from server.mcp_server import mcp as mcp_server, init as mcp_init, _browser_manager

# 预先创建 MCP streamable HTTP app（触发 session_manager 的 lazy init）
_mcp_app = mcp_server.streamable_http_app()

# ============== 全局组件 ==============
task_manager = TaskManager()
agent_manager = AgentManager()
ws_channel = WebSocketChannel()
qq_channel = QQChannel()
message_router = MessageRouter(agent_manager)


async def _handle_timeout(task_id: str, description: str, instance_id: str = None):
    """处理任务超时，通知发起任务的实例或所有活跃实例"""
    message = f"[系统通知] 任务 {task_id} ({description}) 到达超时时间，请确认任务是否在正常进行。若原因是子进程没有正确发送回调，请手动注册/延长任务时间，每隔 15 分钟监督进度，并下发下一步任务，直到达到目标步骤。"

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动
    agent_manager.set_task_manager(task_manager)
    message_router.load_config()
    # 不预创建实例，首条消息到达时按需创建

    task_manager.set_broadcast_callback(_broadcast_for_tasks)
    await task_manager.start_checker(_handle_timeout)
    await agent_manager.start_health_checker(interval=30, idle_timeout_minutes=message_router.idle_timeout_minutes)

    # 启动 MCP Server 的 session manager（StreamableHTTP 需要 task group 初始化）
    async with mcp_server.session_manager.run():
        yield

    # 关闭
    await _browser_manager.close_all()
    await agent_manager.stop_health_checker()
    await task_manager.stop_checker()
    await agent_manager.stop_all()


app = FastAPI(title="JARVIS Server v2", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

# ============== 注入依赖并挂载路由 ==============
sessions.init(agent_manager, ws_channel)
tasks.init(task_manager)
status.init(agent_manager, task_manager, ws_channel, qq_channel, message_router)
instances.init(agent_manager, ws_channel, qq_channel=qq_channel, message_router=message_router)
mcp_init(agent_manager, ws_channel, task_manager, qq_channel=qq_channel, message_router=message_router)

app.include_router(pages.router)
app.include_router(sessions.router)
app.include_router(tasks.router)
app.include_router(status.router)
app.include_router(instances.router)

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
                if message or attachments:
                    # 第一条消息时按需创建实例（route_message 内部 _ensure_instance）
                    await message_router.route_message(
                        channel=ws_channel,
                        channel_type="websocket",
                        message=message,
                        context={"instance_id": instance_id, "source": "browser"},
                        attachments=attachments if attachments else None,
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
        # 所有浏览器断开时中断处理
        if ws_channel.get_subscriber_count(instance_id) == 0:
            inst = agent_manager.get_instance(instance_id)
            if inst and inst.is_processing:
                print("[WS] 所有浏览器断开，中断当前消息处理")
                await inst.interrupt()
