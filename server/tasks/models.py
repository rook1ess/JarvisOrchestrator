"""Pydantic 数据模型"""

from typing import Optional, List
from pydantic import BaseModel


class TaskRegisterData(BaseModel):
    task_id: str
    timeout_minutes: int = 20
    description: str = ""
    total_steps: int = 0
    instance_id: Optional[str] = None  # 发起任务的实例，用于超时通知路由


class TaskProgressData(BaseModel):
    progress: Optional[int] = None
    current_step: str = ""
    status: Optional[str] = None


class TaskRenewData(BaseModel):
    extra_minutes: Optional[int] = None


class CallbackData(BaseModel):
    task_id: str
    status: str  # done, blocked, progress, running
    reason: Optional[str] = ""
    progress: Optional[int] = None
    current_step: Optional[str] = ""
    instance_id: Optional[str] = None  # 指定通知哪个实例，不传则通知所有活跃实例
