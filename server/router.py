"""消息路由：channel → agent instance（按需创建）"""

import json
from pathlib import Path
from typing import Optional
from server.agents.manager import AgentManager
from server.channels.base import Channel
from server.config import PROJECT_ROOT


class MessageRouter:
    """根据 routing.json 配置将消息路由到正确的 AgentInstance，按需创建"""

    def __init__(self, agent_manager: AgentManager):
        self.agent_manager = agent_manager
        self.routes: list = []
        self.idle_timeout_minutes: int = 60

    def load_config(self, config_path: Path = None):
        if config_path is None:
            config_path = PROJECT_ROOT / "routing.json"
        if not config_path.exists():
            print("[Router] routing.json 不存在，使用默认配置")
            self.routes = [{"channel": "websocket", "instance_id": "ws-default"}]
            return
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            self.routes = config.get("routes", [])
            self.idle_timeout_minutes = config.get("idle_timeout_minutes", 60)
            print(f"[Router] 加载 {len(self.routes)} 条路由规则 (空闲超时: {self.idle_timeout_minutes}min)")
        except Exception as e:
            print(f"[Router] 加载路由配置失败: {e}")
            self.routes = [{"channel": "websocket", "instance_id": "ws-default"}]

    def resolve(self, channel_type: str, context: dict = None) -> Optional[dict]:
        """根据 channel + context 匹配路由，返回完整路由条目（含 instance_id）

        匹配逻辑：
        1. 先精确匹配有 match 条件的路由
        2. 无 match 条件的路由作为该 channel 的 fallback
        """
        context = context or {}
        fallback = None
        for route in self.routes:
            if route.get("channel") != channel_type:
                continue
            match = route.get("match")
            if match:
                if all(context.get(k) == v for k, v in match.items()):
                    return route
            elif fallback is None:
                fallback = route
        return fallback

    async def _ensure_instance(self, route: dict):
        """确保实例存在，不存在则按需创建（有历史 session 则 resume，失败则新建）"""
        instance_id = route.get("instance_id")
        instance = self.agent_manager.get_instance(instance_id)
        if instance is not None:
            return instance

        # 检查是否有上次回收时保存的 session_id
        saved_config = self.agent_manager.get_instance_config(instance_id)
        last_session_id = saved_config.get("last_session_id")

        if last_session_id:
            print(f"[Router] 按需恢复实例: {instance_id} (resume: {last_session_id[:8]}...)")
            try:
                return await self.agent_manager.create_instance(instance_id, resume_session=last_session_id)
            except Exception as e:
                print(f"[Router] resume 失败: {instance_id}: {e}")
                print(f"[Router] 回退到新 session: {instance_id}")
                self.agent_manager.clear_instance_config_key(instance_id, "last_session_id")
                return await self.agent_manager.create_instance(instance_id, resume_session=None)
        else:
            print(f"[Router] 按需创建实例: {instance_id} (新 session)")
            return await self.agent_manager.create_instance(instance_id, resume_session=None)

    def get_channel_type_for_instance(self, instance_id: str) -> str:
        """根据 routing.json 确定实例对应的 channel 类型"""
        for route in self.routes:
            if route.get("instance_id") == instance_id:
                return route.get("channel", "websocket")
        return "websocket"  # 默认 websocket

    async def route_message(self, channel: Channel, channel_type: str,
                             message: str, context: dict = None,
                             attachments: list = None,
                             message_id: str = None):
        """路由消息到正确的 AgentInstance（不存在则自动创建）"""
        route = self.resolve(channel_type, context)
        if not route:
            print(f"[Router] 无法路由: channel={channel_type}, context={context}")
            return

        instance = await self._ensure_instance(route)
        if not instance:
            print(f"[Router] 创建实例失败: {route.get('instance_id')}")
            return

        source = context.get("source", "user") if context else "user"
        await instance.enqueue(
            message=message,
            source=source,
            attachments=attachments,
            response_callback=channel.send_response,
            message_id=message_id,
        )
