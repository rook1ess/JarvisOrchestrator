"""HTML 页面路由"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from server.config import WEB_DIR

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index():
    html_file = WEB_DIR / "index.html"
    return html_file.read_text(encoding="utf-8")


@router.get("/settings", response_class=HTMLResponse)
async def settings():
    html_file = WEB_DIR / "settings.html"
    if html_file.exists():
        return html_file.read_text(encoding="utf-8")
    return "<h1>Settings page not found</h1>"


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    html_file = WEB_DIR / "dashboard.html"
    if html_file.exists():
        return html_file.read_text(encoding="utf-8")
    return "<h1>Dashboard page not found</h1>"
