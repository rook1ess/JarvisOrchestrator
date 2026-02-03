"""任务管理 API"""

from fastapi import APIRouter, HTTPException
from server.tasks.models import TaskRegisterData, TaskProgressData, TaskRenewData

router = APIRouter()

_task_manager = None


def init(task_manager):
    global _task_manager
    _task_manager = task_manager


@router.post("/task/register")
async def register_task(data: TaskRegisterData):
    task_info = await _task_manager.register_async(
        data.task_id, data.timeout_minutes, data.description, data.total_steps,
        instance_id=data.instance_id,
    )
    return {
        "status": "ok",
        "task_id": data.task_id,
        "expires_in_minutes": data.timeout_minutes,
        "task": task_info
    }


@router.get("/task/list")
async def list_tasks():
    return {"tasks": _task_manager.get_all_tasks()}


@router.put("/task/{task_id}/progress")
async def update_task_progress(task_id: str, data: TaskProgressData):
    task_info = await _task_manager.update_progress_async(
        task_id, data.progress, data.current_step, data.status
    )
    if not task_info:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "ok", "task": task_info}


@router.delete("/task/{task_id}")
async def remove_task(task_id: str):
    await _task_manager.remove_async(task_id)
    return {"status": "ok"}


@router.put("/task/{task_id}/renew")
async def renew_task(task_id: str, data: TaskRenewData = None):
    extra_minutes = data.extra_minutes if data else None
    task_info = await _task_manager.renew_async(task_id, extra_minutes)
    if not task_info:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "ok", "task": task_info}
