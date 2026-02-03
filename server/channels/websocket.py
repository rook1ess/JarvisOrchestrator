"""WebSocket 渠道"""

from typing import Set, Dict
from fastapi import WebSocket
from server.channels.base import Channel


class WebSocketChannel(Channel):
    """管理 WebSocket 订阅者，按 instance_id 分组"""

    channel_type = "websocket"

    def __init__(self):
        # instance_id -> set of WebSocket connections
        self._subscribers: Dict[str, Set[WebSocket]] = {}

    def subscribe(self, instance_id: str, ws: WebSocket):
        if instance_id not in self._subscribers:
            self._subscribers[instance_id] = set()
        self._subscribers[instance_id].add(ws)
        total = sum(len(s) for s in self._subscribers.values())
        print(f"[WS] 浏览器连接 instance={instance_id} (总计 {total} 个)")

    def unsubscribe(self, instance_id: str, ws: WebSocket):
        if instance_id in self._subscribers:
            self._subscribers[instance_id].discard(ws)
            if not self._subscribers[instance_id]:
                del self._subscribers[instance_id]
        total = sum(len(s) for s in self._subscribers.values())
        print(f"[WS] 浏览器断开 instance={instance_id} (总计 {total} 个)")

    def get_subscriber_count(self, instance_id: str) -> int:
        return len(self._subscribers.get(instance_id, set()))

    def get_total_subscribers(self) -> int:
        return sum(len(s) for s in self._subscribers.values())

    async def send_response(self, data: dict, context: dict):
        """发送响应给指定 instance 的所有 WS 连接"""
        instance_id = context.get("instance_id", "")
        subscribers = self._subscribers.get(instance_id, set())
        dead = set()
        for ws in subscribers:
            try:
                await ws.send_json(data)
            except Exception:
                dead.add(ws)
        if dead:
            subscribers -= dead

    async def broadcast_all(self, data: dict):
        """广播给所有 instance 的所有连接"""
        dead_pairs = []
        for instance_id, subscribers in self._subscribers.items():
            for ws in subscribers:
                try:
                    await ws.send_json(data)
                except Exception:
                    dead_pairs.append((instance_id, ws))
        for instance_id, ws in dead_pairs:
            if instance_id in self._subscribers:
                self._subscribers[instance_id].discard(ws)
