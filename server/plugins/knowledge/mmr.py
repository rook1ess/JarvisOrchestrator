"""Maximal Marginal Relevance 重排 — 降低结果冗余
参考 OpenClaw memory-core/mmr.ts + Carbonell & Goldstein 1998

λ × relevance - (1-λ) × max_similarity(已选)
similarity 用 Jaccard(CJK bigram + Latin word)。
"""

import re


def _cjk_bigrams(text: str) -> set[str]:
    """把 CJK 段落切成 bigram"""
    out = set()
    cjk_run = []
    for ch in text:
        code = ord(ch)
        is_cjk = (
            0x3400 <= code <= 0x4DBF
            or 0x4E00 <= code <= 0x9FFF
            or 0x3040 <= code <= 0x30FF
        )
        if is_cjk:
            cjk_run.append(ch)
        else:
            if len(cjk_run) >= 2:
                for i in range(len(cjk_run) - 1):
                    out.add(cjk_run[i] + cjk_run[i + 1])
            cjk_run = []
    if len(cjk_run) >= 2:
        for i in range(len(cjk_run) - 1):
            out.add(cjk_run[i] + cjk_run[i + 1])
    return out


_WORD_RE = re.compile(r"[A-Za-z0-9_]{2,}")


def _latin_tokens(text: str) -> set[str]:
    return {m.group(0).lower() for m in _WORD_RE.finditer(text)}


def tokenize(text: str) -> set[str]:
    """CJK bigram + Latin word tokens"""
    return _cjk_bigrams(text) | _latin_tokens(text)


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def mmr_rerank(
    results: list,
    top_k: int,
    lambda_: float = 0.6,
    text_attr: str = "text",
    score_attr: str = "hybrid_score",
) -> list:
    """返回经过 MMR 重排的 top_k 结果"""
    if not results or top_k <= 0:
        return []
    if top_k >= len(results):
        return results

    tokens_cache = [tokenize(getattr(r, text_attr, "") or "") for r in results]
    selected_idx: list[int] = []
    remaining = list(range(len(results)))

    # 第一个选最高分的
    best = max(remaining, key=lambda i: getattr(results[i], score_attr, 0))
    selected_idx.append(best)
    remaining.remove(best)

    while len(selected_idx) < top_k and remaining:
        best_i = None
        best_score = float("-inf")
        for i in remaining:
            relevance = getattr(results[i], score_attr, 0)
            max_sim = max(
                (jaccard(tokens_cache[i], tokens_cache[s]) for s in selected_idx),
                default=0.0,
            )
            mmr = lambda_ * relevance - (1 - lambda_) * max_sim
            if mmr > best_score:
                best_score = mmr
                best_i = i
        if best_i is None:
            break
        selected_idx.append(best_i)
        remaining.remove(best_i)

    return [results[i] for i in selected_idx]
