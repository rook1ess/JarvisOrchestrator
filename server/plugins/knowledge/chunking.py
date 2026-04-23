"""Markdown 按行边界切分 —— 直译 OpenClaw memory-host-sdk/internal.ts:356-459

关键原则：
- 按行边界切（LLM 无关）
- Token 估算：Latin ~char/4，CJK ~char/1
- Surrogate pair 保护（避免切开 emoji / CJK-Ext-B）
- Overlap 用行级 carry，不是字符级
"""

import hashlib
import re
from dataclasses import dataclass


CHARS_PER_TOKEN_LATIN = 4.0
CHARS_PER_TOKEN_CJK = 1.0


@dataclass
class Chunk:
    text: str
    start_line: int
    end_line: int
    text_hash: str


def _is_cjk(ch: str) -> bool:
    """粗略判断 CJK 字符（中日韩 Unified Ideographs + 平假名 / 片假名 / 常用 Extensions）"""
    code = ord(ch)
    return (
        0x3040 <= code <= 0x30FF      # 平假名 / 片假名
        or 0x3400 <= code <= 0x4DBF   # CJK Ext-A
        or 0x4E00 <= code <= 0x9FFF   # CJK Unified
        or 0xF900 <= code <= 0xFAFF   # CJK 兼容
        or 0x20000 <= code <= 0x2A6DF # CJK Ext-B
    )


def estimate_tokens(text: str) -> int:
    """启发式 token 估算 — CJK/Latin 分别计数"""
    if not text:
        return 0
    cjk = sum(1 for c in text if _is_cjk(c))
    latin = len(text) - cjk
    return int(cjk / CHARS_PER_TOKEN_CJK + latin / CHARS_PER_TOKEN_LATIN)


def _char_limit_for(text_sample: str, token_limit: int) -> int:
    """根据样本 CJK 比例估算 char 上限"""
    if not text_sample:
        return token_limit * int(CHARS_PER_TOKEN_LATIN)
    cjk_ratio = sum(1 for c in text_sample if _is_cjk(c)) / max(1, len(text_sample))
    # 加权平均 char/token
    chars_per_token = cjk_ratio * CHARS_PER_TOKEN_CJK + (1 - cjk_ratio) * CHARS_PER_TOKEN_LATIN
    return int(token_limit * chars_per_token)


def _safe_end(text: str, end: int) -> int:
    """surrogate pair 保护：避免切开高代理"""
    if end <= 0 or end >= len(text):
        return min(end, len(text))
    code = ord(text[end - 1])
    if 0xD800 <= code <= 0xDBFF:
        return min(end + 1, len(text))
    return end


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def chunk_markdown(text: str, target_tokens: int = 1024, overlap_tokens: int = 160) -> list[Chunk]:
    """按行切分 + 超阈值 flush + overlap carry"""
    if not text or not text.strip():
        return []

    lines = text.split("\n")
    chunks: list[Chunk] = []

    buf_lines: list[tuple[int, str]] = []  # (lineNo starting at 1, content)
    buf_chars = 0

    def flush(final: bool = False):
        nonlocal buf_lines, buf_chars
        if not buf_lines:
            return
        start_line = buf_lines[0][0]
        end_line = buf_lines[-1][0]
        chunk_text = "\n".join(line for _, line in buf_lines).strip()
        if chunk_text:
            chunks.append(Chunk(
                text=chunk_text,
                start_line=start_line,
                end_line=end_line,
                text_hash=_hash_text(chunk_text),
            ))
        if final:
            buf_lines = []
            buf_chars = 0
            return

        # overlap carry：保留末尾 overlap_tokens 对应的行
        overlap_limit = _char_limit_for(chunk_text[-500:] if chunk_text else "", overlap_tokens)
        carry: list[tuple[int, str]] = []
        carry_chars = 0
        for lineNo, line in reversed(buf_lines):
            carry_chars += len(line) + 1
            carry.insert(0, (lineNo, line))
            if carry_chars >= overlap_limit:
                break
        buf_lines = carry
        buf_chars = sum(len(l) + 1 for _, l in buf_lines)

    max_chars = _char_limit_for(text[:2000], target_tokens)

    for idx, line in enumerate(lines, start=1):
        line_chars = len(line) + 1

        # 单行过长：细切
        if line_chars > max_chars:
            if buf_lines:
                flush()
            pos = 0
            fine = max_chars
            while pos < len(line):
                end = _safe_end(line, pos + fine)
                sub = line[pos:end]
                chunks.append(Chunk(
                    text=sub,
                    start_line=idx,
                    end_line=idx,
                    text_hash=_hash_text(sub),
                ))
                pos = end
            continue

        if buf_chars + line_chars > max_chars and buf_lines:
            flush()

        buf_lines.append((idx, line))
        buf_chars += line_chars

    flush(final=True)
    return chunks


def chunk_id(source: str, path: str, chunk: Chunk) -> str:
    """确定性 chunk ID（幂等 upsert）"""
    key = f"{source}::{path}::{chunk.start_line}::{chunk.end_line}::{chunk.text_hash}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


# ============== 字符级上限（防 embedding API 超限）==============

EMBEDDING_CHAR_LIMIT = 32000  # 约 8K tokens


def split_by_byte_limit(text: str, max_chars: int = EMBEDDING_CHAR_LIMIT) -> list[str]:
    """embedding 前的兜底切分 —— 单个 chunk 还是超限时继续拆分"""
    if len(text) <= max_chars:
        return [text]
    parts = []
    pos = 0
    while pos < len(text):
        end = _safe_end(text, pos + max_chars)
        parts.append(text[pos:end])
        pos = end
    return parts
