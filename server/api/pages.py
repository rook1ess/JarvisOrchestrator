"""HTML 页面路由"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse
from server.config import WEB_DIR

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index():
    html_file = WEB_DIR / "index.html"
    return html_file.read_text(encoding="utf-8")


@router.get("/settings")
async def settings():
    """旧 settings 页已合并到 dashboard，重定向"""
    return RedirectResponse(url="/dashboard")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    html_file = WEB_DIR / "dashboard.html"
    if html_file.exists():
        return html_file.read_text(encoding="utf-8")
    return "<h1>Dashboard page not found</h1>"
