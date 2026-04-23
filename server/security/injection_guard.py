"""Prompt Injection 威胁扫描 — 记忆 / 知识库写入前调用。

参考 Hermes tools/memory_tool.py 的 _MEMORY_THREAT_PATTERNS 设计。
两层对外接口：
- scan_for_threats(text, strict=True) → (ok, reasons)：命中任一规则则 ok=False
- strip_invisible_unicode(text) → str：轻度清洗（用户手写入口）
"""

import re


_THREAT_PATTERNS = [
    # ── 指令劫持 ─────────────────────────
    (r"ignore\s+(?:previous|above|all|prior)\s+(?:instructions?|rules?|prompts?|directives?)",
     "instruction override"),
    (r"disregard\s+(?:previous|above|all|prior)\s+(?:instructions?|rules?|prompts?)",
     "instruction override"),
    (r"forget\s+(?:everything|all|previous|above|prior)",
     "instruction override"),
    (r"(?:new|updated?)\s+(?:instruction|rule|directive|system\s+prompt)s?\s*[:：]",
     "instruction injection"),

    # ── 角色冒充 ─────────────────────────
    (r"(?:^|\n)\s*(?:system|assistant)\s*[:：]",
     "role impersonation"),
    (r"</?\s*(?:system|assistant|user)\s*>",
     "role tag injection"),

    # ── 标签逃逸（闭合我们自己包裹的 XML） ──
    (r"</?\s*(?:persistent_memory|soul|jarvis|preferences|credentials"
     r"|memory|projects|memory_detail|projects_detail"
     r"|relevant-memories|external-knowledge|knowledge)\s*>",
     "wrapper tag injection"),

    # ── 凭据窃取 ─────────────────────────
    (r"(?:cat|curl|wget|scp|rsync|tar|zip)\s+[^\n]*\.ssh",
     "ssh artifact access"),
    (r"\bauthorized_keys\b",
     "authorized_keys reference"),
    (r"\.ssh/(?:id_rsa|id_ed25519|id_ecdsa|id_dsa|known_hosts)",
     "private key reference"),
    (r"\$\{?(?:TOKEN|OAUTH|API_KEY|CLAUDE_CODE_OAUTH_TOKEN|"
     r"ANTHROPIC_API_KEY|OPENAI_API_KEY|GITHUB_TOKEN)\}?",
     "env var exfiltration"),

    # ── 执行/回传 ────────────────────────
    (r"curl\s+[^\n]*-X\s+POST[^\n]*\$",
     "command exfiltration"),
    (r"\beval\s*\(",
     "eval injection"),
    (r"\bexec\s*\(",
     "exec injection"),
    (r"\bsubprocess\.\w+\s*\(",
     "subprocess invocation"),
    (r"\bos\.system\s*\(",
     "os.system invocation"),
    (r"__import__\s*\(",
     "dynamic import injection"),

    # ── 凭据落盘 ─────────────────────────
    (r">>\s*~/\.(?:ssh|aws|config)/",
     "credential write"),
]


# 不可见 / 双向 / BOM 字符
_INVISIBLE_UNICODE = {
    "\u200b", "\u200c", "\u200d", "\u200e", "\u200f",   # zero-width / bidi marks
    "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",   # bidi override
    "\u2066", "\u2067", "\u2068", "\u2069",             # directional isolates
    "\ufeff",                                            # BOM
}


_COMPILED = [
    (re.compile(p, re.IGNORECASE | re.MULTILINE), reason)
    for p, reason in _THREAT_PATTERNS
]


def scan_for_threats(text: str, strict: bool = True) -> tuple[bool, list[str]]:
    """扫描文本威胁。

    Args:
        text: 待扫描文本
        strict: True=命中任一规则即 reject；False=只返回 reasons，ok 恒 True

    Returns:
        (ok, reasons)
    """
    if not text:
        return True, []

    reasons: list[str] = []

    # 不可见 unicode
    for ch in text:
        if ch in _INVISIBLE_UNICODE:
            reasons.append(f"invisible unicode detected (U+{ord(ch):04X})")
            break

    # 威胁 pattern
    for pattern, reason in _COMPILED:
        m = pattern.search(text)
        if m:
            snippet = m.group(0)[:60]
            reasons.append(f"{reason}: {snippet!r}")

    if strict and reasons:
        return False, reasons
    return True, reasons


def strip_invisible_unicode(text: str) -> str:
    """剥离不可见 unicode（用户手动写入时的轻度清洗）"""
    if not text:
        return text
    return "".join(ch for ch in text if ch not in _INVISIBLE_UNICODE)
