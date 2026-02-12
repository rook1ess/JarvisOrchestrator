"""TaskManager + 文件持久化"""

import asyncio
import json
import time
from pathlib import Path
from typing import Optional, List, Dict, Callable, Awaitable

from server.config import DATA_DIR


class TaskManager:
    """管理已注册的任务、超时检查、文件持久化"""

    HISTORY_LIMIT = 200

    def __init__(self):
        self.tasks: Dict[str, dict] = {}
        self.history: List[dict] = []
        self._check_task: Optional[asyncio.Task] = None
        self._broadcast_callback: Optional[Callable] = None
        self._storage_path = DATA_DIR / "tasks.json"

    def set_broadcast_callback(self, callback):
        self._broadcast_callback = callback

    # ---- 持久化 ----

    def _save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        data = {"active": self.tasks, "history": self.history[-self.HISTORY_LIMIT:]}
        try:
            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[TaskManager] 持久化失败: {e}")

    def _load(self):
        if self._storage_path.exists():
            try:
                with open(self._storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.tasks = data.get("active", {})
                self.history = data.get("history", [])
                print(f"[TaskManager] 加载 {len(self.tasks)} 个活跃任务, {len(self.history)} 条历史")
            except Exception as e:
                print(f"[TaskManager] 加载失败: {e}")

    def _archive(self, task_info: dict):
        """将完成/超时的任务移入历史"""
        entry = task_info.copy()
        entry["archived_at"] = time.time()
        self.history.append(entry)
        if len(self.history) > self.HISTORY_LIMIT:
            self.history = self.history[-self.HISTORY_LIMIT:]

    # ---- 广播 ----

    async def _broadcast_task_update(self, task_info: dict, event_type: str):
        if self._broadcast_callback:
            await self._broadcast_callback({
                "type": "task_update",
                "event": event_type,
                "task": task_info,
                "all_tasks": self.get_all_tasks()
            })

    # ---- CRUD ----

    def register(self, task_id: str, timeout_minutes: int, description: str = "",
                 total_steps: int = 0, instance_id: str = None, mode: str = None):
        task_info = {
            "task_id": task_id,
            "description": description,
            "timeout_minutes": timeout_minutes,
            "registered_at": time.time(),
            "expires_at": time.time() + timeout_minutes * 60,
            "status": "running",
            "progress": 0,
            "total_steps": total_steps,
            "current_step": "",
            "instance_id": instance_id,  # 发起任务的实例
            "mode": mode,  # "container" | "local" | None
        }
        self.tasks[task_id] = task_info
        self._save()
        print(f"[TaskManager] 注册任务: {task_id} (超时: {timeout_minutes}分钟)")
        return task_info

    async def register_async(self, task_id: str, timeout_minutes: int, description: str = "",
                             total_steps: int = 0, instance_id: str = None, mode: str = None):
        task_info = self.register(task_id, timeout_minutes, description, total_steps, instance_id, mode)
        await self._broadcast_task_update(task_info, "registered")
        return task_info

    def complete(self, task_id: str):
        if task_id in self.tasks:
            task_info = self.tasks[task_id]
            task_info["status"] = "done"
            task_info["progress"] = task_info.get("total_steps", 1) or 1
            self._archive(task_info)
            del self.tasks[task_id]
            self._save()
            print(f"[TaskManager] 任务完成: {task_id}")
            return task_info
        return None

    async def complete_async(self, task_id: str):
        task_info = self.complete(task_id)
        if task_info:
            await self._broadcast_task_update(task_info, "completed")
        return task_info

    def update_progress(self, task_id: str, progress: int = None, current_step: str = "", status: str = None):
        if task_id in self.tasks:
            if progress is not None:
                self.tasks[task_id]["progress"] = progress
            if current_step:
                self.tasks[task_id]["current_step"] = current_step
            if status:
                self.tasks[task_id]["status"] = status
            self._save()
            return self.tasks[task_id]
        return None

    async def update_progress_async(self, task_id: str, progress: int = None, current_step: str = "", status: str = None):
        task_info = self.update_progress(task_id, progress, current_step, status)
        if task_info:
            await self._broadcast_task_update(task_info, "progress")
        return task_info

    def block(self, task_id: str, reason: str = ""):
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = "blocked"
            self.tasks[task_id]["block_reason"] = reason
            self._save()
            print(f"[TaskManager] 任务阻塞: {task_id} - {reason}")
            return self.tasks[task_id]
        return None

    async def block_async(self, task_id: str, reason: str = ""):
        task_info = self.block(task_id, reason)
        if task_info:
            await self._broadcast_task_update(task_info, "blocked")
        return task_info

    def renew(self, task_id: str, extra_minutes: int = None):
        if task_id in self.tasks:
            task = self.tasks[task_id]
            minutes = extra_minutes or task.get("timeout_minutes", 20)
            task["expires_at"] = time.time() + minutes * 60
            task["status"] = "running"
            self._save()
            print(f"[TaskManager] 任务续期: {task_id} (+{minutes}分钟)")
            return task
        return None

    async def renew_async(self, task_id: str, extra_minutes: int = None):
        task_info = self.renew(task_id, extra_minutes)
        if task_info:
            await self._broadcast_task_update(task_info, "renewed")
        return task_info

    def remove(self, task_id: str):
        if task_id in self.tasks:
            task_info = self.tasks.pop(task_id)
            self._archive(task_info)
            self._save()
            print(f"[TaskManager] 移除任务: {task_id}")
            return task_info
        return None

    async def remove_async(self, task_id: str):
        task_info = self.remove(task_id)
        if task_info:
            await self._broadcast_task_update(task_info, "removed")
        return task_info

    def get_expired_tasks(self) -> List[dict]:
        now = time.time()
        return [info for info in self.tasks.values()
                if info["status"] == "running" and now > info["expires_at"]]

    def get_all_tasks(self) -> List[dict]:
        now = time.time()
        tasks = []
        for task in self.tasks.values():
            task_copy = task.copy()
            if task_copy["status"] == "running":
                remaining = task_copy["expires_at"] - now
                task_copy["remaining_seconds"] = max(0, int(remaining))
            tasks.append(task_copy)
        return tasks

    def get_tasks_by_instance(self, instance_id: str) -> List[dict]:
        """返回指定实例的所有任务"""
        now = time.time()
        tasks = []
        for task in self.tasks.values():
            if task.get("instance_id") != instance_id:
                continue
            task_copy = task.copy()
            if task_copy["status"] == "running":
                remaining = task_copy["expires_at"] - now
                task_copy["remaining_seconds"] = max(0, int(remaining))
            tasks.append(task_copy)
        return tasks

    async def start_checker(self, on_timeout_callback):
        self._load()
        # 启动时清理已超时的僵尸任务（服务器重启后可能残留）
        self._cleanup_zombies()

        async def check_loop():
            while True:
                await asyncio.sleep(30)
                expired = self.get_expired_tasks()
                for task in expired:
                    task_id = task["task_id"]
                    task["status"] = "timeout"
                    self._archive(task)
                    del self.tasks[task_id]  # 从活跃列表移除
                    self._save()
                    print(f"[TaskManager] 任务超时并移除: {task_id}")
                    await self._broadcast_task_update(task, "timeout")
                    await on_timeout_callback(task_id, task["description"], task.get("instance_id"))

                # 定期清理 tmux 已死但任务仍在的孤儿
                self._cleanup_dead_tmux()

        self._check_task = asyncio.create_task(check_loop())
        print("[TaskManager] 超时检查器已启动")

    def _cleanup_zombies(self):
        """清理 status 不是 running/blocked 的僵尸任务（历史 bug 残留）"""
        zombies = [tid for tid, t in self.tasks.items() if t["status"] not in ("running", "blocked")]
        for tid in zombies:
            self._archive(self.tasks.pop(tid))
            print(f"[TaskManager] 清理僵尸任务: {tid}")
        if zombies:
            self._save()

    def _cleanup_dead_tmux(self):
        """清理 tmux session 已不存在的任务（子进程已结束但未回调）"""
        import subprocess
        dead = []
        for tid in list(self.tasks.keys()):
            result = subprocess.run(
                ["tmux", "has-session", "-t", tid],
                capture_output=True, timeout=5,
            )
            if result.returncode != 0:
                dead.append(tid)
        for tid in dead:
            task = self.tasks.pop(tid)
            task["status"] = "dead_session"
            self._archive(task)
            print(f"[TaskManager] tmux 已消失，清理任务: {tid}")
        if dead:
            self._save()

    async def stop_checker(self):
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
            print("[TaskManager] 超时检查器已停止")
