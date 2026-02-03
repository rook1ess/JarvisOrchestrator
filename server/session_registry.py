"""Session 安全注册表 - 防止多实例写入同一 session 导致文件损坏"""

import asyncio
from typing import Optional


class SessionRegistry:
    """应用层 session 锁，防止两个 AgentInstance 同时 resume 同一个 session"""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._sessions: dict[str, str] = {}  # session_id -> instance_id

    async def acquire(self, session_id: Optional[str], instance_id: str) -> bool:
        """尝试占用 session。新 session (None) 总是允许。
        Returns True if acquired, False if already occupied by another instance.
        """
        if session_id is None:
            return True
        async with self._lock:
            holder = self._sessions.get(session_id)
            if holder is not None and holder != instance_id:
                print(f"[SessionRegistry] 拒绝: session {session_id[:8]}... 已被 {holder} 占用")
                return False
            self._sessions[session_id] = instance_id
            print(f"[SessionRegistry] 注册: {instance_id} -> session {session_id[:8]}...")
            return True

    async def release(self, session_id: Optional[str], instance_id: str):
        """释放 session 占用"""
        if session_id is None:
            return
        async with self._lock:
            if self._sessions.get(session_id) == instance_id:
                del self._sessions[session_id]
                print(f"[SessionRegistry] 释放: {instance_id} -> session {session_id[:8]}...")

    def get_holder(self, session_id: str) -> Optional[str]:
        return self._sessions.get(session_id)

    def get_all(self) -> dict[str, str]:
        return dict(self._sessions)


# 全局单例
session_registry = SessionRegistry()
