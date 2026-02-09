# Claude Agent v2 - 开发日志

## 2026-02-09 遗留代码清理 + 架构统一

### 1. 前端：移除旧 Agent/Session 系统

项目从 v1 的"Agent 模板"架构重构为"Instance 配置"后，前端仍残留两套并行的 session 管理系统和完整的 agent 选择器代码。旧系统调用的 API（`/api/agents`, `/api/sessions`）在服务端已不存在。

**删除的死代码：**
- `currentAgent`, `agentNameMap` 变量
- `loadAgents()` — 调用不存在的 `/api/agents`
- `handleAgentChange()` — 调用不存在的 `/api/restart?agent_id=`
- `loadSessions()`, `renderSessionList()` — 旧 session 系统
- `window.switchSession` — 调用不存在的 `/api/sessions/{id}`
- `confirmRename()`, `confirmDelete()` — 旧 session modal 操作
- HTML 中的 Agent Selector 下拉框和状态指示器

**修复：**
- Session Tabs 改为调用 `switchClaudeSession()` / `createNewClaudeSession()`
- 移动菜单 wrapper 改为包装 `switchClaudeSession`
- 导出功能改用 `currentInstance` 替代 `agentNameMap`
- 统一使用 `currentClaudeSessionId` 作为唯一 session 标识

### 2. 后端：API 模块整理

- 将 `agents.py` 的路由（`/api/instances/config`, `/api/subagents`）合并到 `instances.py`，删除 `agents.py`
- `sessions.py` 所有 API 新增 `instance_id` 查询参数，不再硬编码 `ws-default`

### 3. 后端：Bug 修复

- `TaskManager.complete()` — 修复完成的任务未从活跃列表移除的 bug
- QQ Channel `_contexts` — 修复 done 后未清理 context 导致的内存泄漏
- `router.py` `resolve()` — 重写匹配逻辑，移除永远不会触发的 fallback 循环

### 4. 后端：代码质量

- `AgentManager` — 添加 `get_instance_config()`, `get_all_instance_configs()`, `update_instance_config()`, `clear_instance_config_key()` 公开方法，替代外部直接访问 `_instance_configs`
- `mcp_server.py` — 硬编码路径（`CONTAINER_NAME`, `HOST_PROJECTS`, `CONTAINER_WORKSPACE`）改为环境变量可覆盖
- `requirements.txt` — 补全 `mcp>=1.0.0`, `playwright>=1.40.0`
- `run.py` — 更新启动信息，反映当前实际端点

### 5. 清理

- 删除 `sessions.json` — 旧版自定义 session 存储，已被 Claude SDK JSONL 替代
- 删除 `server/api/agents.py` — 路由已合并到 `instances.py`

## 2026-02-06 Session 管理修复 + 消息加载架构重构

### 1. `restart()` 新建 Session Bug 修复

`instance.restart(resume_session=None)` 本意是创建新 session，但由于 Python truthy/falsy 陷阱，`None` 被当作"未传参"处理，实际恢复了旧 session。

**修改文件：**
- `server/agents/instance.py` — 引入 `_UNSET` 哨兵值，区分三种调用语义：
  - `restart()` 不传参 → 保留当前 session
  - `restart(resume_session=None)` → 创建全新 session
  - `restart(resume_session="xxx")` → 恢复指定 session
- `server/api/sessions.py` — `create_new_claude_session` 中清除 `_instance_configs` 的 `last_session_id`，防止实例被 idle 回收后重建时恢复旧 session

### 2. 消息加载改为服务端唯一 truth

旧方案：前端 localStorage 存消息副本 + 服务端 Claude session JSONL 各存一份，容易 desync（跨设备、服务器重启、idle 回收等场景）。

新方案：删除 localStorage 消息持久化，页面启动时从服务端 `/api/claude-sessions/{id}/messages` 加载历史消息。

**修改文件：**
- `server/api/sessions.py` — `get_claude_sessions` API 新增 `pending_session` 支持（实例未创建但有保存 session 时返回）
- `web/app.js` — 删除 `saveMessagesToStorage`/`restoreMessagesFromStorage`/`checkServerSession` 等 localStorage 消息函数；新增 `loadCurrentSessionMessages()` 从服务端加载；WebSocket `connected` 事件触发加载

### 3. 多设备 Session 同步

前端新增 `session_changed` WebSocket 消息处理，其他设备创建新 session 或切换 session 时，本设备自动同步 UI。用 `_sessionChangeInitiatedLocally` 标记避免发起设备重复处理。

**设计决策：**
- 服务端 JSONL 为唯一消息来源，前端不再缓存消息
- 当前 JSONL 解析只提取纯文本（user/assistant），tool calls、图片等未还原（后续可扩展）
- `clearStorage()` 保留用于清理旧版 localStorage 数据

## 2026-02-03 Agent 间通信 + MCP Tools

### 1. Agent 实例发现与消息传递

新增 REST API + MCP Server，让所有 Agent 实例（ws-default, qq-default 等）能互相发现、互相发消息。

**新文件：**
- `server/api/instances.py` — REST 端点：`GET /api/instances`（列出实例）、`POST /api/instances/{id}/send`（发送消息入队）
- `server/mcp_server.py` — Streamable HTTP MCP Server，挂载在 FastAPI 同端口 `/mcp` 路径

**修改文件：**
- `server/main.py` — 挂载 instances 路由 + MCP Server
- `server/agents/instance.py` — `_build_system_status` 中添加兄弟实例列表，新增 `_agent_manager` 注入
- `server/agents/manager.py` — 创建/自愈实例时注入 `agent_manager` 引用
- `.mcp.json` — 添加 `jarvis` MCP Server 配置（`http://localhost:6790/mcp`）

**MCP 实例通信工具（2 个）：**
- `jarvis_list_instances` — 列出所有实例及状态
- `jarvis_send_message` — 向指定实例发送消息（异步入队，不等回复）

### 2. tmux 子进程管理 MCP Tools

将 jarvis-controller skill 中的 tmux 操作封装为 MCP tools，解决手动拼命令易出错、多次 Enter 等问题。

**MCP 子进程管理工具（5 个）：**
- `jarvis_spawn_task` — 一键派生子 Claude：创建 tmux → 启动 docker/local Claude → 等待就绪 → 发送任务（含 callback 协议）→ 注册超时监控。自动处理 token 注入、路径转换、引号转义、多次 Enter
- `jarvis_check_output` — 查看 tmux 子进程最近输出
- `jarvis_send_input` — 向子进程发送输入（自动多次 Enter 确保送达）
- `jarvis_kill_task` — 终止 tmux session + 清理任务注册
- `jarvis_list_tasks` — 列出所有 tmux session + 已注册任务

**设计决策：**
- MCP Server 挂在 FastAPI 同进程同端口，tool 内部直接 Python 函数调用，无进程间通信
- 异步消息模式：send 只入队不阻塞，需要对话则双方互发
- jarvis-controller skill 保留不删，作为 fallback 文档
- `CLAUDE_CODE_OAUTH_TOKEN` 每次 spawn 时从环境变量实时读取，支持动态修改

### 3. Playwright Headless 浏览器自动化 MCP Tools

新增 headless Chromium 浏览器控制，让 Agent 实例能自主操控浏览器完成网页交互。

**新文件：**
- `server/browser.py` — BrowserManager（单例）+ BrowserSession，管理 Playwright 浏览器实例和多个命名 session

**修改文件：**
- `server/mcp_server.py` — 新增 10 个 browser tools
- `server/main.py` — lifespan shutdown 中调用 `browser_manager.close_all()` 清理

**MCP 浏览器工具（10 个）：**
- `browser_navigate` — 导航到 URL（首次调用 lazy 启动 Chromium）
- `browser_snapshot` — 获取页面 accessibility tree + `[ref=eN]` 引用标记
- `browser_screenshot` — 截图返回 base64 PNG
- `browser_click` — 通过 ref 点击元素
- `browser_fill` — 通过 ref 填写输入框，可选 submit
- `browser_select` — 通过 ref 选择下拉选项
- `browser_evaluate` — 执行 JavaScript
- `browser_wait` — 等待条件（selector/url/load）
- `browser_get_content` — 提取页面或元素文本内容
- `browser_close` — 关闭 session 或所有浏览器

**设计决策：**
- Accessibility tree 优先（`aria_snapshot()`），省 token 不需 vision model
- 单 Browser 多 Context：一个 chromium 进程，每个 session 独立 context（独立 cookies）
- Lazy init：首次 tool call 时才启动浏览器
- Ref 在导航后失效，需重新 snapshot
- 依赖：`playwright` + `playwright install chromium`

### 4. 实例配置架构重构

将旧的"Agent 模板"（agents/*.json）重构为"实例配置"（instances/*.json），简化概念。

**删除：**
- `agents/` 目录（旧的 agent 模板，包括 default.json, writer.json, xhs.json）
- `AgentConfig` 数据模型
- `load_agent_configs()` 函数
- `routing.json` 中的 `agent` 字段

**新增：**
- `instances/_default.json` — 所有实例的默认配置（system_prompt, model, mcp, tools 等）
- `instances/ws-default.json` — WebSocket 实例特定配置（可覆盖默认）
- `instances/qq-default.json` — QQ 实例特定配置
- `load_instance_config(instance_id)` — 加载配置（_default + 实例特定合并）
- `jarvis_restart_instance` MCP tool — 重启实例，重载配置，保留对话

**概念变化：**
- 旧：agent_id（模板）→ instance_id（运行时），多对多关系
- 新：instance_id 即配置标识，一对一关系，配置直接按 instance_id 加载
- `AgentInstance` 构造函数只需 `instance_id`，不再需要 `agent_id`
- 配置变更后调用 `restart()` 生效，保留 session

**配置合并逻辑：**
1. 读取 `instances/_default.json` 作为基础
2. 读取 `instances/{instance_id}.json`，用其字段覆盖默认值
3. 忽略以 `_` 开头的字段（如 `_comment`）

### 5. ResultMessage 上下文统计显示

前端显示每轮对话的 token 用量、费用、耗时等信息。

**修改文件：**
- `server/agents/instance.py` — ResultMessage 广播完整字段（session_id, cost_usd, duration_ms, num_turns, usage）
- `web/app.js` — 解析 result 消息并显示统计
- `web/style.css` — 添加 `.result-context-info` 样式

**显示格式：**
```
12,345 in / 2,345 out · cache: 10,000 · $0.0312 · 4.2s
```
