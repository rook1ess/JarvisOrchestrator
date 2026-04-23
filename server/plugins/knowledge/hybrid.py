"""混合排序 — 0.7 vec + 0.3 bm25，参考 OpenClaw hybrid.ts

BM25 归一化：score = 1 / (1 + rank)，rank 是 FTS5 bm25() 返回值（低=好）
向量归一化：sqlite-vec 的 vec_distance_cosine 返回 [0, 2]，转 similarity = 1 - distance/2
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class HybridResult:
    id: str
    source: str
    path: str
    text: str
    start_line: int
    end_line: int
    updated_at: int
    vec_score: float = 0.0
    bm25_score: float = 0.0
    hybrid_score: float = 0.0
    metadata: dict[str, Any] = None


def cosine_distance_to_similarity(distance: float) -> float:
    """sqlite-vec vec_distance_cosine ∈ [0, 2] → similarity ∈ [0, 1]"""
    return max(0.0, 1.0 - distance / 2.0)


def bm25_rank_to_score(rank_value: float) -> float:
    """FTS5 bm25() 是"越低越好"的分数。实验上用 1/(1+|rank|) 归一化较平滑"""
    return 1.0 / (1.0 + abs(rank_value))


def merge_hybrid_results(
    vec_candidates: list[HybridResult],
    bm25_candidates: list[HybridResult],
    vec_weight: float = 0.7,
    bm25_weight: float = 0.3,
) -> list[HybridResult]:
    """合并两路候选：相同 id 合并分数，缺失一边当 0"""
    by_id: dict[str, HybridResult] = {}

    for r in vec_candidates:
        by_id[r.id] = r

    for r in bm25_candidates:
        if r.id in by_id:
            existing = by_id[r.id]
            existing.bm25_score = r.bm25_score
        else:
            by_id[r.id] = r

    merged = []
    for r in by_id.values():
        r.hybrid_score = vec_weight * r.vec_score + bm25_weight * r.bm25_score
        merged.append(r)

    merged.sort(key=lambda x: x.hybrid_score, reverse=True)
    return merged
