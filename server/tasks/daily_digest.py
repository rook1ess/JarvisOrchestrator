"""每日/每周对话摘要 —— 双份分级压缩

设计：每次 Sonnet 调用产出两份摘要：
- **SHORT** (~200 token)：日常注入 system_prompt 保持最小常驻记忆
- **DETAIL** (~2000 token)：供 jarvis_memory_search tool 按需检索

文件结构：
- data/memory/memory.md           → short 版，包含 <dd-YYYY-MM-DD> 和 <wk-...> 标签
- data/memory/memory_detail.md    → detail 版，同上标签结构但内容更详细

触发机制：
- 独立 asyncio loop，每 10 分钟检查一次
- 条件：本地时间 ≥02:00 且 "昨天" 在 short 版没有 dd 标签
- Mac 休眠错过：开机后首次 loop 检查立即补跑

累积机制：
- daily 攒到 7 个 dd → 立即折叠为一个 <wk-START-to-END>
- 两份（memory.md / memory_detail.md）同步 fold
- 严格 7 天滚动窗口；稳态为 N 个 wk + 0~7 个 dd
"""

import asyncio
import json
import os
import re
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from server.config import DATA_DIR, PROJECT_ROOT


MEMORY_DIR = DATA_DIR / "memory"
MEMORY_SHORT_FILE = MEMORY_DIR / "memory.md"
MEMORY_DETAIL_FILE = MEMORY_DIR / "memory_detail.md"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

_POLL_INTERVAL = 600
_TRIGGER_HOUR = 2


# ============== Prompt 模板（双摘要一次产出）==============

_DAILY_PROMPT_TEMPLATE = """\
请根据下面的用户与 agent 于 {date_str} 的对话流水，同时生成两份摘要。

## 输出格式（严格）

你必须输出恰好两个 XML 片段，分隔符是两个长度标签：

---SHORT---
<dd-{date_str}>
（简短摘要，严格控制在 100-300 字符，包含当天的核心事件。写入 memory.md 后会在每轮对话全量注入 system_prompt，必须极度精简。）
</dd-{date_str}>
---DETAIL---
<dd-{date_str}>
（细化摘要，300-1500 字符，记录当天的事件链、决策、技术点、结论。写入 memory_detail.md 供按需检索，可详细但不要啰嗦。）
</dd-{date_str}>

## 规则

- **中文输出**。规则可以是英文，但摘要正文必须简体中文。
- Never use conclusive phrases like "throughout the process...", "demonstrated...".
- 避免含糊表达。
- 确保任何读者不看原文就能理解发生了什么。
- 项目相关工作在 SHORT 版使用高层次描述（"实现了 X / 扩展 Y 能力"）；DETAIL 版可以提及具体模块、文件、决策依据。
- 两份摘要的标签必须完全相同：<dd-{date_str}>...</dd-{date_str}>。
- 除了 ---SHORT--- / ---DETAIL--- 分隔符和两个标签及其内容，不要输出任何其他文字。

---

历史上下文（用于延续性，可能为空）：

{history}

---

{date_str} 当日对话流水：

{flow}
"""


_WEEKLY_PROMPT_TEMPLATE = """\
请把下面这连续 7 天（{start} 到 {end}）的每日摘要（双份）折叠为周总结（双份）。

## 输出格式（严格）

---SHORT---
<wk-{start}-to-{end}>
（周总结简短版，300-600 字符，覆盖 7 天核心脉络。写入 memory.md，每轮注入 system_prompt。）
</wk-{start}-to-{end}>
---DETAIL---
<wk-{start}-to-{end}>
（周总结细化版，1500-4000 字符，覆盖 7 天的关键决策、项目进展、讨论链。写入 memory_detail.md 供检索。）
</wk-{start}-to-{end}>

## 规则

- **中文输出**。
- Never use conclusive phrases. 避免含糊表达。
- SHORT 版用高层次描述，DETAIL 版可展开技术决策。
- 两份标签完全一致：<wk-{start}-to-{end}>...</wk-{start}-to-{end}>
- 只输出分隔符和两个带标签的摘要，不要其他文字。

---

历史周总结（可能为空）：

{history}

---

即将折叠的 7 天每日摘要（SHORT + DETAIL 双份）：

{daily_chunk}
"""


# ============== JSONL 扫描 ==============

def _find_session_dirs() -> list[Path]:
    """扫所有相关 session 目录。历史遗留：两个 CWD 都扫（CLAUDE.md 有说明）"""
    from server.config import INSTANCES_DIR, load_instance_config

    cwds: set[str] = set()
    if INSTANCES_DIR.is_dir():
        for json_file in INSTANCES_DIR.glob("*.json"):
            if json_file.stem.startswith("_"):
                continue
            try:
                cfg = load_instance_config(json_file.stem)
                cwd = cfg.get("cwd")
                if cwd:
                    cwds.add(str(Path(cwd).resolve()))
            except Exception as e:
                print(f"[DailyDigest] 读 {json_file.name} 失败: {e}")
    cwds.add(str(PROJECT_ROOT.resolve()))

    dirs = []
    for cwd in sorted(cwds):
        enc = cwd.replace("/", "-")
        d = CLAUDE_PROJECTS_DIR / enc
        if d.is_dir():
            dirs.append(d)
    return dirs


def _parse_timestamp(ts: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _extract_day_messages(jsonl_path: Path, target_date: date) -> list[dict]:
    out = []
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = obj.get("timestamp")
                dt = _parse_timestamp(ts) if ts else None
                if dt and dt.astimezone().date() == target_date:
                    out.append(obj)
    except Exception as e:
        print(f"[DailyDigest] 读 {jsonl_path} 失败: {e}")
    return out


_CODE_BLOCK_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)

PER_MSG_THRESHOLD = 20000
PER_MSG_HEAD = 10000
PER_MSG_TAIL = 10000
TOTAL_LIMIT = 50000


def _strip_code_blocks(text: str) -> str:
    def repl(m):
        inner = m.group(1)
        return f"[代码块 {inner.count(chr(10)) + 1} 行]"
    return _CODE_BLOCK_RE.sub(repl, text)


def _truncate_long_message(text: str) -> str:
    if len(text) <= PER_MSG_THRESHOLD:
        return text
    omitted = len(text) - PER_MSG_HEAD - PER_MSG_TAIL
    return (
        text[:PER_MSG_HEAD]
        + f"\n\n[...中间省略 {omitted} 字符...]\n\n"
        + text[-PER_MSG_TAIL:]
    )


def _to_flow_text(msgs: list[dict]) -> str:
    lines = []
    for obj in msgs:
        t = obj.get("type")
        if t == "user":
            content = obj.get("message", {}).get("content", "")
            if isinstance(content, list):
                parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                content = "\n".join(p for p in parts if p)
            if isinstance(content, str) and content.strip():
                cleaned = _strip_code_blocks(content.strip())
                cleaned = _truncate_long_message(cleaned)
                lines.append(f"User: {cleaned}")
        elif t == "assistant":
            content = obj.get("message", {}).get("content", [])
            if isinstance(content, list):
                parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                text = "\n".join(p for p in parts if p).strip()
                if text:
                    cleaned = _strip_code_blocks(text)
                    cleaned = _truncate_long_message(cleaned)
                    lines.append(f"Assistant: {cleaned}")
    return "\n\n".join(lines)


def _gather_day_flow(target_date: date) -> str:
    chunks = []
    for d in _find_session_dirs():
        for jsonl in d.glob("*.jsonl"):
            msgs = _extract_day_messages(jsonl, target_date)
            if msgs:
                chunk = _to_flow_text(msgs)
                if chunk:
                    chunks.append(f"# Session: {jsonl.stem}\n\n{chunk}")
    combined = "\n\n---\n\n".join(chunks)
    if len(combined) > TOTAL_LIMIT:
        original_len = len(combined)
        combined = combined[:TOTAL_LIMIT] + f"\n\n[...硬截断于 {TOTAL_LIMIT} 字符；原长 {original_len}...]"
        print(f"[DailyDigest] 流水过长硬截断：{original_len} → {TOTAL_LIMIT}")
    return combined


# ============== 文件读写 ==============

def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _list_dd_dates(content: str) -> list[str]:
    return re.findall(r"<dd-(\d{4}-\d{2}-\d{2})>", content)


def _has_dd_for(target_date: date, content: Optional[str] = None) -> bool:
    if content is None:
        content = _read(MEMORY_SHORT_FILE)
    return f"<dd-{target_date.isoformat()}>" in content


def _append(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n" + text.strip() + "\n")


# ============== 双摘要解析 ==============

_SPLIT_PATTERN = re.compile(
    r"---SHORT---\s*(.*?)\s*---DETAIL---\s*(.*)",
    re.DOTALL,
)


def _parse_dual_output(text: str) -> tuple[str, str]:
    """从 Sonnet 输出中解析 SHORT/DETAIL 两段。失败时 short=full, detail 为空"""
    m = _SPLIT_PATTERN.search(text)
    if not m:
        print("[DailyDigest] 警告：Sonnet 输出未按 ---SHORT---/---DETAIL--- 格式，fallback")
        return text.strip(), ""
    return m.group(1).strip(), m.group(2).strip()


# ============== CLI 调用 ==============

def _call_claude_cli(prompt: str, timeout: int = 600, model: str = "claude-sonnet-4-6") -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("ANTHROPIC_")}
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", model,
             "--output-format", "json", "--dangerously-skip-permissions"],
            env=env, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"claude -p 超时 ({timeout}s)")

    if result.returncode != 0:
        raise RuntimeError(f"claude -p 退出码 {result.returncode}: {result.stderr[:500]}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"claude 输出非 JSON: {result.stdout[:500]}")

    text = data.get("result") or data.get("text") or ""
    if not text:
        raise RuntimeError(f"claude 返回空 text: {result.stdout[:500]}")
    return text


# ============== 主流程 ==============

async def run_daily_digest(target_date: date) -> bool:
    if _has_dd_for(target_date):
        print(f"[DailyDigest] {target_date} 已有摘要，跳过")
        return False

    flow = _gather_day_flow(target_date)
    if not flow.strip():
        print(f"[DailyDigest] {target_date} 无对话记录，跳过")
        return False

    # 历史：把 short + detail 都作为历史上下文（让 Sonnet 保持两份格式一致性）
    history_short = _read(MEMORY_SHORT_FILE) or "(无)"
    history_detail = _read(MEMORY_DETAIL_FILE) or "(无)"
    history = f"### memory.md (short)\n{history_short}\n\n### memory_detail.md (detail)\n{history_detail}"

    date_str = target_date.isoformat()
    prompt = _DAILY_PROMPT_TEMPLATE.format(date_str=date_str, flow=flow, history=history)

    print(f"[DailyDigest] 生成 {target_date} 双摘要...")
    loop = asyncio.get_running_loop()

    # 从 config_store 读模型（可选）
    try:
        from server.config_store import get_config
        model = get_config().get("daily_digest", "model", default="claude-sonnet-4-6")
    except Exception:
        model = "claude-sonnet-4-6"

    try:
        raw = await loop.run_in_executor(None, _call_claude_cli, prompt, 600, model)
    except Exception as e:
        print(f"[DailyDigest] CLI 调用失败: {e}")
        return False

    short_text, detail_text = _parse_dual_output(raw)

    if short_text:
        _append(MEMORY_SHORT_FILE, short_text)
    if detail_text:
        _append(MEMORY_DETAIL_FILE, detail_text)
    print(f"[DailyDigest] {target_date} short={len(short_text)} detail={len(detail_text)} 已写入")

    # 触发向量库增量索引（plugin 启用时）
    await _try_reindex_memory()

    # 检查是否该 fold
    content = _read(MEMORY_SHORT_FILE)
    dd_dates = sorted(set(_list_dd_dates(content)))
    if len(dd_dates) >= 7:
        await run_weekly_fold(dd_dates[:7])

    return True


async def run_weekly_fold(dd_dates_to_fold: list[str]) -> bool:
    if len(dd_dates_to_fold) != 7:
        print(f"[DailyDigest] weekly fold 需要 7 个 dd，收到 {len(dd_dates_to_fold)}")
        return False

    short_content = _read(MEMORY_SHORT_FILE)
    detail_content = _read(MEMORY_DETAIL_FILE)
    start, end = dd_dates_to_fold[0], dd_dates_to_fold[-1]

    # 收集 7 天的 SHORT + DETAIL 两份
    daily_dual = []
    for d in dd_dates_to_fold:
        short_m = re.search(
            rf"(<dd-{re.escape(d)}>.*?</dd-{re.escape(d)}>)",
            short_content, re.DOTALL,
        )
        detail_m = re.search(
            rf"(<dd-{re.escape(d)}>.*?</dd-{re.escape(d)}>)",
            detail_content, re.DOTALL,
        )
        if short_m or detail_m:
            block = ""
            if short_m:
                block += f"### {d} SHORT\n{short_m.group(1)}"
            if detail_m:
                block += f"\n### {d} DETAIL\n{detail_m.group(1)}"
            daily_dual.append(block)
    daily_chunk_text = "\n\n".join(daily_dual)

    # 历史 wk（两份）
    existing_wks_short = re.findall(r"<wk-[^>]+>.*?</wk-[^>]+>", short_content, re.DOTALL)
    existing_wks_detail = re.findall(r"<wk-[^>]+>.*?</wk-[^>]+>", detail_content, re.DOTALL)
    history = "### 既有 short 周总结\n" + ("\n\n".join(existing_wks_short) or "(无)")
    history += "\n\n### 既有 detail 周总结\n" + ("\n\n".join(existing_wks_detail) or "(无)")

    prompt = _WEEKLY_PROMPT_TEMPLATE.format(
        daily_chunk=daily_chunk_text, history=history, start=start, end=end,
    )

    print(f"[DailyDigest] 折叠 {start} → {end} 周总结（双份）...")
    loop = asyncio.get_running_loop()

    try:
        from server.config_store import get_config
        model = get_config().get("daily_digest", "model", default="claude-sonnet-4-6")
    except Exception:
        model = "claude-sonnet-4-6"

    try:
        raw = await loop.run_in_executor(None, _call_claude_cli, prompt, 600, model)
    except Exception as e:
        print(f"[DailyDigest] 周总结 CLI 失败: {e}")
        return False

    wk_short, wk_detail = _parse_dual_output(raw)

    # 从两个文件中删除那 7 个 dd
    new_short = short_content
    new_detail = detail_content
    for d in dd_dates_to_fold:
        pattern = rf"<dd-{re.escape(d)}>.*?</dd-{re.escape(d)}>\n?"
        new_short = re.sub(pattern, "", new_short, flags=re.DOTALL, count=1)
        new_detail = re.sub(pattern, "", new_detail, flags=re.DOTALL, count=1)

    def _insert_wk(content: str, wk_text: str, existing_wks: list[str]) -> str:
        if not wk_text:
            return content
        if existing_wks:
            last = existing_wks[-1]
            idx = content.rindex(last) + len(last)
            return content[:idx] + "\n\n" + wk_text.strip() + "\n" + content[idx:]
        return wk_text.strip() + "\n\n" + content

    new_short = _insert_wk(new_short, wk_short, existing_wks_short)
    new_detail = _insert_wk(new_detail, wk_detail, existing_wks_detail)

    MEMORY_SHORT_FILE.write_text(new_short, encoding="utf-8")
    MEMORY_DETAIL_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_DETAIL_FILE.write_text(new_detail, encoding="utf-8")
    print(f"[DailyDigest] 周总结已写入，折叠 {len(dd_dates_to_fold)} 个 dd")

    # 触发向量库重建（fold 影响面大）
    await _try_reindex_memory()
    return True


async def _try_reindex_memory():
    """尝试触发 knowledge plugin 的增量索引（plugin 未启用时静默跳过）"""
    try:
        from server.plugins.knowledge import get_manager
        mgr = get_manager()
        if mgr is None:
            return
        await mgr.reindex(source="memory")
    except Exception as e:
        print(f"[DailyDigest] 触发向量库增量索引失败（非致命）: {e}")


# ============== 后台 loop ==============

_loop_task: Optional[asyncio.Task] = None
_running = False


async def _poll_loop():
    print(f"[DailyDigest] 后台 loop 启动，触发条件：本地时间 ≥ {_TRIGGER_HOUR}:00 且昨日无 dd")
    while _running:
        try:
            # 读配置确认仍启用（运行时可改）
            enabled = True
            try:
                from server.config_store import get_config
                enabled = get_config().get("daily_digest", "enabled", default=True)
            except Exception:
                pass
            if enabled:
                now = datetime.now()
                yesterday = (now - timedelta(days=1)).date()
                if now.hour >= _TRIGGER_HOUR and not _has_dd_for(yesterday):
                    await run_daily_digest(yesterday)
        except Exception as e:
            print(f"[DailyDigest] loop 异常: {e}")
        await asyncio.sleep(_POLL_INTERVAL)


async def start():
    global _loop_task, _running
    if _running:
        return
    _running = True
    _loop_task = asyncio.create_task(_poll_loop())


async def stop():
    global _loop_task, _running
    _running = False
    if _loop_task:
        _loop_task.cancel()
        try:
            await _loop_task
        except asyncio.CancelledError:
            pass
        _loop_task = None
    print("[DailyDigest] 后台 loop 已停止")
