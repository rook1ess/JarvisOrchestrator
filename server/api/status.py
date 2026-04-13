"""状态/回调/重启/QQ webhook API"""

import os
import sys
import subprocess
from fastapi import APIRouter, HTTPException, Query, Request
from server.tasks.models import CallbackData
from server.config import (
    QQ_ALLOWED_USERS, QQ_ALLOWED_GROUPS, QQ_GROUP_AT_ONLY,
)
from server.channels.qq import parse_qq_message, qq_message_has_at_bot, download_image_as_base64, download_file_as_attachment

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


async def _notify_instance(instance_id: str, message: str, source: str = "callback") -> int:
    """查找目标实例并投递消息，返回通知的实例数"""
    if instance_id:
        targets = [_agent_manager.get_instance(instance_id)] if _agent_manager else []
        targets = [t for t in targets if t is not None]
    else:
        targets = list(_agent_manager.get_all_instances().values()) if _agent_manager else []

    if not targets:
        print(f"[{source}] 无活跃实例可接收回调")
        return 0

    for inst in targets:
        channel_type = _message_router.get_channel_type_for_instance(inst.instance_id) if _message_router else "websocket"
        if channel_type == "qq" and _qq_channel:
            callback = _qq_channel.send_response
        else:
            callback = _ws_channel.send_response if _ws_channel else None
        await inst.enqueue(message, source=source, response_callback=callback)

    return len(targets)


@router.post("/callback")
async def task_callback(data: CallbackData):
    """接收子进程回调（旧版 curl 方式，保留兼容）"""
    print(f"[Callback] 收到子进程汇报: task={data.task_id}, status={data.status}, instance={data.instance_id or 'all'}")

    if data.status == "progress":
        if _task_manager:
            await _task_manager.update_progress_async(data.task_id, data.progress, data.current_step)
        return {"status": "ok", "message": f"Progress updated for task {data.task_id}"}

    if data.status == "done":
        if _task_manager:
            await _task_manager.renew_async(data.task_id)
        message = f"[子进程汇报] 任务 {data.task_id} 报告已完成当前阶段任务。请确认当前所处步骤/剩余步骤，并下发下一阶段任务。若已经完成所有步骤，使用 jarvis_complete_task 将任务标记为完成。"
    elif data.status == "blocked":
        if _task_manager:
            await _task_manager.block_async(data.task_id, data.reason or "")
        message = f"[子进程汇报] 任务 {data.task_id} 报告遇到阻塞: {data.reason}。请核实并决定下一步。"
    else:
        return {"status": "ok", "message": f"Callback received for task {data.task_id}"}

    count = await _notify_instance(data.instance_id, message)
    return {"status": "ok", "message": f"Callback delivered to {count} instance(s)"}


@router.post("/hook/stop")
async def hook_stop(request: Request, task_id: str = Query(...), instance_id: str = Query("")):
    """接收 Claude Code Stop hook 回调 — 子进程每轮完成时自动触发"""
    body = await request.json()
    stop_reason = body.get("stop_reason", "unknown")
    last_message = body.get("last_assistant_message", "")

    print(f"[Hook/Stop] task={task_id}, reason={stop_reason}, msg_len={len(last_message)}")

    # 保活 5 分钟缓冲，等待中控决策
    if _task_manager:
        await _task_manager.renew_async(task_id, extra_minutes=5)

    # 截取最后 1000 字符
    truncated = last_message[-1000:] if len(last_message) > 1000 else last_message

    message = (
        f"[子进程回调] 任务 {task_id} 完成了一轮工作（{stop_reason}，已自动保活 5 分钟）。\n\n"
        f"<subprocess_response>\n{truncated}\n</subprocess_response>\n\n"
        f"请根据回复内容决定下一步：\n"
        f"- 继续派发：jarvis_send_input + jarvis_renew_task\n"
        f"- 全部完成：jarvis_complete_task\n"
        f"- 需要详情：jarvis_check_output"
    )

    count = await _notify_instance(instance_id, message, source="hook/stop")
    return {"status": "ok", "message": f"Stop hook delivered to {count} instance(s)"}


@router.post("/hook/stop-failure")
async def hook_stop_failure(request: Request, task_id: str = Query(...), instance_id: str = Query("")):
    """接收 Claude Code StopFailure hook 回调 — 子进程遇到 API 错误时触发"""
    body = await request.json()
    error_type = body.get("error_type", "unknown")
    error_message = body.get("error_message", "")

    print(f"[Hook/StopFailure] task={task_id}, type={error_type}, msg={error_message[:200]}")

    message = (
        f"[子进程异常] 任务 {task_id} 发生错误：{error_type} - {error_message}\n\n"
        f"请 jarvis_check_output 查看子进程状态，尝试为子进程提供帮助。"
        f"如果遇到认证等无法解决的问题，jarvis_kill_task 终止子进程并通知用户。"
    )

    count = await _notify_instance(instance_id, message, source="hook/stop-failure")
    return {"status": "ok", "message": f"StopFailure hook delivered to {count} instance(s)"}


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

    text, image_urls, files = parse_qq_message(raw_message)
    if not text and not image_urls and not files:
        return {"status": "ignored", "reason": "empty message"}

    if message_type == "group":
        source = f"qq:group:{group_id}"
    else:
        source = f"qq:private:{user_id}"

    # 解析路由以获取 instance_id
    route = _message_router.resolve("qq", {"message_type": message_type, "source": source})
    qq_instance_id = route.get("instance_id", "qq-default") if route else "qq-default"

    # 设置 QQ channel 上下文（传入 instance_id 用于 last_active 记录）
    _qq_channel.set_context(
        source,
        user_id=user_id,
        group_id=group_id if message_type == "group" else None,
        instance_id=qq_instance_id,
    )

    sender = data.get("sender", {})
    nickname = sender.get("card") or sender.get("nickname") or str(user_id)
    img_hint = f" +{len(image_urls)}图" if image_urls else ""
    file_hint = f" +{len(files)}文件" if files else ""
    print(f"[QQ] 收到消息: [{message_type}] {nickname}: {text[:50]}{img_hint}{file_hint}")

    # 下载图片和文件转 attachments
    import asyncio
    attachments = []

    if image_urls:
        img_results = await asyncio.gather(*[download_image_as_base64(url) for url in image_urls])
        attachments.extend(r for r in img_results if r is not None)

    if files:
        file_results = await asyncio.gather(*[download_file_as_attachment(f["url"], f["name"]) for f in files])
        attachments.extend(r for r in file_results if r is not None)
        # 对于没有成功下载的文件，在文本中保留提示
        for f, result in zip(files, file_results):
            if result is None:
                text = f'{text}\n[文件: {f["name"]}（不支持的格式或下载失败）]' if text else f'[文件: {f["name"]}（不支持的格式或下载失败）]'

    if not attachments:
        attachments = None

    # 通过路由发送消息
    await _message_router.route_message(
        channel=_qq_channel,
        channel_type="qq",
        message=text or "(发送了图片/文件)",
        context={"message_type": message_type, "source": source},
        attachments=attachments,
    )
    return {"status": "ok"}
