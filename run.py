"""入口：uvicorn 启动"""

import uvicorn
from server.config import (
    SERVER_HOST, SERVER_PORT,
    NAPCAT_API_URL, QQ_ALLOWED_USERS, QQ_ALLOWED_GROUPS, QQ_GROUP_AT_ONLY,
)

if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  JARVIS Server v2 (Modular)")
    print(f"  http://localhost:{SERVER_PORT}")
    print("")
    print("  端点:")
    print("    POST /task/register  - 注册任务（启用超时检查）")
    print("    GET  /task/list      - 查看所有任务")
    print("    POST /callback       - 任务完成回调")
    print("    POST /qq/webhook     - QQ 消息接收（NapCat OneBot11）")
    print("")
    print(f"  QQ 配置:")
    print(f"    NapCat API: {NAPCAT_API_URL}")
    print(f"    用户白名单: {QQ_ALLOWED_USERS or '全部放行'}")
    print(f"    群白名单: {QQ_ALLOWED_GROUPS or '全部放行'}")
    print(f"    群聊仅@响应: {QQ_GROUP_AT_ONLY}")
    print("=" * 50 + "\n")

    uvicorn.run("server.main:app", host=SERVER_HOST, port=SERVER_PORT, reload=True)
