"""HTML 页面路由"""

from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from server.config import WEB_DIR

router = APIRouter()

# 允许访问的本地目录（防止任意文件读取）
_ALLOWED_ROOTS = [
    Path.home() / "Pictures",
    Path.home() / "Downloads",
    Path.home() / "Desktop",
    Path.home() / "Projects",
    Path("/tmp"),
]

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}


@router.get("/api/file")
async def serve_local_file(path: str):
    """提供本地文件访问（限制目录 + 图片类型）"""
    file_path = Path(path).resolve()

    # 检查文件扩展名
    if file_path.suffix.lower() not in _IMAGE_EXTENSIONS:
        raise HTTPException(status_code=403, detail="Only image files allowed")

    # 检查是否在允许的目录下
    if not any(file_path.is_relative_to(root.resolve()) for root in _ALLOWED_ROOTS):
        raise HTTPException(status_code=403, detail="Path not in allowed directories")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(file_path)


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
