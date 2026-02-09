"""入口：uvicorn 启动"""

import uvicorn
from server.config import (
    SERVER_HOST, SERVER_PORT,
    NAPCAT_API_URL, QQ_ALLOWED_USERS, QQ_ALLOWED_GROUPS, QQ_GROUP_AT_ONLY,
)

if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  JARVIS Server v2")
    print(f"  http://localhost:{SERVER_PORT}")
    print("")
    print("  主要端点:")
    print("    WS   /ws/chat           - WebSocket 聊天")
    print("    GET  /api/instances      - 实例列表")
    print("    GET  /api/claude-sessions - 会话列表")
    print("    POST /callback           - 子进程回调")
    print("    POST /qq/webhook         - QQ 消息（NapCat OneBot11）")
    print("    GET  /health             - 健康检查")
    print("    *    /mcp/mcp            - MCP Server")
    print("")
    if NAPCAT_API_URL != "http://localhost:3000" or QQ_ALLOWED_USERS or QQ_ALLOWED_GROUPS:
        print(f"  QQ 配置:")
        print(f"    NapCat API: {NAPCAT_API_URL}")
        print(f"    用户白名单: {QQ_ALLOWED_USERS or '全部放行'}")
        print(f"    群白名单: {QQ_ALLOWED_GROUPS or '全部放行'}")
        print(f"    群聊仅@响应: {QQ_GROUP_AT_ONLY}")
    print("=" * 50 + "\n")

    uvicorn.run("server.main:app", host=SERVER_HOST, port=SERVER_PORT, reload=True)
