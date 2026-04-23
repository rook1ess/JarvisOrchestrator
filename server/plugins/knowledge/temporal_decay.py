"""时间衰减 — exp(-ln(2)/halfLife * ageDays)
参考 OpenClaw memory-core/temporal-decay.ts
"""

import math
import time


def decay_factor(updated_at_epoch: int, half_life_days: int = 30) -> float:
    """返回 [0, 1] 的衰减系数"""
    if half_life_days <= 0:
        return 1.0
    age_days = max(0.0, (time.time() - updated_at_epoch) / 86400.0)
    return math.exp(-math.log(2.0) / half_life_days * age_days)


def apply_decay(results: list, half_life_days: int = 30, score_attr: str = "hybrid_score"):
    """原地修改每个 result 的 score，乘以衰减系数"""
    for r in results:
        ts = getattr(r, "updated_at", None)
        if ts is None:
            continue
        factor = decay_factor(ts, half_life_days)
        base = getattr(r, score_attr, 0)
        setattr(r, score_attr, base * factor)
