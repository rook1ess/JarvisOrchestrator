"""状态/回调/重启/QQ webhook API"""

import os
import sys
import subprocess
from fastapi import APIRouter, HTTPException, Query, Request
from server.tasks.models import CallbackData
from server.config import (
    QQ_ALLOWED_USERS, QQ_ALLOWED_GROUPS, QQ_GROUP_AT_ONLY,
)
from server.channels.qq import parse_qq_message, qq_message_has_at_bot

router = APIRouter()

_agent_manager = None
_task_manager = None
_ws_channel = None
_qq_channel = None
_message_router = None


def init(agent_manager, task_manager, ws_channel, qq_channel, message_router):
    global _agent_manager, _task_manager, _ws_channel, _qq_channel, _message_router
    _agent_manager = agent_manager
    _task_manager = task_manager
    _ws_channel = ws_channel
    _qq_channel = qq_channel
    _message_router = message_router


@router.get("/health")
async def health_check():
    """健康检查端点 - 供外部监控 (如 Docker HEALTHCHECK, uptime robot 等)"""
    report = _agent_manager.check_all_health() if _agent_manager else {"status": "starting", "instances": []}
    status_code = 200 if report["status"] == "healthy" else 503
    from fastapi.responses import JSONResponse
    return JSONResponse(content=report, status_code=status_code)


@router.get("/api/status")
async def get_status():
    default_instance = _agent_manager.get_instance("ws-default") if _agent_manager else None
    return {
        "running": default_instance is not None and default_instance.client is not None,
        "subscribers": _ws_channel.get_total_subscribers() if _ws_channel else 0,
        "processing": default_instance.is_processing if default_instance else False,
        "instances": _agent_manager.list_instances() if _agent_manager else [],
    }


@router.post("/api/restart")
async def restart_jarvis(instance_id: str = Query(default=None)):
    """重启指定实例，重新加载配置。保留对话历史。"""
    target_id = instance_id or "ws-default"
    instance = _agent_manager.get_instance(target_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    await instance.restart()
    return {"status": "ok", "instance_id": target_id}


@router.post("/api/restart-server")
async def restart_server():
    def do_restart():
        import time as _time
        _time.sleep(1)
        python = sys.executable
        if sys.platform == "win32":
            subprocess.Popen([python] + sys.argv, creationflags=subprocess.CREATE_NEW_CONSOLE)
            os._exit(0)
        else:
            os.execv(python, [python] + sys.argv)

    import threading
    t = threading.Thread(target=do_restart)
    t.daemon = True
    t.start()
    return {"status": "ok", "message": "Server restarting..."}


@router.post("/callback")
async def task_callback(data: CallbackData):
    """接收子进程回调，通知指定实例或所有活跃实例"""
    print(f"[Callback] 收到子进程汇报: task={data.task_id}, status={data.status}, instance={data.instance_id or 'all'}")

    if data.status == "progress":
        progress_info = f"progress={data.progress}" if data.progress else ""
        step_info = f"step={data.current_step}" if data.current_step else ""
        print(f"[Callback] 任务 {data.task_id} 进度汇报: {progress_info} {step_info}")
        return {"status": "ok", "message": f"Progress noted for task {data.task_id}"}

    # 构建通知消息
    if data.status == "done":
        message = f"[子进程汇报] 任务 {data.task_id} 报告已完成当前阶段任务。请确认当前所处步骤/剩余步骤，并下发下一阶段任务。若已经完成所有步骤，将当前任务标记为 done。"
    elif data.status == "blocked":
        message = f"[子进程汇报] 任务 {data.task_id} 报告遇到阻塞: {data.reason}。请核实并决定下一步。"
    else:
        return {"status": "ok", "message": f"Callback received for task {data.task_id}"}

    # 确定通知哪些实例
    if data.instance_id:
        targets = [_agent_manager.get_instance(data.instance_id)] if _agent_manager else []
        targets = [t for t in targets if t is not None]
    else:
        # 通知所有活跃实例
        targets = list(_agent_manager.get_all_instances().values()) if _agent_manager else []

    if not targets:
        print(f"[Callback] 无活跃实例可接收回调")
        return {"status": "ok", "message": "No active instance to notify"}

    for inst in targets:
        # 根据实例类型选择回调渠道
        callback = _ws_channel.send_response if _ws_channel else None
        await inst.enqueue(message, source="callback", response_callback=callback)

    return {"status": "ok", "message": f"Callback delivered to {len(targets)} instance(s)"}


@router.post("/qq/webhook")
async def qq_webhook(request: Request):
    """接收 NapCat 推送的 QQ 消息"""
    data = await request.json()
    post_type = data.get("post_type")
    if post_type != "message":
        return {"status": "ignored"}

    user_id = data.get("user_id")
    group_id = data.get("group_id")
    message_type = data.get("message_type")
    raw_message = data.get("message", "")
    self_id = data.get("self_id")

    if QQ_ALLOWED_USERS and user_id not in QQ_ALLOWED_USERS:
        return {"status": "denied", "reason": "user not in allowlist"}
    if group_id and QQ_ALLOWED_GROUPS and group_id not in QQ_ALLOWED_GROUPS:
        return {"status": "denied", "reason": "group not in allowlist"}

    if message_type == "group" and QQ_GROUP_AT_ONLY:
        if not qq_message_has_at_bot(raw_message, self_id):
            return {"status": "ignored", "reason": "not mentioned"}

    text = parse_qq_message(raw_message)
    if not text:
        return {"status": "ignored", "reason": "empty message"}

    if message_type == "group":
        source = f"qq:group:{group_id}"
    else:
        source = f"qq:private:{user_id}"

    # 设置 QQ channel 上下文
    _qq_channel.set_context(
        source,
        user_id=user_id,
        group_id=group_id if message_type == "group" else None
    )

    sender = data.get("sender", {})
    nickname = sender.get("card") or sender.get("nickname") or str(user_id)
    print(f"[QQ] 收到消息: [{message_type}] {nickname}: {text[:50]}")

    # 通过路由发送消息
    await _message_router.route_message(
        channel=_qq_channel,
        channel_type="qq",
        message=text,
        context={"message_type": message_type, "source": source},
    )
    return {"status": "ok"}
