#!/bin/bash
# 一键启动容器内 Claude Code（支持多开，每次 docker exec 都是独立进程）

CONTAINER="claude-dev"

docker start "$CONTAINER" 2>/dev/null

TOKEN="${CLAUDE_CODE_OAUTH_TOKEN}"
if [ -z "$TOKEN" ]; then
    TOKEN=$(launchctl getenv CLAUDE_CODE_OAUTH_TOKEN 2>/dev/null)
fi
if [ -z "$TOKEN" ]; then
    echo "错误：CLAUDE_CODE_OAUTH_TOKEN 未设置"
    echo "请执行：launchctl setenv CLAUDE_CODE_OAUTH_TOKEN \"你的token\""
    read -p "按回车退出..."
    exit 1
fi

exec docker exec -it -e "CLAUDE_CODE_OAUTH_TOKEN=$TOKEN" "$CONTAINER" \
    bash -c "cd /home/claude/workspace && claude --dangerously-skip-permissions"
