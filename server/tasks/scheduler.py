"""ScheduledTaskManager - 定时/周期/延迟任务调度器"""

import asyncio
import json
import re
import time
import uuid
from pathlib import Path
from typing import Optional, Callable, Awaitable

from server.config import DATA_DIR


class ScheduledTaskManager:
    """管理定时任务的注册、持久化与触发"""

    def __init__(self):
        self._tasks: dict[str, dict] = {}
        self._storage_path = DATA_DIR / "scheduled_tasks.json"
        self._running = False
        self._poll_task: Optional[asyncio.Task] = None
        self._fire_callback: Optional[Callable[[str, str], Awaitable]] = None

    # ---- 持久化 ----

    def _save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump(self._tasks, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Scheduler] 持久化失败: {e}")

    def _load(self):
        if self._storage_path.exists():
            try:
                with open(self._storage_path, "r", encoding="utf-8") as f:
                    self._tasks = json.load(f)
                print(f"[Scheduler] 加载 {len(self._tasks)} 个定时任务")
            except Exception as e:
                print(f"[Scheduler] 加载失败: {e}")

    # ---- 表达式解析 ----

    @staticmethod
    def _parse_expression(expression: str) -> dict:
        """解析调度表达式，返回 {type, ...} 元数据

        支持三种格式:
        - Cron: "0 9 * * *"  (5 字段 cron)
        - Interval: "every 5 minutes" / "every 1 hour"
        - One-shot: "after 30 minutes" / "after 2 hours"
        """
        expr = expression.strip().lower()

        # Interval: "every N minutes/hours"
        m = re.match(r"every\s+(\d+)\s+(minute|minutes|hour|hours|second|seconds)", expr)
        if m:
            value = int(m.group(1))
            unit = m.group(2)
            if "hour" in unit:
                interval_sec = value * 3600
            elif "second" in unit:
                interval_sec = value
            else:
                interval_sec = value * 60
            return {"type": "interval", "interval_seconds": interval_sec}

        # One-shot: "after N minutes/hours"
        m = re.match(r"after\s+(\d+)\s+(minute|minutes|hour|hours|second|seconds)", expr)
        if m:
            value = int(m.group(1))
            unit = m.group(2)
            if "hour" in unit:
                delay_sec = value * 3600
            elif "second" in unit:
                delay_sec = value
            else:
                delay_sec = value * 60
            return {"type": "oneshot", "delay_seconds": delay_sec}

        # Cron expression (5 fields)
        parts = expression.strip().split()
        if len(parts) == 5:
            return {"type": "cron", "cron_expression": expression.strip()}

        raise ValueError(f"Unsupported schedule expression: {expression}")

    @staticmethod
    def _compute_next_run(task: dict) -> float | None:
        """计算下次执行时间 (epoch timestamp)"""
        now = time.time()
        stype = task.get("schedule_type")

        if stype == "interval":
            base = task.get("last_run") or task.get("created_at", now)
            return base + task["interval_seconds"]

        elif stype == "oneshot":
            if task.get("last_run"):
                return None  # Already fired
            return task.get("created_at", now) + task["delay_seconds"]

        elif stype == "cron":
            try:
                from croniter import croniter
                base_time = task.get("last_run") or now
                cron = croniter(task["cron_expression"], base_time)
                return cron.get_next(float)
            except ImportError:
                print("[Scheduler] croniter not installed, cron expressions unavailable")
                return None
            except Exception as e:
                print(f"[Scheduler] cron 解析错误: {e}")
                return None

        return None

    # ---- CRUD ----

    def register(self, schedule_id: str, expression: str, message: str,
                 instance_id: str = None) -> dict:
        """注册定时任务"""
        parsed = self._parse_expression(expression)

        task = {
            "id": schedule_id,
            "expression": expression,
            "schedule_type": parsed["type"],
            "message": message,
            "instance_id": instance_id,
            "enabled": True,
            "created_at": time.time(),
            "last_run": None,
            "next_run": None,
        }

        # Copy parsed fields
        if parsed["type"] == "interval":
            task["interval_seconds"] = parsed["interval_seconds"]
        elif parsed["type"] == "oneshot":
            task["delay_seconds"] = parsed["delay_seconds"]
        elif parsed["type"] == "cron":
            task["cron_expression"] = parsed["cron_expression"]

        task["next_run"] = self._compute_next_run(task)
        self._tasks[schedule_id] = task
        self._save()
        print(f"[Scheduler] 注册任务: {schedule_id} ({expression}) → instance:{instance_id or 'auto'}")
        return task

    def cancel(self, schedule_id: str) -> dict | None:
        """取消定时任务"""
        task = self._tasks.pop(schedule_id, None)
        if task:
            self._save()
            print(f"[Scheduler] 取消任务: {schedule_id}")
        return task

    def list_all(self) -> list[dict]:
        """列出所有定时任务"""
        now = time.time()
        result = []
        for task in self._tasks.values():
            t = task.copy()
            if t.get("next_run") and t["enabled"]:
                t["seconds_until_next"] = max(0, int(t["next_run"] - now))
            result.append(t)
        return result

    # ---- 调度循环 ----

    async def start(self, fire_callback: Callable[[str, str], Awaitable]):
        """启动调度循环

        Args:
            fire_callback: async (message, instance_id) → 触发时调用
        """
        self._load()
        self._fire_callback = fire_callback
        self._running = True

        # Recompute next_run for all tasks after load
        for task in self._tasks.values():
            if task["enabled"] and task.get("next_run") is None:
                task["next_run"] = self._compute_next_run(task)

        async def poll_loop():
            while self._running:
                await asyncio.sleep(30)
                now = time.time()
                for task in list(self._tasks.values()):
                    if not task["enabled"]:
                        continue
                    next_run = task.get("next_run")
                    if next_run is None or now < next_run:
                        continue

                    # Fire!
                    print(f"[Scheduler] 触发任务: {task['id']} → {task['message'][:50]}")
                    try:
                        await self._fire_callback(task["message"], task.get("instance_id"))
                    except Exception as e:
                        print(f"[Scheduler] 触发失败: {task['id']} - {e}")

                    # Update state
                    task["last_run"] = now

                    if task["schedule_type"] == "oneshot":
                        task["enabled"] = False
                        task["next_run"] = None
                    else:
                        task["next_run"] = self._compute_next_run(task)

                    self._save()

        self._poll_task = asyncio.create_task(poll_loop())
        print(f"[Scheduler] 调度器已启动 ({len(self._tasks)} 个任务)")

    async def stop(self):
        """停止调度循环并清空所有定时任务（任务与会话上下文绑定，重启后无意义）"""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        count = len(self._tasks)
        self._tasks.clear()
        self._save()
        print(f"[Scheduler] 调度器已停止，已清空 {count} 个定时任务")
