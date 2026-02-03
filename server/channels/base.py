"""Channel 抽象基类"""

from abc import ABC, abstractmethod


class Channel(ABC):
    """消息渠道抽象"""

    channel_type: str = ""

    @abstractmethod
    async def send_response(self, data: dict, context: dict):
        """将响应块发回消息来源

        Args:
            data: 响应数据 (type, content, etc.)
            context: 来源上下文 (instance_id, source, etc.)
        """
