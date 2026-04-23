// Settings drawer — 独立模块，通过 /api/config 读写 data/config.json
(function () {
    'use strict';

    const drawer = document.getElementById('settingsDrawer');
    const backdrop = document.getElementById('settingsDrawerBackdrop');
    const openBtn = document.getElementById('settingsBtn');
    const closeBtn = document.getElementById('closeSettingsDrawerBtn');
    const cancelBtn = document.getElementById('settingsCancelBtn');
    const saveBtn = document.getElementById('settingsSaveBtn');
    const saveRestartBtn = document.getElementById('settingsSaveRestartBtn');
    const tabsEl = document.getElementById('settingsTabs');
    const body = document.getElementById('settingsDrawerBody');
    const footerHint = document.getElementById('settingsFooterHint');

    if (!drawer || !openBtn) return;

    let currentConfig = null;
    let originalConfig = null;
    let currentTab = 'dialog';

    // 当前实例（从 URL ?instance= 读，同 app.js 逻辑）
    function getCurrentInstance() {
        const params = new URLSearchParams(window.location.search);
        return params.get('instance') || 'ws-default';
    }
    const currentInstance = getCurrentInstance();

    const PERMISSION_MODES = [
        { value: 'default', name: 'Default', desc: 'SDK 默认权限，按 allowed_tools 控制' },
        { value: 'acceptEdits', name: 'Accept Edits', desc: '自动接受文件编辑' },
        { value: 'bypassPermissions', name: 'Bypass', desc: '跳过所有权限询问（当前常用）' },
        { value: 'plan', name: 'Plan', desc: '计划模式（只读）' },
    ];

    // Inline SVG icons (取代 emoji)
    const ICON_RESTART = '<svg class="hint-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>';
    const ICON_LOCK = '<svg class="hint-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>';

    // ---------- Open/close ----------

    function openDrawer() {
        drawer.classList.add('visible');
        loadConfig();
    }
    function closeDrawer() {
        drawer.classList.remove('visible');
    }

    // ---------- Load & render ----------

    async function loadConfig() {
        body.innerHTML = '<div class="settings-loading">加载中…</div>';
        try {
            const res = await fetch('/api/config');
            if (!res.ok) throw new Error('HTTP ' + res.status);
            currentConfig = await res.json();
            originalConfig = JSON.parse(JSON.stringify(currentConfig));
            render();
        } catch (e) {
            body.innerHTML = `<div class="settings-error">加载失败: ${escapeHTML(String(e))}</div>`;
        }
    }

    function render() {
        const html = buildPanelHTML(currentTab);
        body.innerHTML = html;
        bindInputs();
        bindPanelActions();
    }

    function buildPanelHTML(tab) {
        if (tab === 'memory') return memoryPanel();
        if (tab === 'knowledge') return knowledgePanel();
        if (tab === 'dialog') return dialogPanel();
        if (tab === 'schedule') return schedulePanel();
        if (tab === 'channel') return channelPanel();
        if (tab === 'service') return servicePanel();
        return '';
    }

    // ---------- Panels ----------

    function memoryPanel() {
        const m = currentConfig.memory || {};
        return `
            <section class="settings-section">
                <h4>召回策略</h4>
                <p class="settings-hint">控制 UserPromptSubmit hook 是否在每轮注入相关记忆。Token 成本与召回质量的权衡。</p>
                <div class="settings-row">
                    <label>策略</label>
                    <select data-path="memory.recall_strategy">
                        <option value="off" ${m.recall_strategy === 'off' ? 'selected' : ''}>关闭（不召回）</option>
                        <option value="triggered" ${m.recall_strategy === 'triggered' ? 'selected' : ''}>触发式（关键词命中才召回）</option>
                        <option value="light" ${m.recall_strategy === 'light' ? 'selected' : ''}>轻量常驻（每轮返回标题）</option>
                    </select>
                </div>
                <div class="settings-row">
                    <label>Top K</label>
                    <input type="number" min="1" max="10" value="${m.recall_top_k || 3}" data-path="memory.recall_top_k" data-type="int">
                </div>
                <div class="settings-row">
                    <label>最低分阈值 (0-1)</label>
                    <input type="number" min="0" max="1" step="0.05" value="${m.recall_min_score ?? 0.3}" data-path="memory.recall_min_score" data-type="float">
                </div>
                <div class="settings-row">
                    <label>时间衰减半衰期（天）</label>
                    <input type="number" min="1" value="${m.temporal_half_life_days || 30}" data-path="memory.temporal_half_life_days" data-type="int">
                </div>
            </section>
            <section class="settings-section">
                <h4>触发关键词</h4>
                <p class="settings-hint">用户消息命中任一关键词时启动召回。逗号分隔，不区分大小写（英文）。</p>
                <div class="settings-row column">
                    <label>中文</label>
                    <input type="text" value="${escapeAttr((m.recall_trigger_keywords_zh || []).join(', '))}" data-path="memory.recall_trigger_keywords_zh" data-type="csv">
                </div>
                <div class="settings-row column">
                    <label>英文</label>
                    <input type="text" value="${escapeAttr((m.recall_trigger_keywords_en || []).join(', '))}" data-path="memory.recall_trigger_keywords_en" data-type="csv">
                </div>
            </section>
        `;
    }

    function knowledgePanel() {
        const p = currentConfig.plugins || {};
        const e = currentConfig.embedding || {};
        const k = currentConfig.api_keys || {};
        const kb = currentConfig.knowledge || {};
        return `
            <section class="settings-section">
                <h4>Knowledge Plugin <span class="hint-restart">${ICON_RESTART}切换需重启</span></h4>
                <p class="settings-hint">启用后可索引 data/knowledge/ 下文件 + memory_detail.md + projects_detail.md。</p>
                <div class="settings-row">
                    <label>启用向量知识库</label>
                    <label class="switch">
                        <input type="checkbox" ${p.knowledge ? 'checked' : ''} data-path="plugins.knowledge" data-type="bool">
                        <span class="slider"></span>
                    </label>
                </div>
            </section>
            <section class="settings-section">
                <h4>Embedding Provider</h4>
                <p class="settings-hint">Auto fallback 顺序。local 为本地 GGUF（零成本，推荐首选）；其他为付费 API。</p>
                <div class="settings-row column">
                    <label>优先级（逗号分隔）</label>
                    <input type="text" value="${escapeAttr((e.auto_priority || []).join(', '))}" data-path="embedding.auto_priority" data-type="csv">
                </div>
                <div class="settings-row column">
                    <label>本地 GGUF 模型（留空用 data/models/embeddinggemma-300m-qat-Q8_0.gguf）</label>
                    <input type="text" value="${escapeAttr(e.local_model_path || '')}" data-path="embedding.local_model_path">
                </div>
            </section>
            <section class="settings-section">
                <h4>API Keys <span class="hint-sensitive">${ICON_LOCK}敏感，明文写入 data/config.json（chmod 600）</span></h4>
                <p class="settings-hint">显示为打码，留空或打码不变；输入新值则更新。</p>
                <div class="settings-row">
                    <label>OpenAI</label>
                    <input type="password" value="${escapeAttr(k.openai || '')}" data-path="api_keys.openai" autocomplete="off" placeholder="sk-...">
                </div>
                <div class="settings-row">
                    <label>Voyage</label>
                    <input type="password" value="${escapeAttr(k.voyage || '')}" data-path="api_keys.voyage" autocomplete="off">
                </div>
                <div class="settings-row">
                    <label>Mistral</label>
                    <input type="password" value="${escapeAttr(k.mistral || '')}" data-path="api_keys.mistral" autocomplete="off">
                </div>
                <div class="settings-row">
                    <label>Google</label>
                    <input type="password" value="${escapeAttr(k.google || '')}" data-path="api_keys.google" autocomplete="off">
                </div>
            </section>
            <section class="settings-section">
                <h4>混合检索参数</h4>
                <div class="settings-row">
                    <label>向量权重</label>
                    <input type="number" min="0" max="1" step="0.05" value="${kb.hybrid_vec_weight ?? 0.7}" data-path="knowledge.hybrid_vec_weight" data-type="float">
                </div>
                <div class="settings-row">
                    <label>BM25 权重</label>
                    <input type="number" min="0" max="1" step="0.05" value="${kb.hybrid_bm25_weight ?? 0.3}" data-path="knowledge.hybrid_bm25_weight" data-type="float">
                </div>
                <div class="settings-row">
                    <label>MMR 去冗余</label>
                    <label class="switch"><input type="checkbox" ${kb.mmr_enabled ? 'checked' : ''} data-path="knowledge.mmr_enabled" data-type="bool"><span class="slider"></span></label>
                </div>
                <div class="settings-row">
                    <label>Chunk tokens</label>
                    <input type="number" min="100" max="4096" value="${kb.chunk_tokens || 1024}" data-path="knowledge.chunk_tokens" data-type="int">
                </div>
                <div class="settings-row">
                    <label>Chunk overlap</label>
                    <input type="number" min="0" max="1024" value="${kb.chunk_overlap || 160}" data-path="knowledge.chunk_overlap" data-type="int">
                </div>
            </section>
            <section class="settings-section">
                <h4>索引管理</h4>
                <div class="settings-row">
                    <label>操作</label>
                    <div class="settings-inline-actions">
                        <button type="button" class="btn btn-secondary" id="kbStatsBtn">查看统计</button>
                    </div>
                </div>
                <pre class="settings-log" id="kbStatsLog">提示：通过对话让小克调用 jarvis_knowledge_reindex 重建索引；或 jarvis_knowledge_stats 查看。</pre>
            </section>
        `;
    }

    function dialogPanel() {
        const s = currentConfig.service || {};
        const perms = PERMISSION_MODES.map((m) => `
            <label class="permission-option" data-perm-value="${m.value}">
                <input type="radio" name="__perm" value="${m.value}">
                <div class="permission-option-body">
                    <div class="permission-option-name">${m.name}</div>
                    <div class="permission-option-desc">${escapeHTML(m.desc)}</div>
                </div>
            </label>
        `).join('');
        return `
            <section class="settings-section">
                <h4>权限模式 <span class="hint-sensitive">运行时即时生效</span></h4>
                <p class="settings-hint">控制 Agent 使用工具时的权限策略。实例 <code>${escapeHTML(currentInstance)}</code></p>
                <div class="permission-options" id="permissionOptions">${perms}</div>
            </section>
            <section class="settings-section">
                <h4>MCP Servers <span class="hint-sensitive">运行时开关，重启后保留</span></h4>
                <p class="settings-hint">启用/禁用当前实例挂载的 MCP 服务器。</p>
                <div class="mcp-server-list" id="mcpServerList"><div class="settings-loading">加载中…</div></div>
            </section>
            <section class="settings-section">
                <h4>实例空闲回收</h4>
                <div class="settings-row">
                    <label>空闲超时（分钟）</label>
                    <input type="number" min="5" value="${s.idle_timeout_minutes || 60}" data-path="service.idle_timeout_minutes" data-type="int">
                </div>
                <p class="settings-hint" style="margin-top:8px">模型、context 用量在 Header 切换；disallowed_tools / subagents / sandbox 等实例级配置在 <code>instances/${escapeHTML(currentInstance)}.json</code>。</p>
            </section>
            <section class="settings-section">
                <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px">
                    <h4 style="margin:0">子进程 &amp; 环境</h4>
                    <div style="display:flex;gap:6px;align-items:center">
                        <span id="subprocInfoAge" style="font-size:12px;color:var(--text-secondary)"></span>
                        <button type="button" class="btn btn-secondary" id="subprocRefreshBtn" style="padding:4px 10px;font-size:12.5px">刷新</button>
                    </div>
                </div>
                <p class="settings-hint">运行时探测，缓存 5 分钟。容器停止时仅显示宿主信息。</p>
                <div class="subproc-info" id="subprocInfo"><div class="settings-loading">加载中…</div></div>
            </section>
        `;
    }

    function schedulePanel() {
        const d = currentConfig.daily_digest || {};
        return `
            <section class="settings-section">
                <h4>Daily Digest（每日/每周摘要）</h4>
                <p class="settings-hint">独立 asyncio loop，每 10 分钟轮询；本地时间 ≥ trigger_hour 且昨日无 dd 时触发。</p>
                <div class="settings-row">
                    <label>启用</label>
                    <label class="switch"><input type="checkbox" ${d.enabled !== false ? 'checked' : ''} data-path="daily_digest.enabled" data-type="bool"><span class="slider"></span></label>
                </div>
                <div class="settings-row">
                    <label>触发时间（小时，0-23）</label>
                    <input type="number" min="0" max="23" value="${d.trigger_hour ?? 2}" data-path="daily_digest.trigger_hour" data-type="int">
                </div>
                <div class="settings-row">
                    <label>摘要模型</label>
                    <input type="text" value="${escapeAttr(d.model || 'claude-sonnet-4-6')}" data-path="daily_digest.model">
                </div>
                <div class="settings-row">
                    <label>单条消息截断阈值（字符）</label>
                    <input type="number" min="1000" value="${d.per_message_threshold || 20000}" data-path="daily_digest.per_message_threshold" data-type="int">
                </div>
                <div class="settings-row">
                    <label>单日流水硬上限（字符）</label>
                    <input type="number" min="10000" value="${d.total_limit || 50000}" data-path="daily_digest.total_limit" data-type="int">
                </div>
            </section>
            <section class="settings-section">
                <h4>ScheduledTaskManager（定时/巡检任务）</h4>
                <p class="settings-hint">定时任务列表、巡检任务在右侧"任务状态"抽屉管理。</p>
            </section>
        `;
    }

    function channelPanel() {
        const qq = (currentConfig.channels && currentConfig.channels.qq) || {};
        return `
            <section class="settings-section">
                <h4>QQ (NapCat OneBot11)</h4>
                <div class="settings-row">
                    <label>启用</label>
                    <label class="switch"><input type="checkbox" ${qq.enabled ? 'checked' : ''} data-path="channels.qq.enabled" data-type="bool"><span class="slider"></span></label>
                </div>
                <div class="settings-row">
                    <label>NapCat URL</label>
                    <input type="text" value="${escapeAttr(qq.napcat_url || 'http://localhost:3000')}" data-path="channels.qq.napcat_url">
                </div>
                <div class="settings-row">
                    <label>NapCat Token <span class="hint-sensitive">${ICON_LOCK}敏感</span></label>
                    <input type="password" value="${escapeAttr(qq.napcat_token || '')}" data-path="channels.qq.napcat_token" autocomplete="off">
                </div>
                <div class="settings-row column">
                    <label>允许的用户 QQ（逗号分隔数字，空=允许所有）</label>
                    <input type="text" value="${escapeAttr((qq.allowed_users || []).join(', '))}" data-path="channels.qq.allowed_users" data-type="csvint">
                </div>
                <div class="settings-row column">
                    <label>允许的群 QQ</label>
                    <input type="text" value="${escapeAttr((qq.allowed_groups || []).join(', '))}" data-path="channels.qq.allowed_groups" data-type="csvint">
                </div>
                <div class="settings-row">
                    <label>群聊仅响应 @</label>
                    <label class="switch"><input type="checkbox" ${qq.group_at_only ? 'checked' : ''} data-path="channels.qq.group_at_only" data-type="bool"><span class="slider"></span></label>
                </div>
            </section>
        `;
    }

    function servicePanel() {
        const s = currentConfig.service || {};
        return `
            <section class="settings-section">
                <h4>网络 <span class="hint-restart">${ICON_RESTART}需重启</span></h4>
                <div class="settings-row">
                    <label>Bind Host</label>
                    <select data-path="service.host">
                        <option value="127.0.0.1" ${s.host === '127.0.0.1' ? 'selected' : ''}>127.0.0.1（仅本机，推荐）</option>
                        <option value="0.0.0.0" ${s.host === '0.0.0.0' ? 'selected' : ''}>0.0.0.0（局域网可访问）</option>
                    </select>
                </div>
                <div class="settings-row">
                    <label>端口</label>
                    <input type="number" min="1024" max="65535" value="${s.port || 6790}" data-path="service.port" data-type="int">
                </div>
            </section>
            <section class="settings-section">
                <h4>运维</h4>
                <div class="settings-row">
                    <label>重启后端服务</label>
                    <div class="settings-inline-actions">
                        <button type="button" class="btn btn-secondary" id="restartServerBtn">立即重启</button>
                    </div>
                </div>
                <div class="settings-row">
                    <label>重载配置（不重启）</label>
                    <div class="settings-inline-actions">
                        <button type="button" class="btn btn-secondary" id="reloadConfigBtn">从磁盘重载</button>
                    </div>
                </div>
                <pre class="settings-log" id="serviceLog"></pre>
            </section>
        `;
    }

    // ---------- Input binding ----------

    function bindInputs() {
        body.querySelectorAll('[data-path]').forEach((el) => {
            el.addEventListener('change', () => {
                const path = el.dataset.path.split('.');
                const type = el.dataset.type || 'string';
                let v;
                if (el.type === 'checkbox') v = el.checked;
                else v = el.value;

                if (type === 'int') v = parseInt(v, 10) || 0;
                else if (type === 'float') v = parseFloat(v) || 0;
                else if (type === 'csv') v = typeof v === 'string' ? v.split(',').map(s => s.trim()).filter(Boolean) : v;
                else if (type === 'csvint') v = typeof v === 'string' ? v.split(',').map(s => parseInt(s.trim(), 10)).filter(n => !isNaN(n)) : v;

                setByPath(currentConfig, path, v);
            });
        });
    }

    function bindPanelActions() {
        // Dialog Tab: 权限 + MCP 加载 / 绑定
        if (currentTab === 'dialog') {
            loadPermissionState();
            loadMcpList();
            loadSubprocInfo(false);
            body.querySelectorAll('.permission-option').forEach((el) => {
                el.addEventListener('click', async (e) => {
                    e.preventDefault();
                    const val = el.dataset.permValue;
                    await setPermissionMode(val);
                });
            });
            body.querySelector('#subprocRefreshBtn')?.addEventListener('click', () => loadSubprocInfo(true));
        }

        body.querySelector('#kbStatsBtn')?.addEventListener('click', async () => {
            const log = body.querySelector('#kbStatsLog');
            log.textContent = '（提示）请在对话中让小克调用 jarvis_knowledge_stats 查看统计。';
        });

        body.querySelector('#restartServerBtn')?.addEventListener('click', async () => {
            const log = body.querySelector('#serviceLog');
            log.textContent = '重启中…';
            try {
                await fetch('/api/restart-server', { method: 'POST' });
                log.textContent = '重启指令已发出，页面将在 3 秒后刷新';
                setTimeout(() => location.reload(), 3000);
            } catch (e) {
                log.textContent = '失败: ' + e;
            }
        });

        body.querySelector('#reloadConfigBtn')?.addEventListener('click', async () => {
            const log = body.querySelector('#serviceLog');
            log.textContent = '重载中…';
            try {
                await fetch('/api/config/reload', { method: 'POST' });
                await loadConfig();
                log.textContent = '已重载（注意：部分已缓存的配置需重启服务生效）';
            } catch (e) {
                log.textContent = '失败: ' + e;
            }
        });
    }

    // ---------- Save ----------

    function buildDiff() {
        function prune(current, original) {
            const out = {};
            if (typeof current !== 'object' || current === null) return current;
            for (const key of Object.keys(current)) {
                const c = current[key];
                const o = original?.[key];
                if (Array.isArray(c)) {
                    if (JSON.stringify(c) !== JSON.stringify(o)) out[key] = c;
                } else if (typeof c === 'object' && c !== null) {
                    const sub = prune(c, o);
                    if (sub && typeof sub === 'object' && Object.keys(sub).length) out[key] = sub;
                } else {
                    // 打码值（•开头）视为未改
                    if (typeof c === 'string' && c.startsWith('•')) continue;
                    if (JSON.stringify(c) !== JSON.stringify(o)) out[key] = c;
                }
            }
            return out;
        }
        return prune(currentConfig, originalConfig);
    }

    async function save(restart) {
        const changes = buildDiff();
        if (Object.keys(changes).length === 0 && !restart) {
            footerHint.textContent = '无改动';
            setTimeout(() => (footerHint.textContent = ''), 1500);
            return;
        }
        footerHint.textContent = '保存中…';
        try {
            const res = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ changes }),
            });
            if (!res.ok) throw new Error('HTTP ' + res.status);
            footerHint.textContent = '已保存';
            originalConfig = JSON.parse(JSON.stringify(currentConfig));
            if (restart) {
                footerHint.textContent = '已保存，正在重启…';
                await fetch('/api/restart-server', { method: 'POST' });
                setTimeout(() => location.reload(), 3000);
            } else {
                setTimeout(() => (footerHint.textContent = ''), 2000);
            }
        } catch (e) {
            footerHint.textContent = '保存失败: ' + e;
        }
    }

    // ---------- Tab ----------

    tabsEl?.addEventListener('click', (e) => {
        const btn = e.target.closest('.settings-tab');
        if (!btn) return;
        currentTab = btn.dataset.tab;
        tabsEl.querySelectorAll('.settings-tab').forEach((t) => {
            t.classList.toggle('active', t.dataset.tab === currentTab);
        });
        render();
    });

    // ---------- Global listeners ----------

    openBtn.addEventListener('click', openDrawer);
    closeBtn?.addEventListener('click', closeDrawer);
    backdrop?.addEventListener('click', closeDrawer);
    cancelBtn?.addEventListener('click', closeDrawer);
    saveBtn?.addEventListener('click', () => save(false));
    saveRestartBtn?.addEventListener('click', () => save(true));

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && drawer.classList.contains('visible')) {
            closeDrawer();
        }
    });

    // ---------- Instance-level controls (permission + MCP) ----------

    async function loadPermissionState() {
        try {
            const res = await fetch(`/api/instances/${currentInstance}/config`);
            if (!res.ok) return;
            const data = await res.json();
            const mode = data.merged_config?.permission_mode || 'bypassPermissions';
            body.querySelectorAll('.permission-option').forEach((el) => {
                const isActive = el.dataset.permValue === mode;
                el.classList.toggle('active', isActive);
                const radio = el.querySelector('input[type="radio"]');
                if (radio) radio.checked = isActive;
            });
        } catch (e) {
            console.warn('加载权限状态失败:', e);
        }
    }

    async function setPermissionMode(mode) {
        try {
            const res = await fetch(`/api/instances/${currentInstance}/permission-mode`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mode }),
            });
            if (!res.ok) throw new Error('HTTP ' + res.status);
            body.querySelectorAll('.permission-option').forEach((el) => {
                const isActive = el.dataset.permValue === mode;
                el.classList.toggle('active', isActive);
                const radio = el.querySelector('input[type="radio"]');
                if (radio) radio.checked = isActive;
            });
            // 同步 Header 的 Permission 按钮标签
            const label = document.getElementById('permissionLabel');
            if (label) {
                const m = PERMISSION_MODES.find((p) => p.value === mode);
                if (m) label.textContent = m.name;
            }
            footerHint.textContent = `权限已切换为 ${mode}`;
            setTimeout(() => (footerHint.textContent = ''), 2000);
        } catch (e) {
            footerHint.textContent = '切换权限失败: ' + e;
        }
    }

    async function loadMcpList() {
        const container = body.querySelector('#mcpServerList');
        if (!container) return;
        try {
            const res = await fetch(`/api/instances/${currentInstance}/mcp-status`);
            if (res.status === 404) {
                container.innerHTML = '<div class="settings-loading">（实例未启动 — 发送消息或切到频道 Tab 启动后再刷新）</div>';
                return;
            }
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const data = await res.json();
            const servers = data.mcp_status?.mcpServers || [];
            if (!servers.length) {
                container.innerHTML = '<div class="settings-loading">（此实例未配置 MCP server）</div>';
                return;
            }
            container.innerHTML = servers.map((s) => {
                const isOn = s.status === 'connected';
                const toolCount = (s.tools && s.tools.length) || 0;
                return `
                    <div class="mcp-server-row" data-mcp="${escapeAttr(s.name)}">
                        <div class="mcp-server-name">
                            <span class="mcp-server-status-dot ${isOn ? 'on' : 'off'}"></span>
                            <span>${escapeHTML(s.name)}</span>
                            <span style="color:var(--text-secondary);font-weight:400;font-size:12.5px">
                                ${escapeHTML(s.status || 'unknown')}${toolCount ? ` · ${toolCount} tools` : ''}
                            </span>
                        </div>
                        <label class="switch">
                            <input type="checkbox" ${isOn ? 'checked' : ''} data-mcp-toggle="${escapeAttr(s.name)}">
                            <span class="slider"></span>
                        </label>
                    </div>
                `;
            }).join('');
            container.querySelectorAll('input[data-mcp-toggle]').forEach((input) => {
                input.addEventListener('change', async () => {
                    const name = input.dataset.mcpToggle;
                    const enabled = input.checked;
                    await toggleMcp(name, enabled);
                });
            });
        } catch (e) {
            container.innerHTML = `<div class="settings-error">加载 MCP 状态失败: ${escapeHTML(String(e))}</div>`;
        }
    }

    // ---- 子进程环境探测 ----

    async function loadSubprocInfo(forceRefresh) {
        const container = body.querySelector('#subprocInfo');
        const ageEl = body.querySelector('#subprocInfoAge');
        const refreshBtn = body.querySelector('#subprocRefreshBtn');
        if (!container) return;
        if (forceRefresh) {
            container.innerHTML = '<div class="settings-loading">探测中（docker exec 可能需 1-2 秒）…</div>';
            if (refreshBtn) { refreshBtn.disabled = true; refreshBtn.textContent = '探测中…'; }
        }
        try {
            const url = forceRefresh ? '/api/subprocess-info?refresh=true' : '/api/subprocess-info';
            const res = await fetch(url);
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const data = await res.json();
            renderSubprocInfo(container, data);
            if (ageEl) {
                if (data.cached) ageEl.textContent = `缓存 ${data.age_seconds}s 前`;
                else ageEl.textContent = '刚刚探测';
            }
        } catch (e) {
            container.innerHTML = `<div class="settings-error">加载失败: ${escapeHTML(String(e))}</div>`;
        } finally {
            if (refreshBtn) { refreshBtn.disabled = false; refreshBtn.textContent = '刷新'; }
        }
    }

    function renderSubprocInfo(container, data) {
        const c = data.container || {};
        const cli = data.cli || {};
        const settings = data.settings || {};
        const oauth = data.oauth || {};
        const host = data.host || {};
        const skills = data.skills || [];
        const mcps = data.mcp_servers || [];

        const containerStatus = c.running
            ? `<span class="proc-badge proc-ok">● ${escapeHTML(c.status || 'running')}</span>`
            : `<span class="proc-badge proc-down">● ${escapeHTML(c.status || 'stopped')}</span>`;

        const oauthStatus = oauth.container_creds || oauth.host_env
            ? `<span class="proc-badge proc-ok">● 已配置</span>`
            : `<span class="proc-badge proc-warn">● 未检测到</span>`;

        const hooks = (settings.hooks && settings.hooks.length)
            ? settings.hooks.map((h) => `<code>${escapeHTML(h)}</code>`).join(' ')
            : '<span style="color:var(--text-secondary)">无</span>';

        const skillsHtml = skills.length
            ? skills.map((s) => `<code>${escapeHTML(s)}</code>`).join(' ')
            : '<span style="color:var(--text-secondary)">无</span>';

        const mcpsHtml = mcps.length
            ? mcps.map((s) => `<code>${escapeHTML(s)}</code>`).join(' ')
            : '<span style="color:var(--text-secondary)">无</span>';

        container.innerHTML = `
            <div class="proc-info-grid">
                <div class="proc-info-group">
                    <div class="proc-info-group-title">子进程容器</div>
                    <div class="proc-info-row"><span>名称</span><code>${escapeHTML(c.name || '—')}</code></div>
                    <div class="proc-info-row"><span>状态</span>${containerStatus}</div>
                    ${c.image ? `<div class="proc-info-row"><span>镜像</span><code style="font-size:11px">${escapeHTML(c.image)}</code></div>` : ''}
                    ${c.started_at ? `<div class="proc-info-row"><span>启动时间</span><span style="font-size:12px;color:var(--text-secondary)">${escapeHTML(c.started_at.substring(0, 19).replace('T', ' '))}</span></div>` : ''}
                    ${cli.version ? `<div class="proc-info-row"><span>Claude CLI</span><code>v${escapeHTML(cli.version)}</code></div>` : (cli.error ? `<div class="proc-info-row"><span>Claude CLI</span><span style="color:#b36a6a">${escapeHTML(cli.error)}</span></div>` : '')}
                    ${settings.model ? `<div class="proc-info-row"><span>模型</span><code>${escapeHTML(settings.model)}</code></div>` : ''}
                    ${settings.permission_mode ? `<div class="proc-info-row"><span>权限模式</span><code>${escapeHTML(settings.permission_mode)}</code></div>` : ''}
                    <div class="proc-info-row"><span>OAuth</span>${oauthStatus}</div>
                    <div class="proc-info-row"><span>Stop Hooks</span><div class="proc-chip-group">${hooks}</div></div>
                    <div class="proc-info-row"><span>MCP Servers</span><div class="proc-chip-group">${mcpsHtml}</div></div>
                    <div class="proc-info-row"><span>Skills</span><div class="proc-chip-group">${skillsHtml}</div></div>
                </div>
                <div class="proc-info-group">
                    <div class="proc-info-group-title">宿主环境</div>
                    <div class="proc-info-row"><span>Python</span><code>${escapeHTML(host.python || '—')}</code></div>
                    <div class="proc-info-row"><span>平台</span><code>${escapeHTML(host.platform || '—')}</code></div>
                    <div class="proc-info-row"><span>Claude Agent SDK</span><code>${host.claude_agent_sdk ? escapeHTML(host.claude_agent_sdk) : '<span style="color:#b36a6a">未安装</span>'}</code></div>
                    <div class="proc-info-row"><span>FastAPI</span><code>${host.fastapi ? escapeHTML(host.fastapi) : '—'}</code></div>
                    <div class="proc-info-row"><span>MCP SDK</span><code>${host.mcp ? escapeHTML(host.mcp) : '—'}</code></div>
                    <div class="proc-info-row"><span>Uvicorn</span><code>${host.uvicorn ? escapeHTML(host.uvicorn) : '—'}</code></div>
                    <div class="proc-info-row"><span>sqlite-vec</span><code>${host.sqlite_vec ? escapeHTML(host.sqlite_vec) : '<span style="color:var(--text-secondary)">未安装</span>'}</code></div>
                    <div class="proc-info-row"><span>llama-cpp-python</span><code>${host.llama_cpp_python ? escapeHTML(host.llama_cpp_python) : '<span style="color:var(--text-secondary)">未安装</span>'}</code></div>
                </div>
            </div>
        `;
    }

    async function toggleMcp(name, enabled) {
        try {
            const res = await fetch(`/api/instances/${currentInstance}/mcp-toggle`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ server_name: name, enabled }),
            });
            if (!res.ok) throw new Error('HTTP ' + res.status);
            footerHint.textContent = `${name} ${enabled ? '已启用' : '已禁用'}（变更将在当前消息处理完成后生效）`;
            setTimeout(() => (footerHint.textContent = ''), 3000);
            // 视觉反馈
            const row = body.querySelector(`.mcp-server-row[data-mcp="${CSS.escape(name)}"]`);
            const dot = row?.querySelector('.mcp-server-status-dot');
            if (dot) {
                dot.classList.toggle('on', enabled);
                dot.classList.toggle('off', !enabled);
            }
        } catch (e) {
            footerHint.textContent = 'MCP 切换失败: ' + e;
        }
    }

    // ---------- Utils ----------

    function setByPath(obj, path, value) {
        let node = obj;
        for (let i = 0; i < path.length - 1; i++) {
            const k = path[i];
            if (!(k in node) || typeof node[k] !== 'object' || node[k] === null) node[k] = {};
            node = node[k];
        }
        node[path[path.length - 1]] = value;
    }

    function escapeHTML(s) {
        return String(s).replace(/[&<>"']/g, (c) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[c]));
    }

    function escapeAttr(s) {
        return String(s).replace(/"/g, '&quot;');
    }
})();
