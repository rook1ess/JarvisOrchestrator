"""任务管理 API"""

import asyncio
import subprocess

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
    loop = asyncio.get_event_loop()
    tasks = await loop.run_in_executor(None, lambda: _task_manager.get_all_tasks(check_tmux=True))
    return {"tasks": tasks}


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


# ============== Spawn Tasks REST API ==============

@router.get("/api/instances/{instance_id}/spawn-tasks")
async def get_instance_spawn_tasks(instance_id: str):
    """获取指定实例的子进程任务列表"""
    tasks = _task_manager.get_tasks_by_instance(instance_id)
    return {"tasks": tasks}


@router.get("/api/spawn-tasks/{task_id}/output")
async def get_spawn_task_output(task_id: str, lines: int = 100):
    """获取子进程 tmux 最近输出"""
    loop = asyncio.get_event_loop()

    def _do():
        check = subprocess.run(
            ["tmux", "has-session", "-t", task_id], capture_output=True
        )
        if check.returncode != 0:
            return None
        result = subprocess.run(
            f"tmux capture-pane -t {task_id} -p -S -{lines}",
            shell=True, capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip()

    output = await loop.run_in_executor(None, _do)
    if output is None:
        raise HTTPException(status_code=404, detail=f"tmux session '{task_id}' not found")
    return {"task_id": task_id, "output": output}


@router.delete("/api/spawn-tasks/{task_id}")
async def kill_spawn_task(task_id: str):
    """终止子进程 tmux session 并清理任务注册"""
    loop = asyncio.get_event_loop()

    def _do():
        result = subprocess.run(
            ["tmux", "kill-session", "-t", task_id], capture_output=True
        )
        return result.returncode == 0

    killed = await loop.run_in_executor(None, _do)
    await _task_manager.remove_async(task_id)
    return {"status": "ok", "task_id": task_id, "session_killed": killed}
