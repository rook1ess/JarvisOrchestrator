"""AgentManager：管理多个 AgentInstance 生命周期 + 健康检查"""

import asyncio
import time
from typing import Optional, Dict
from server.agents.instance import AgentInstance


class AgentManager:
    def __init__(self):
        self._instances: Dict[str, AgentInstance] = {}
        self._lock = asyncio.Lock()
        self._task_manager = None
        self._health_task: Optional[asyncio.Task] = None
        # instance_id -> {"last_session_id": str} 记录运行时状态，用于自愈和空闲恢复
        self._instance_configs: Dict[str, dict] = {}

    def set_task_manager(self, tm):
        self._task_manager = tm

    async def create_instance(self, instance_id: str,
                               resume_session: str = None) -> AgentInstance:
        async with self._lock:
            if instance_id in self._instances:
                await self._instances[instance_id].stop()

            instance = AgentInstance(instance_id)
            if self._task_manager:
                instance.set_task_manager(self._task_manager)
            instance.set_agent_manager(self)
            await instance.start(resume_session)
            self._instances[instance_id] = instance
            self._instance_configs[instance_id] = {}
            return instance

    async def stop_instance(self, instance_id: str, forget: bool = False):
        """停止实例。forget=True 时清除配置（不可按需重建）"""
        async with self._lock:
            instance = self._instances.pop(instance_id, None)
            if forget:
                self._instance_configs.pop(instance_id, None)
            if instance:
                await instance.stop()

    async def stop_all(self):
        async with self._lock:
            for instance in self._instances.values():
                await instance.stop()
            self._instances.clear()
            self._instance_configs.clear()

    def get_instance(self, instance_id: str) -> Optional[AgentInstance]:
        return self._instances.get(instance_id)

    def get_all_instances(self) -> Dict[str, AgentInstance]:
        return dict(self._instances)

    # ---- 健康检查 ----

    def check_instance_health(self, instance_id: str) -> dict:
        """检查单个实例健康状态"""
        inst = self._instances.get(instance_id)
        if inst is None:
            return {"instance_id": instance_id, "status": "missing"}

        # client 为 None 说明子进程已死
        if inst.client is None:
            return {"instance_id": instance_id, "status": "dead", "reason": "client is None"}

        # queue worker 任务结束（非正常）
        if inst._queue_worker_task and inst._queue_worker_task.done():
            exc = inst._queue_worker_task.exception() if not inst._queue_worker_task.cancelled() else None
            return {
                "instance_id": instance_id,
                "status": "dead",
                "reason": f"queue_worker exited: {exc}" if exc else "queue_worker stopped",
            }

        return {
            "instance_id": instance_id,
            "status": "healthy",
            "is_processing": inst.is_processing,
            "queue_size": inst.message_queue.qsize(),
        }

    def check_all_health(self) -> dict:
        """检查所有实例健康状态"""
        results = []
        all_healthy = True
        for iid in self._instances:
            h = self.check_instance_health(iid)
            results.append(h)
            if h["status"] != "healthy":
                all_healthy = False
        return {
            "status": "healthy" if all_healthy else "degraded",
            "instances": results,
            "timestamp": time.time(),
        }

    async def _try_revive(self, instance_id: str):
        """尝试重启一个死掉的实例（优先 resume 上次 session）"""
        config = self._instance_configs.get(instance_id, {})

        old = self._instances.pop(instance_id, None)
        # 保存死掉实例的 session_id
        if old and old.current_session_id:
            config["last_session_id"] = old.current_session_id
            self._instance_configs[instance_id] = config

        if old:
            try:
                await old.stop()
            except Exception:
                pass

        last_session_id = config.get("last_session_id")
        label = f"resume: {last_session_id[:8]}..." if last_session_id else "新 session"
        print(f"[Health] 尝试自愈实例: {instance_id} ({label})")

        try:
            instance = AgentInstance(instance_id)
            if self._task_manager:
                instance.set_task_manager(self._task_manager)
            instance.set_agent_manager(self)
            await instance.start(resume_session=last_session_id)
            self._instances[instance_id] = instance
            print(f"[Health] 自愈成功: {instance_id}")
            return True
        except Exception as e:
            print(f"[Health] 自愈失败 {instance_id}: {e}")
            # resume 失败时尝试新 session
            if last_session_id:
                print(f"[Health] 回退到新 session: {instance_id}")
                try:
                    instance = AgentInstance(instance_id)
                    if self._task_manager:
                        instance.set_task_manager(self._task_manager)
                    instance.set_agent_manager(self)
                    await instance.start(resume_session=None)
                    self._instances[instance_id] = instance
                    config.pop("last_session_id", None)
                    print(f"[Health] 新 session 自愈成功: {instance_id}")
                    return True
                except Exception as e2:
                    print(f"[Health] 新 session 也失败: {instance_id}: {e2}")
            return False

    async def start_health_checker(self, interval: int = 30, idle_timeout_minutes: int = 60):
        """启动后台健康检查 + 空闲回收（每 interval 秒扫一次）"""
        self._idle_timeout = idle_timeout_minutes * 60

        async def loop():
            while True:
                await asyncio.sleep(interval)
                now = time.time()
                for iid in list(self._instances.keys()):
                    h = self.check_instance_health(iid)
                    if h["status"] == "dead":
                        print(f"[Health] 检测到实例异常: {iid} - {h.get('reason')}")
                        async with self._lock:
                            await self._try_revive(iid)
                        continue

                    # 空闲回收（不回收正在处理消息的实例）
                    inst = self._instances.get(iid)
                    if inst and not inst.is_processing and inst.message_queue.qsize() == 0:
                        idle_seconds = now - inst.last_active_at
                        if idle_seconds > self._idle_timeout:
                            print(f"[Health] 实例空闲超时 ({int(idle_seconds)}s): {iid}，回收释放资源")
                            async with self._lock:
                                removed = self._instances.pop(iid, None)
                                if removed:
                                    # 保存 session_id 以便下次按需恢复
                                    if removed.current_session_id:
                                        self._instance_configs.setdefault(iid, {})
                                        self._instance_configs[iid]["last_session_id"] = removed.current_session_id
                                        print(f"[Health] 保存 session: {iid} -> {removed.current_session_id[:8]}...")
                                    await removed.stop()

        self._health_task = asyncio.create_task(loop())
        print(f"[Health] 健康检查已启动 (间隔 {interval}s, 空闲超时 {idle_timeout_minutes}min)")

    async def stop_health_checker(self):
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
            self._health_task = None
            print("[Health] 健康检查已停止")

    def list_instances(self) -> list:
        result = []
        for iid, inst in self._instances.items():
            h = self.check_instance_health(iid)
            result.append({
                "instance_id": iid,
                "session_id": inst.current_session_id,
                "is_processing": inst.is_processing,
                "queue_size": inst.message_queue.qsize(),
                "health": h["status"],
            })
        return result
