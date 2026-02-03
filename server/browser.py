"""Playwright headless browser manager - 管理多个命名 session"""

import asyncio
import re
import time
from dataclasses import dataclass, field

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Locator


# 可交互的 ARIA roles
_INTERACTIVE_ROLES = frozenset({
    "link", "button", "textbox", "combobox", "checkbox", "radio",
    "menuitem", "menuitemcheckbox", "menuitemradio", "option",
    "searchbox", "slider", "spinbutton", "switch", "tab", "treeitem",
})

# 匹配 aria_snapshot 行: "- role "name"..." or "- role:" etc.
_LINE_RE = re.compile(r'^(\s*- )(\w+)(.*)')


@dataclass
class BrowserSession:
    context: BrowserContext
    page: Page
    ref_map: dict[str, Locator] = field(default_factory=dict)
    last_active: float = field(default_factory=time.time)


class BrowserManager:
    """单 Browser 多 Context，lazy init"""

    def __init__(self, headless: bool = True, idle_timeout: float = 1800):
        self._headless = headless
        self._idle_timeout = idle_timeout
        self._playwright = None
        self._browser: Browser | None = None
        self._sessions: dict[str, BrowserSession] = {}
        self._lock = asyncio.Lock()

    async def ensure_browser(self) -> Browser:
        if self._browser and self._browser.is_connected():
            return self._browser
        async with self._lock:
            if self._browser and self._browser.is_connected():
                return self._browser
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=self._headless)
        return self._browser

    async def get_session(self, name: str = "default") -> BrowserSession:
        if name in self._sessions:
            s = self._sessions[name]
            if not s.page.is_closed():
                s.last_active = time.time()
                return s
            del self._sessions[name]

        browser = await self.ensure_browser()
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        page = await context.new_page()
        session = BrowserSession(context=context, page=page)
        self._sessions[name] = session
        return session

    async def close_session(self, name: str):
        s = self._sessions.pop(name, None)
        if s:
            await s.context.close()

    async def close_all(self):
        for name in list(self._sessions):
            await self.close_session(name)
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def snapshot(self, session_name: str = "default", interactive_only: bool = False) -> str:
        """生成 accessibility tree 文本 + ref map

        使用 Playwright aria_snapshot() 获取页面结构，
        为可交互元素注入 [ref=eN] 标记并缓存 locator 映射。
        """
        s = await self.get_session(session_name)
        s.ref_map.clear()

        raw = await s.page.locator("body").aria_snapshot()
        if not raw or not raw.strip():
            return "[empty page]"

        counter = 0
        out_lines: list[str] = []

        for line in raw.split("\n"):
            m = _LINE_RE.match(line)
            if m:
                indent, role, rest = m.group(1), m.group(2), m.group(3)
                if role in _INTERACTIVE_ROLES:
                    counter += 1
                    ref = f"e{counter}"
                    # Extract name from rest: could be ' "Name"...' or ':'
                    name = _extract_name(rest)
                    s.ref_map[ref] = _build_locator(s.page, role, name)
                    if interactive_only:
                        out_lines.append(f"{indent}{role}{rest} [ref={ref}]")
                    else:
                        out_lines.append(f"{indent}{role}{rest} [ref={ref}]")
                else:
                    if not interactive_only:
                        out_lines.append(line)
            else:
                if not interactive_only:
                    out_lines.append(line)

        url = s.page.url
        title = await s.page.title()
        header = f"[Page] {title}\n[URL] {url}\n---\n"
        return header + "\n".join(out_lines)


def _extract_name(rest: str) -> str:
    """从 aria_snapshot 行的 rest 部分提取名称"""
    # Pattern: ' "Some Name"' or ' "Some Name":' or ': some text'
    m = re.search(r'"([^"]*)"', rest)
    if m:
        return m.group(1)
    # "role: text" pattern
    m = re.match(r':\s*(.+)', rest.strip())
    if m:
        return m.group(1).strip()
    return ""


def _build_locator(page: Page, role: str, name: str) -> Locator:
    """从 role + name 构建 Playwright locator"""
    if name:
        return page.get_by_role(role, name=name)
    return page.get_by_role(role)
