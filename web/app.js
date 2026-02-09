/**
 * Claude Agent Chat - Frontend Application (WebSocket Version)
 * 支持多实例、图片上传、打字机效果、消息编辑、虚拟滚动
 * Round 5: Typewriter effect, Message editing, Enhanced drag & drop, i18n, Virtual scrolling
 */

(function () {
    'use strict';

    // ============================================
    // Configuration
    // ============================================
    // 从 URL 参数获取 instance，默认 ws-default
    function getCurrentInstance() {
        const params = new URLSearchParams(window.location.search);
        return params.get('instance') || 'ws-default';
    }
    let currentInstance = getCurrentInstance();

    // Typewriter effect settings
    const TYPEWRITER_CONFIG = {
        enabled: true,
        charDelay: 8,      // ms between characters
        wordMode: true,     // type word by word instead of char by char
        wordDelay: 20,      // ms between words (if wordMode is true)
        skipMarkdown: true, // render markdown after completion for complex blocks
        maxQueueSize: 100   // max pending characters before batch render
    };

    // Virtual scrolling settings
    const VIRTUAL_SCROLL_CONFIG = {
        enabled: true,
        threshold: 100,     // number of messages before enabling
        itemHeight: 150,    // estimated average message height
        bufferSize: 5,      // number of items to render outside viewport
        recyclePool: 20     // max number of recycled DOM elements
    };

    function getWsUrl() {
        return `ws://${window.location.host}/ws/chat?instance=${currentInstance}`;
    }

    // ============================================
    // Session Message Loading (服务端为唯一 truth)
    // ============================================
    async function loadCurrentSessionMessages() {
        /**
         * 从服务端加载当前 session 的消息历史并显示。
         * 返回 true 表示加载了消息，false 表示无消息（显示 welcome）。
         */
        try {
            const response = await fetch('/api/claude-sessions');
            const data = await response.json();

            if (data.sessions) {
                renderClaudeSessions(data.sessions);
            }

            const sessionId = data.current_session;
            if (!sessionId) {
                showWelcomeMessage();
                return false;
            }

            currentClaudeSessionId = sessionId;

            // 加载该 session 的消息
            const msgResponse = await fetch(`/api/claude-sessions/${sessionId}/messages`);
            const msgData = await msgResponse.json();

            if (!msgData.messages || msgData.messages.length === 0) {
                showWelcomeMessage();
                return false;
            }

            // 隐藏欢迎消息
            if (elements.welcomeMessage) {
                elements.welcomeMessage.classList.add('hidden');
            }

            elements.messagesWrapper.innerHTML = '';
            state.messages = [];

            msgData.messages.forEach(msg => {
                const type = msg.role === 'user' ? 'user' : 'assistant';
                const messageEl = createMessageElement(type, msg.content);
                elements.messagesWrapper.appendChild(messageEl);
                state.messages.push({ type, content: msg.content });
            });

            scrollToBottom();
            console.log(`Loaded ${msgData.messages.length} messages from server (session: ${sessionId.slice(0, 8)}...)`);
            return true;
        } catch (error) {
            console.error('Failed to load current session messages:', error);
            showWelcomeMessage();
            return false;
        }
    }

    // ============================================
    // DOM Elements
    // ============================================
    const elements = {
        messagesContainer: document.getElementById('messagesContainer'),
        messagesWrapper: document.getElementById('messagesWrapper'),
        welcomeMessage: document.getElementById('welcomeMessage'),
        messageInput: document.getElementById('messageInput'),
        sendBtn: document.getElementById('sendBtn'),
        newChatBtn: document.getElementById('newChatBtn'),
        inputContainer: document.querySelector('.input-container'),
        attachBtn: document.getElementById('attachBtn'),
        fileInput: document.getElementById('fileInput'),
        attachmentPreview: document.getElementById('attachmentPreview'),
        sessionsList: document.getElementById('sessionsList'),
        taskBar: document.getElementById('taskBar'),
        taskItems: document.getElementById('taskItems'),
        roleName: document.getElementById('roleName'),
        roleStatus: document.getElementById('roleStatus')
    };

    // ============================================
    // State
    // ============================================
    let state = {
        isLoading: false,
        messages: [],
        ws: null,
        currentMessageEl: null,
        currentContentEl: null,
        toolsContainer: null,
        textContainer: null,
        fullContent: '',
        attachments: [],  // Store pending attachments
        tasks: [],  // Active tasks list
        bookmarks: [],  // Bookmarked messages
        searchResults: [],  // Search results indices
        currentSearchIndex: -1,  // Current search result position
        searchQuery: '',  // Current search query
        // Typewriter state
        typewriterQueue: [],
        typewriterTimer: null,
        typewriterBuffer: '',
        isTypewriting: false,
        // Virtual scroll state
        virtualScroll: {
            enabled: false,
            scrollTop: 0,
            containerHeight: 0,
            totalHeight: 0,
            visibleStart: 0,
            visibleEnd: 0,
            itemHeights: [],
            recycledNodes: []
        },
        // Message edit state
        editingMessageIndex: -1,
        editingOriginalContent: ''
    };

    const BOOKMARKS_KEY = 'jarvis_bookmarks';

    // ============================================
    // Typewriter Effect Engine
    // ============================================
    class TypewriterEngine {
        constructor(container, config = TYPEWRITER_CONFIG) {
            this.container = container;
            this.config = config;
            this.buffer = '';
            this.displayedText = '';
            this.timer = null;
            this.isRunning = false;
            this.onComplete = null;
            this.renderCallback = null;
        }

        start(renderCallback, onComplete) {
            this.renderCallback = renderCallback;
            this.onComplete = onComplete;
            this.isRunning = true;
            this.buffer = '';
            this.displayedText = '';
            this.processQueue();
        }

        append(text) {
            this.buffer += text;
            if (!this.isRunning) {
                this.isRunning = true;
                this.processQueue();
            }
        }

        processQueue() {
            if (!this.isRunning) return;

            if (this.buffer.length === 0) {
                // Wait for more content
                this.timer = setTimeout(() => this.processQueue(), 50);
                return;
            }

            if (this.config.wordMode) {
                // Word by word mode
                const match = this.buffer.match(/^(\S+\s*|\s+)/);
                if (match) {
                    const chunk = match[1];
                    this.displayedText += chunk;
                    this.buffer = this.buffer.slice(chunk.length);
                    this.render();
                    this.timer = setTimeout(() => this.processQueue(), this.config.wordDelay);
                } else {
                    this.timer = setTimeout(() => this.processQueue(), 50);
                }
            } else {
                // Character by character mode
                const char = this.buffer[0];
                this.displayedText += char;
                this.buffer = this.buffer.slice(1);
                this.render();
                this.timer = setTimeout(() => this.processQueue(), this.config.charDelay);
            }
        }

        render() {
            if (this.renderCallback) {
                this.renderCallback(this.displayedText);
            }
        }

        complete() {
            this.isRunning = false;
            if (this.timer) {
                clearTimeout(this.timer);
                this.timer = null;
            }
            // Flush remaining buffer
            if (this.buffer.length > 0) {
                this.displayedText += this.buffer;
                this.buffer = '';
                this.render();
            }
            if (this.onComplete) {
                this.onComplete(this.displayedText);
            }
        }

        stop() {
            this.isRunning = false;
            if (this.timer) {
                clearTimeout(this.timer);
                this.timer = null;
            }
        }

        getDisplayedText() {
            return this.displayedText;
        }

        getFullText() {
            return this.displayedText + this.buffer;
        }
    }

    // Current typewriter instance
    let currentTypewriter = null;

    // ============================================
    // Virtual Scroll Manager
    // ============================================
    class VirtualScrollManager {
        constructor(container, wrapper, config = VIRTUAL_SCROLL_CONFIG) {
            this.container = container;
            this.wrapper = wrapper;
            this.config = config;
            this.items = [];
            this.itemHeights = new Map();
            this.enabled = false;
            this.scrollHandler = this.handleScroll.bind(this);
            this.resizeObserver = null;
            this.spacerTop = null;
            this.spacerBottom = null;
            this.visibleRange = { start: 0, end: 0 };
        }

        init() {
            if (!this.config.enabled) return;

            // Create spacer elements
            this.spacerTop = document.createElement('div');
            this.spacerTop.className = 'virtual-scroll-spacer-top';
            this.spacerBottom = document.createElement('div');
            this.spacerBottom.className = 'virtual-scroll-spacer-bottom';

            // Setup scroll listener
            this.container.addEventListener('scroll', this.scrollHandler, { passive: true });

            // Setup resize observer
            this.resizeObserver = new ResizeObserver(() => this.recalculate());
            this.resizeObserver.observe(this.container);
        }

        setItems(items) {
            this.items = items;
            this.checkShouldEnable();
        }

        addItem(item, height = this.config.itemHeight) {
            this.items.push(item);
            this.itemHeights.set(this.items.length - 1, height);
            this.checkShouldEnable();
        }

        checkShouldEnable() {
            const shouldEnable = this.items.length > this.config.threshold;
            if (shouldEnable !== this.enabled) {
                this.enabled = shouldEnable;
                if (shouldEnable) {
                    this.enable();
                } else {
                    this.disable();
                }
            }
        }

        enable() {
            console.log('Virtual scroll enabled for', this.items.length, 'items');
            this.wrapper.classList.add('virtual-scroll-enabled');
            this.recalculate();
        }

        disable() {
            this.wrapper.classList.remove('virtual-scroll-enabled');
            this.spacerTop?.remove();
            this.spacerBottom?.remove();
        }

        handleScroll() {
            if (!this.enabled) return;
            requestAnimationFrame(() => this.render());
        }

        recalculate() {
            if (!this.enabled) return;

            const containerHeight = this.container.clientHeight;
            const scrollTop = this.container.scrollTop;

            let totalHeight = 0;
            const positions = [];

            for (let i = 0; i < this.items.length; i++) {
                const height = this.itemHeights.get(i) || this.config.itemHeight;
                positions.push({ top: totalHeight, height });
                totalHeight += height;
            }

            this.positions = positions;
            this.totalHeight = totalHeight;
            this.render();
        }

        render() {
            if (!this.enabled || !this.positions) return;

            const scrollTop = this.container.scrollTop;
            const containerHeight = this.container.clientHeight;
            const buffer = this.config.bufferSize * this.config.itemHeight;

            // Find visible range
            let start = 0;
            let end = this.items.length;

            for (let i = 0; i < this.positions.length; i++) {
                if (this.positions[i].top + this.positions[i].height < scrollTop - buffer) {
                    start = i + 1;
                }
                if (this.positions[i].top > scrollTop + containerHeight + buffer) {
                    end = i;
                    break;
                }
            }

            if (start !== this.visibleRange.start || end !== this.visibleRange.end) {
                this.visibleRange = { start, end };
                this.updateVisibleItems();
            }
        }

        updateVisibleItems() {
            // Update spacers
            if (this.spacerTop && this.positions && this.positions[this.visibleRange.start]) {
                this.spacerTop.style.height = this.positions[this.visibleRange.start].top + 'px';
            }

            if (this.spacerBottom && this.positions) {
                const lastVisible = this.positions[this.visibleRange.end - 1];
                const bottomSpace = lastVisible
                    ? this.totalHeight - (lastVisible.top + lastVisible.height)
                    : 0;
                this.spacerBottom.style.height = Math.max(0, bottomSpace) + 'px';
            }

            // Dispatch event for message visibility update
            window.dispatchEvent(new CustomEvent('virtualscroll:update', {
                detail: this.visibleRange
            }));
        }

        updateItemHeight(index, height) {
            this.itemHeights.set(index, height);
            this.recalculate();
        }

        destroy() {
            this.container.removeEventListener('scroll', this.scrollHandler);
            this.resizeObserver?.disconnect();
            this.disable();
        }
    }

    let virtualScrollManager = null;

    // ============================================
    // SVG Icons
    // ============================================
    const icons = {
        user: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
            <circle cx="12" cy="7" r="4"></circle>
        </svg>`,
        assistant: `<svg width="28" height="28" viewBox="0 0 16 16" fill="#D97757">
            <path d="m3.127 10.604 3.135-1.76.053-.153-.053-.085H6.11l-.525-.032-1.791-.048-1.554-.065-1.505-.08-.38-.081L0 7.832l.036-.234.32-.214.455.04 1.009.069 1.513.105 1.097.064 1.626.17h.259l.036-.105-.089-.065-.068-.064-1.566-1.062-1.695-1.121-.887-.646-.48-.327-.243-.306-.104-.67.435-.48.585.04.15.04.593.456 1.267.981 1.654 1.218.242.202.097-.068.012-.049-.109-.181-.9-1.626-.96-1.655-.428-.686-.113-.411a2 2 0 0 1-.068-.484l.496-.674L4.446 0l.662.089.279.242.411.94.666 1.48 1.033 2.014.302.597.162.553.06.17h.105v-.097l.085-1.134.157-1.392.154-1.792.052-.504.25-.605.497-.327.387.186.319.456-.045.294-.19 1.23-.37 1.93-.243 1.29h.142l.161-.16.654-.868 1.097-1.372.484-.545.565-.601.363-.287h.686l.505.751-.226.775-.707.895-.585.759-.839 1.13-.524.904.048.072.125-.012 1.897-.403 1.024-.186 1.223-.21.553.258.06.263-.218.536-1.307.323-1.533.307-2.284.54-.028.02.032.04 1.029.098.44.024h1.077l2.005.15.525.346.315.424-.053.323-.807.411-3.631-.863-.872-.218h-.12v.073l.726.71 1.331 1.202 1.667 1.55.084.383-.214.302-.226-.032-1.464-1.101-.565-.497-1.28-1.077h-.084v.113l.295.432 1.557 2.34.08.718-.112.234-.404.141-.444-.08-.911-1.28-.94-1.44-.759-1.291-.093.053-.448 4.821-.21.246-.484.186-.403-.307-.214-.496.214-.98.258-1.28.21-1.016.19-1.263.112-.42-.008-.028-.092.012-.953 1.307-1.448 1.957-1.146 1.227-.274.109-.477-.247.045-.44.266-.39 1.586-2.018.956-1.25.617-.723-.004-.105h-.036l-4.212 2.736-.75.096-.324-.302.04-.496.154-.162 1.267-.871z"/>
        </svg>`,
        tool: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"></path>
        </svg>`,
        send: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="22" y1="2" x2="11" y2="13"></line>
            <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
        </svg>`,
        stop: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
        </svg>`
    };

    // ============================================
    // Markdown Configuration
    // ============================================
    if (typeof marked !== 'undefined') {
        marked.setOptions({
            breaks: true,
            gfm: true,
            highlight: function (code, lang) {
                if (typeof hljs !== 'undefined' && lang && hljs.getLanguage(lang)) {
                    try {
                        return hljs.highlight(code, { language: lang }).value;
                    } catch (e) { }
                }
                return code;
            }
        });
    }

    // ============================================
    // Utility Functions
    // ============================================
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function renderMarkdown(text) {
        if (typeof marked !== 'undefined') {
            return marked.parse(text);
        }
        return escapeHtml(text).replace(/\n/g, '<br>');
    }

    function scrollToBottom() {
        elements.messagesContainer.scrollTop = elements.messagesContainer.scrollHeight;
    }

    function setStatus(status, text) {
        // Update role indicator status
        if (elements.roleStatus) {
            elements.roleStatus.className = 'role-status';
            if (status === 'busy') elements.roleStatus.classList.add('busy');
            if (status === 'error') elements.roleStatus.classList.add('error');
        }
        if (elements.roleName) {
            // When idle/ready, show the instance name; otherwise show status text
            if (status === 'ready') {
                elements.roleName.textContent = currentInstance;
            } else {
                elements.roleName.textContent = text;
            }
        }
    }

    function autoResizeTextarea() {
        const textarea = elements.messageInput;
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
    }

    // ============================================
    // Claude Sessions Management
    // ============================================
    let currentClaudeSessionId = null;

    async function loadClaudeSessions() {
        try {
            const response = await fetch('/api/claude-sessions');
            const data = await response.json();
            if (data.sessions) {
                renderClaudeSessions(data.sessions);
                // 如果有当前激活的 session，标记它
                if (data.current_session) {
                    currentClaudeSessionId = data.current_session;
                }
            }
        } catch (error) {
            console.error('Failed to load Claude sessions:', error);
            if (elements.sessionsList) {
                elements.sessionsList.innerHTML = '<div class="sessions-error">Failed to load history</div>';
            }
        }
    }

    function renderClaudeSessions(sessions) {
        if (!elements.sessionsList) return;

        if (!sessions || sessions.length === 0) {
            elements.sessionsList.innerHTML = '<div class="sessions-empty">No history yet</div>';
            return;
        }

        const html = sessions.map(s => `
            <div class="session-item ${s.id === currentClaudeSessionId ? 'active' : ''}"
                 data-session-id="${s.id}"
                 onclick="window.switchClaudeSession('${s.id}')">
                <div class="session-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                    </svg>
                </div>
                <div class="session-info">
                    <div class="session-title">${escapeHtml(s.title || 'New Chat')}</div>
                    <div class="session-meta-row">
                        <span class="session-meta">${formatTime(s.modified)}</span>
                        <button class="session-delete-btn" onclick="event.stopPropagation(); window.deleteClaudeSession('${s.id}')" title="Delete">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="3 6 5 6 21 6"/>
                                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                            </svg>
                        </button>
                    </div>
                </div>
            </div>
        `).join('');

        elements.sessionsList.innerHTML = html;
    }

    window.switchClaudeSession = async function(sessionId) {
        if (sessionId === currentClaudeSessionId) return;

        try {
            setStatus('busy', 'Switching session...');
            _sessionChangeInitiatedLocally = true;

            // 调用后端 API 切换 session
            const response = await fetch(`/api/claude-sessions/${sessionId}/activate`, {
                method: 'PUT'
            });

            if (!response.ok) {
                _sessionChangeInitiatedLocally = false;
                throw new Error('Failed to switch session');
            }

            const result = await response.json();
            currentClaudeSessionId = sessionId;

            // 清空当前 UI
            elements.messagesWrapper.innerHTML = '';
            state.messages = [];

            // 加载 session 的消息历史
            const messagesResponse = await fetch(`/api/claude-sessions/${sessionId}/messages`);
            const messagesData = await messagesResponse.json();

            if (messagesData.messages && messagesData.messages.length > 0) {
                if (elements.welcomeMessage) {
                    elements.welcomeMessage.classList.add('hidden');
                }

                messagesData.messages.forEach(msg => {
                    const messageEl = createMessageElement(
                        msg.role === 'user' ? 'user' : 'assistant',
                        msg.content
                    );
                    elements.messagesWrapper.appendChild(messageEl);
                    state.messages.push({
                        type: msg.role === 'user' ? 'user' : 'assistant',
                        content: msg.content
                    });
                });
                scrollToBottom();
            } else {
                // 显示欢迎消息
                showWelcomeMessage();
            }

            // 更新列表显示
            await loadClaudeSessions();
            setStatus('ready', 'Ready');
            showToast('Session Loaded', 'Switched to selected conversation', 'success', 2000);
        } catch (error) {
            console.error('Failed to switch Claude session:', error);
            setStatus('error', 'Switch failed');
            showToast('Error', 'Failed to switch session', 'error');
        }
    };

    window.deleteClaudeSession = async function(sessionId) {
        // 确认删除
        if (!confirm('Delete this conversation?')) {
            return;
        }

        try {
            const response = await fetch(`/api/claude-sessions/${sessionId}`, {
                method: 'DELETE'
            });

            if (!response.ok) {
                throw new Error('Failed to delete session');
            }

            // 先从 DOM 中移除该项（立即响应）
            const itemEl = document.querySelector(`.session-item[data-session-id="${sessionId}"]`);
            if (itemEl) {
                itemEl.remove();
            }

            // 如果删除的是当前 session，清空界面
            if (sessionId === currentClaudeSessionId) {
                currentClaudeSessionId = null;
                elements.messagesWrapper.innerHTML = '';
                state.messages = [];
                showWelcomeMessage();
            }

            // 刷新列表（确保与服务器同步）
            await loadClaudeSessions();
            showToast('Deleted', 'Conversation deleted', 'success', 2000);
        } catch (error) {
            console.error('Failed to delete Claude session:', error);
            showToast('Error', 'Failed to delete conversation', 'error');
        }
    };

    let _sessionChangeInitiatedLocally = false;

    async function createNewClaudeSession() {
        try {
            setStatus('busy', 'Creating new session...');
            _sessionChangeInitiatedLocally = true;

            // 调用后端 API 创建新 session
            const response = await fetch('/api/claude-sessions/new', {
                method: 'POST'
            });

            if (!response.ok) {
                _sessionChangeInitiatedLocally = false;
                throw new Error('Failed to create new session');
            }

            const result = await response.json();
            currentClaudeSessionId = null; // 新 session 还没有 ID

            // 清空 UI
            elements.messagesWrapper.innerHTML = '';
            state.messages = [];
            showWelcomeMessage();

            // 清空附件
            state.attachments = [];
            renderAttachmentPreviews();

            // 更新列表
            await loadClaudeSessions();
            setStatus('ready', 'Ready');
            showToast('New Chat', 'Started a new conversation', 'success', 2000);
        } catch (error) {
            console.error('Failed to create new Claude session:', error);
            setStatus('error', 'Creation failed');
            showToast('Error', 'Failed to create new session', 'error');
        }
    }

    function showWelcomeMessage() {
        elements.messagesWrapper.innerHTML = `
            <div class="welcome-message" id="welcomeMessage">
                <div class="welcome-icon">
                    <svg width="56" height="56" viewBox="0 0 16 16" fill="#D97757">
                        <path d="m3.127 10.604 3.135-1.76.053-.153-.053-.085H6.11l-.525-.032-1.791-.048-1.554-.065-1.505-.08-.38-.081L0 7.832l.036-.234.32-.214.455.04 1.009.069 1.513.105 1.097.064 1.626.17h.259l.036-.105-.089-.065-.068-.064-1.566-1.062-1.695-1.121-.887-.646-.48-.327-.243-.306-.104-.67.435-.48.585.04.15.04.593.456 1.267.981 1.654 1.218.242.202.097-.068.012-.049-.109-.181-.9-1.626-.96-1.655-.428-.686-.113-.411a2 2 0 0 1-.068-.484l.496-.674L4.446 0l.662.089.279.242.411.94.666 1.48 1.033 2.014.302.597.162.553.06.17h.105v-.097l.085-1.134.157-1.392.154-1.792.052-.504.25-.605.497-.327.387.186.319.456-.045.294-.19 1.23-.37 1.93-.243 1.29h.142l.161-.16.654-.868 1.097-1.372.484-.545.565-.601.363-.287h.686l.505.751-.226.775-.707.895-.585.759-.839 1.13-.524.904.048.072.125-.012 1.897-.403 1.024-.186 1.223-.21.553.258.06.263-.218.536-1.307.323-1.533.307-2.284.54-.028.02.032.04 1.029.098.44.024h1.077l2.005.15.525.346.315.424-.053.323-.807.411-3.631-.863-.872-.218h-.12v.073l.726.71 1.331 1.202 1.667 1.55.084.383-.214.302-.226-.032-1.464-1.101-.565-.497-1.28-1.077h-.084v.113l.295.432 1.557 2.34.08.718-.112.234-.404.141-.444-.08-.911-1.28-.94-1.44-.759-1.291-.093.053-.448 4.821-.21.246-.484.186-.403-.307-.214-.496.214-.98.258-1.28.21-1.016.19-1.263.112-.42-.008-.028-.092.012-.953 1.307-1.448 1.957-1.146 1.227-.274.109-.477-.247.045-.44.266-.39 1.586-2.018.956-1.25.617-.723-.004-.105h-.036l-4.212 2.736-.75.096-.324-.302.04-.496.154-.162 1.267-.871z"/>
                    </svg>
                </div>
                <h2>Welcome</h2>
                <p>Start a conversation with your AI assistant</p>
            </div>
        `;
        // 更新元素引用，因为 innerHTML 覆盖后原引用失效
        elements.welcomeMessage = document.getElementById('welcomeMessage');
    }

    function formatTime(timestamp) {
        if (!timestamp) return '';
        // Handle both ISO string and Unix timestamp
        const date = typeof timestamp === 'number' ? new Date(timestamp * 1000) : new Date(timestamp);
        const now = new Date();
        const diffMs = now - date;
        const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

        if (diffDays === 0) {
            return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
        } else if (diffDays === 1) {
            return 'Yesterday';
        } else if (diffDays < 7) {
            return `${diffDays}d ago`;
        } else {
            return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        }
    }

    async function createNewSession() {
        await createNewClaudeSession();
    }

    // ============================================
    // Toast Notifications
    // ============================================
    const toastIcons = {
        success: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M20 6L9 17l-5-5"/>
        </svg>`,
        error: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <line x1="15" y1="9" x2="9" y2="15"/>
            <line x1="9" y1="9" x2="15" y2="15"/>
        </svg>`,
        warning: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
            <line x1="12" y1="9" x2="12" y2="13"/>
            <line x1="12" y1="17" x2="12.01" y2="17"/>
        </svg>`,
        info: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <line x1="12" y1="16" x2="12" y2="12"/>
            <line x1="12" y1="8" x2="12.01" y2="8"/>
        </svg>`
    };

    function showToast(title, message, type = 'info', duration = 4000) {
        const container = document.getElementById('toastContainer');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = `
            <div class="toast-icon">${toastIcons[type] || toastIcons.info}</div>
            <div class="toast-content">
                <div class="toast-title">${escapeHtml(title)}</div>
                ${message ? `<div class="toast-message">${escapeHtml(message)}</div>` : ''}
            </div>
            <button class="toast-close">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="18" y1="6" x2="6" y2="18"/>
                    <line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
            </button>
        `;

        toast.querySelector('.toast-close').addEventListener('click', () => {
            toast.classList.add('hiding');
            setTimeout(() => toast.remove(), 300);
        });

        container.appendChild(toast);

        if (duration > 0) {
            setTimeout(() => {
                if (toast.parentNode) {
                    toast.classList.add('hiding');
                    setTimeout(() => toast.remove(), 300);
                }
            }, duration);
        }
    }

    // ============================================
    // Task Management
    // ============================================
    async function loadTasks(showRefreshFeedback = false) {
        const refreshBtn = document.getElementById('taskRefreshBtn');
        if (refreshBtn && showRefreshFeedback) {
            refreshBtn.classList.add('refreshing');
        }

        try {
            const response = await fetch('/task/list');
            const data = await response.json();
            state.tasks = data.tasks || [];
            renderTasks();
        } catch (error) {
            console.error('Failed to load tasks:', error);
        } finally {
            if (refreshBtn && showRefreshFeedback) {
                setTimeout(() => refreshBtn.classList.remove('refreshing'), 500);
            }
        }
    }

    function renderTasks() {
        if (!elements.taskItems) return;

        if (state.tasks.length === 0) {
            elements.taskBar.classList.remove('active');
            elements.taskItems.innerHTML = '';
            return;
        }

        elements.taskBar.classList.add('active');
        elements.taskItems.innerHTML = state.tasks.map(task => {
            const statusIcon = getStatusIcon(task.status);
            const progress = task.total_steps > 0 ? (task.progress || 0) : 0;
            const percent = task.total_steps > 0 ? Math.round((progress / task.total_steps) * 100) : 0;
            const progressText = task.total_steps > 0 ? `${progress}/${task.total_steps}` : '';
            const elapsed = formatElapsedTime(task.registered_at);
            const remainingTime = formatRemainingTime(task.expires_at);

            return `
                <div class="task-item ${task.status}" data-task-id="${escapeHtml(task.task_id)}">
                    <span class="task-status-icon">${statusIcon}</span>
                    <span class="task-id">${escapeHtml(task.task_id)}</span>
                    ${task.description ? `<span class="task-desc">${escapeHtml(task.description)}</span>` : ''}
                    ${task.total_steps > 0 ? `
                        <div class="task-progress-bar">
                            <div class="task-progress-fill" style="width: ${percent}%"></div>
                        </div>
                        <span class="task-percent">${percent}%</span>
                    ` : ''}
                    ${progressText ? `<span class="task-progress">${progressText}</span>` : ''}
                    ${task.current_step ? `<span class="task-step">${escapeHtml(task.current_step)}</span>` : ''}
                    ${elapsed ? `<span class="task-elapsed">${elapsed}</span>` : ''}
                    ${remainingTime ? `<span class="task-time">${remainingTime}</span>` : ''}
                </div>
            `;
        }).join('');
    }

    function getStatusIcon(status) {
        switch (status) {
            case 'running':
                return `<svg class="spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 12a9 9 0 11-6.219-8.56"/>
                </svg>`;
            case 'done':
                return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M20 6L9 17l-5-5"/>
                </svg>`;
            case 'blocked':
                return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"/>
                    <line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/>
                </svg>`;
            case 'timeout':
                return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"/>
                    <polyline points="12 6 12 12 16 14"/>
                </svg>`;
            default:
                return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"/>
                </svg>`;
        }
    }

    function formatElapsedTime(registeredAt) {
        if (!registeredAt) return '';
        const elapsed = Date.now() - registeredAt * 1000;
        if (elapsed < 0) return '';

        const seconds = Math.floor(elapsed / 1000);
        if (seconds < 60) return `${seconds}s`;
        const minutes = Math.floor(seconds / 60);
        if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
        const hours = Math.floor(minutes / 60);
        return `${hours}h ${minutes % 60}m`;
    }

    function formatRemainingTime(expiresAt) {
        if (!expiresAt) return '';
        const remaining = expiresAt * 1000 - Date.now();
        if (remaining <= 0) return 'Expired';

        const minutes = Math.floor(remaining / 60000);
        if (minutes < 1) return '<1m';
        if (minutes < 60) return `${minutes}m`;
        const hours = Math.floor(minutes / 60);
        return `${hours}h ${minutes % 60}m`;
    }

    function handleTaskUpdate(data) {
        console.log('Task update:', data.event, data.task);

        const prevTasks = [...state.tasks];

        if (data.all_tasks) {
            state.tasks = data.all_tasks;
        } else if (data.task) {
            const index = state.tasks.findIndex(t => t.task_id === data.task.task_id);
            if (index >= 0) {
                if (data.event === 'removed' || data.event === 'completed') {
                    state.tasks.splice(index, 1);
                } else {
                    state.tasks[index] = data.task;
                }
            } else if (data.event === 'registered') {
                state.tasks.push(data.task);
            }
        }

        renderTasks();

        // Show notifications for task events
        if (data.task && data.event) {
            const taskId = data.task.task_id;
            const desc = data.task.description || taskId;

            switch (data.event) {
                case 'completed':
                    showToast('Task Completed', desc, 'success');
                    break;
                case 'blocked':
                    showToast('Task Blocked', `${desc}: ${data.task.block_reason || 'Unknown reason'}`, 'warning');
                    break;
                case 'timeout':
                    showToast('Task Timeout', desc, 'error');
                    break;
                case 'registered':
                    showToast('Task Started', desc, 'info', 2000);
                    break;
            }
        }
    }

    function handleTaskRefresh() {
        loadTasks(true);
    }

    // ============================================
    // Attachment Handling
    // ============================================

    // SVG icons for file types
    const fileIcons = {
        image: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
            <circle cx="8.5" cy="8.5" r="1.5"/>
            <polyline points="21 15 16 10 5 21"/>
        </svg>`,
        document: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
            <line x1="16" y1="13" x2="8" y2="13"/>
            <line x1="16" y1="17" x2="8" y2="17"/>
        </svg>`,
        text: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
            <line x1="16" y1="13" x2="8" y2="13"/>
            <line x1="16" y1="17" x2="8" y2="17"/>
            <line x1="10" y1="9" x2="8" y2="9"/>
        </svg>`,
        code: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="16 18 22 12 16 6"/>
            <polyline points="8 6 2 12 8 18"/>
        </svg>`,
        data: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <ellipse cx="12" cy="5" rx="9" ry="3"/>
            <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/>
            <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
        </svg>`,
        web: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <line x1="2" y1="12" x2="22" y2="12"/>
            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
        </svg>`,
        style: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="13.5" cy="6.5" r="2.5"/>
            <circle cx="17.5" cy="10.5" r="2.5"/>
            <circle cx="8.5" cy="7.5" r="2.5"/>
            <circle cx="6.5" cy="12.5" r="2.5"/>
            <path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.555C21.965 6.012 17.461 2 12 2z"/>
        </svg>`,
        config: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </svg>`
    };

    // Supported file types with SVG icons
    const SUPPORTED_TYPES = {
        // Images
        'image/jpeg': { type: 'image', iconType: 'image' },
        'image/png': { type: 'image', iconType: 'image' },
        'image/gif': { type: 'image', iconType: 'image' },
        'image/webp': { type: 'image', iconType: 'image' },
        // Documents (PDF)
        'application/pdf': { type: 'document', iconType: 'document' },
        // Text files
        'text/plain': { type: 'text_file', iconType: 'text' },
        'text/markdown': { type: 'text_file', iconType: 'text' },
        'text/csv': { type: 'text_file', iconType: 'data' },
        'application/json': { type: 'text_file', iconType: 'config' },
        'text/html': { type: 'text_file', iconType: 'web' },
        'text/css': { type: 'text_file', iconType: 'style' },
        'text/javascript': { type: 'text_file', iconType: 'code' },
        'application/javascript': { type: 'text_file', iconType: 'code' },
        // Common code files (may be detected as octet-stream)
        'application/xml': { type: 'text_file', iconType: 'config' },
        'text/xml': { type: 'text_file', iconType: 'config' }
    };

    function getFileIconSvg(iconType) {
        return fileIcons[iconType] || fileIcons.text;
    }

    // Text file extensions for fallback detection
    const TEXT_EXTENSIONS = [
        '.txt', '.md', '.markdown', '.json', '.csv', '.html', '.htm',
        '.css', '.js', '.ts', '.jsx', '.tsx', '.py', '.java', '.c',
        '.cpp', '.h', '.hpp', '.go', '.rs', '.rb', '.php', '.sql',
        '.yaml', '.yml', '.xml', '.ini', '.cfg', '.conf', '.log',
        '.sh', '.bash', '.zsh', '.ps1', '.bat', '.cmd'
    ];

    function handleAttachClick() {
        elements.fileInput.click();
    }

    function handleFileSelect(e) {
        const files = e.target.files;
        if (files.length > 0) {
            handleFiles(files);
        }
        // Reset input so same file can be selected again
        e.target.value = '';
    }

    function getFileType(file) {
        // Check MIME type first
        if (SUPPORTED_TYPES[file.type]) {
            return SUPPORTED_TYPES[file.type];
        }

        // Fallback: check extension for text files
        const fileName = file.name.toLowerCase();

        // Check for code files
        const codeExtensions = ['.js', '.ts', '.jsx', '.tsx', '.py', '.java', '.c', '.cpp', '.h', '.hpp', '.go', '.rs', '.rb', '.php', '.sh', '.bash', '.zsh', '.ps1', '.bat', '.cmd'];
        for (const ext of codeExtensions) {
            if (fileName.endsWith(ext)) {
                return { type: 'text_file', iconType: 'code' };
            }
        }

        // Check for config files
        const configExtensions = ['.json', '.yaml', '.yml', '.xml', '.ini', '.cfg', '.conf'];
        for (const ext of configExtensions) {
            if (fileName.endsWith(ext)) {
                return { type: 'text_file', iconType: 'config' };
            }
        }

        // Check for data files
        if (fileName.endsWith('.csv')) {
            return { type: 'text_file', iconType: 'data' };
        }

        // Check for web files
        if (fileName.endsWith('.html') || fileName.endsWith('.htm')) {
            return { type: 'text_file', iconType: 'web' };
        }

        // Check for style files
        if (fileName.endsWith('.css') || fileName.endsWith('.scss') || fileName.endsWith('.sass') || fileName.endsWith('.less')) {
            return { type: 'text_file', iconType: 'style' };
        }

        // General text file check
        for (const ext of TEXT_EXTENSIONS) {
            if (fileName.endsWith(ext)) {
                return { type: 'text_file', iconType: 'text' };
            }
        }

        // PDF fallback
        if (fileName.endsWith('.pdf')) {
            return { type: 'document', iconType: 'document' };
        }

        return null;
    }

    function handleFiles(files) {
        Array.from(files).forEach(file => {
            const fileTypeInfo = getFileType(file);

            if (!fileTypeInfo) {
                console.warn(`Unsupported file type: ${file.type} (${file.name})`);
                showToast('Unsupported File', `File type not supported: ${file.name}`, 'error');
                return;
            }

            if (fileTypeInfo.type === 'image') {
                // Handle images with base64 encoding
                const reader = new FileReader();
                reader.onload = function (e) {
                    const base64Data = e.target.result.split(',')[1];
                    const attachment = {
                        type: 'image',
                        media_type: file.type,
                        data: base64Data,
                        preview: e.target.result,
                        name: file.name,
                        iconType: fileTypeInfo.iconType
                    };
                    state.attachments.push(attachment);
                    renderAttachmentPreviews();
                    updateButtonState();
                };
                reader.readAsDataURL(file);
            } else if (fileTypeInfo.type === 'document') {
                // Handle PDF and other documents with base64 encoding
                const reader = new FileReader();
                reader.onload = function (e) {
                    const base64Data = e.target.result.split(',')[1];
                    const attachment = {
                        type: 'document',
                        media_type: file.type || 'application/pdf',
                        data: base64Data,
                        name: file.name,
                        iconType: fileTypeInfo.iconType,
                        size: formatFileSize(file.size)
                    };
                    state.attachments.push(attachment);
                    renderAttachmentPreviews();
                    updateButtonState();
                };
                reader.readAsDataURL(file);
            } else if (fileTypeInfo.type === 'text_file') {
                // Handle text files - read as text
                const reader = new FileReader();
                reader.onload = function (e) {
                    const content = e.target.result;
                    const attachment = {
                        type: 'text_file',
                        content: content,
                        name: file.name,
                        iconType: fileTypeInfo.iconType,
                        size: formatFileSize(file.size)
                    };
                    state.attachments.push(attachment);
                    renderAttachmentPreviews();
                    updateButtonState();
                };
                reader.readAsText(file);
            }
        });
    }

    function formatFileSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    function renderAttachmentPreviews() {
        elements.attachmentPreview.innerHTML = state.attachments.map((att, index) => {
            if (att.type === 'image') {
                return `
                    <div class="attachment-item" data-index="${index}">
                        <img src="${att.preview}" alt="${att.name}">
                        <button class="remove-attachment" onclick="removeAttachment(${index})">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                                <line x1="18" y1="6" x2="6" y2="18"/>
                                <line x1="6" y1="6" x2="18" y2="18"/>
                            </svg>
                        </button>
                    </div>
                `;
            } else {
                // Document or text file
                const iconSvg = getFileIconSvg(att.iconType);
                return `
                    <div class="attachment-item file-item" data-index="${index}" title="${att.name}">
                        <div class="file-icon">${iconSvg}</div>
                        <div class="file-name">${truncateFileName(att.name)}</div>
                        ${att.size ? `<div class="file-size">${att.size}</div>` : ''}
                        <button class="remove-attachment" onclick="removeAttachment(${index})">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                                <line x1="18" y1="6" x2="6" y2="18"/>
                                <line x1="6" y1="6" x2="18" y2="18"/>
                            </svg>
                        </button>
                    </div>
                `;
            }
        }).join('');

        elements.attachmentPreview.style.display = state.attachments.length > 0 ? 'flex' : 'none';
    }

    function truncateFileName(name, maxLength = 12) {
        if (name.length <= maxLength) return name;
        const ext = name.lastIndexOf('.');
        if (ext > 0) {
            const extension = name.substring(ext);
            const baseName = name.substring(0, ext);
            const truncatedBase = baseName.substring(0, maxLength - extension.length - 2);
            return truncatedBase + '..' + extension;
        }
        return name.substring(0, maxLength - 2) + '..';
    }

    // Make removeAttachment global
    window.removeAttachment = function (index) {
        state.attachments.splice(index, 1);
        renderAttachmentPreviews();
        updateButtonState();
    };

    // ============================================
    // Message Rendering
    // ============================================
    function createMessageElement(type, content, isStreaming = false) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${type}`;

        const sender = type === 'user' ? (window.i18n?.t('message.you') || 'You') : (window.i18n?.t('message.agent') || 'Agent');
        const avatarClass = type === 'user' ? 'user' : 'assistant';
        const icon = type === 'user' ? icons.user : icons.assistant;

        messageDiv.innerHTML = `
            <div class="message-avatar ${avatarClass}">
                ${icon}
            </div>
            <div class="message-body">
                <div class="message-header">
                    <span class="message-sender">${sender}</span>
                </div>
                <div class="message-content">
                    ${isStreaming ? '' : renderMarkdown(content)}
                </div>
            </div>
        `;

        return messageDiv;
    }

    // ============================================
    // Message Edit Functionality
    // ============================================
    const editModal = createEditModal();

    function createEditModal() {
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.id = 'editModal';
        modal.innerHTML = `
            <div class="modal-backdrop"></div>
            <div class="modal-content edit-modal-content">
                <div class="modal-header">
                    <h3>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                        </svg>
                        Edit Message
                    </h3>
                    <button type="button" class="modal-close" id="closeEditModalBtn">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="18" y1="6" x2="6" y2="18"></line>
                            <line x1="6" y1="6" x2="18" y2="18"></line>
                        </svg>
                    </button>
                </div>
                <div class="modal-body">
                    <div class="form-group">
                        <label for="editMessageTextarea">Message Content</label>
                        <textarea id="editMessageTextarea" class="form-textarea" rows="8" placeholder="Enter your message..."></textarea>
                    </div>
                    <div class="edit-info">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <circle cx="12" cy="12" r="10"/>
                            <line x1="12" y1="16" x2="12" y2="12"/>
                            <line x1="12" y1="8" x2="12.01" y2="8"/>
                        </svg>
                        <span>Editing will resend the message and regenerate the response</span>
                    </div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" id="cancelEditBtn">Cancel</button>
                    <button type="button" class="btn btn-primary" id="confirmEditBtn">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="22" y1="2" x2="11" y2="13"></line>
                            <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                        </svg>
                        Save & Resend
                    </button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
        return modal;
    }

    function openEditModal(messageIndex) {
        if (messageIndex < 0 || messageIndex >= state.messages.length) return;

        const message = state.messages[messageIndex];
        if (message.type !== 'user') return; // Only user messages can be edited

        state.editingMessageIndex = messageIndex;
        state.editingOriginalContent = message.content;

        const textarea = document.getElementById('editMessageTextarea');
        textarea.value = message.content;

        editModal.classList.add('active');
        textarea.focus();
        textarea.setSelectionRange(textarea.value.length, textarea.value.length);
    }

    function closeEditModal() {
        editModal.classList.remove('active');
        state.editingMessageIndex = -1;
        state.editingOriginalContent = '';
    }

    async function confirmEdit() {
        const textarea = document.getElementById('editMessageTextarea');
        const newContent = textarea.value.trim();

        if (!newContent) {
            showToast('Error', 'Message cannot be empty', 'error');
            return;
        }

        if (newContent === state.editingOriginalContent) {
            closeEditModal();
            return;
        }

        const messageIndex = state.editingMessageIndex;
        closeEditModal();

        // Remove all messages from the edited message onwards
        const removedMessages = state.messages.splice(messageIndex);

        // Remove corresponding DOM elements
        const messageElements = elements.messagesWrapper.querySelectorAll('.message');
        for (let i = messageIndex; i < messageElements.length; i++) {
            messageElements[i].remove();
        }

        // Resend the edited message
        sendMessage(newContent, removedMessages[0]?.attachments || []);
        showToast('Message Edited', 'Regenerating response...', 'info', 2000);
    }

    function initEditModal() {
        document.getElementById('closeEditModalBtn')?.addEventListener('click', closeEditModal);
        document.getElementById('cancelEditBtn')?.addEventListener('click', closeEditModal);
        document.getElementById('confirmEditBtn')?.addEventListener('click', confirmEdit);
        editModal.querySelector('.modal-backdrop')?.addEventListener('click', closeEditModal);

        document.getElementById('editMessageTextarea')?.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeEditModal();
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                confirmEdit();
            }
        });
    }

    // ============================================
    // Enhanced Drag & Drop with Full-Screen Overlay
    // ============================================
    let dropOverlay = null;
    let dragCounter = 0;

    function createDropOverlay() {
        const overlay = document.createElement('div');
        overlay.className = 'drop-overlay';
        overlay.innerHTML = `
            <div class="drop-overlay-content">
                <div class="drop-overlay-icon">
                    <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                        <polyline points="17 8 12 3 7 8"/>
                        <line x1="12" y1="3" x2="12" y2="15"/>
                    </svg>
                </div>
                <h3 class="drop-overlay-title">Drop files here</h3>
                <p class="drop-overlay-subtitle">Release to upload images and documents</p>
                <div class="drop-overlay-types">
                    <span class="drop-type-badge">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
                            <circle cx="8.5" cy="8.5" r="1.5"/>
                            <polyline points="21 15 16 10 5 21"/>
                        </svg>
                        Images
                    </span>
                    <span class="drop-type-badge">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                            <polyline points="14 2 14 8 20 8"/>
                        </svg>
                        PDF
                    </span>
                    <span class="drop-type-badge">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="16 18 22 12 16 6"/>
                            <polyline points="8 6 2 12 8 18"/>
                        </svg>
                        Code
                    </span>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);
        return overlay;
    }

    function initEnhancedDragDrop() {
        dropOverlay = createDropOverlay();

        // Global drag events for full-screen overlay
        document.addEventListener('dragenter', handleGlobalDragEnter);
        document.addEventListener('dragleave', handleGlobalDragLeave);
        document.addEventListener('dragover', handleGlobalDragOver);
        document.addEventListener('drop', handleGlobalDrop);
    }

    function handleGlobalDragEnter(e) {
        e.preventDefault();
        dragCounter++;

        if (e.dataTransfer?.types?.includes('Files')) {
            dropOverlay.classList.add('active');
        }
    }

    function handleGlobalDragLeave(e) {
        e.preventDefault();
        dragCounter--;

        if (dragCounter === 0) {
            dropOverlay.classList.remove('active');
        }
    }

    function handleGlobalDragOver(e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';
    }

    function handleGlobalDrop(e) {
        e.preventDefault();
        dragCounter = 0;
        dropOverlay.classList.remove('active');

        const files = e.dataTransfer?.files;
        if (files && files.length > 0) {
            handleFiles(files);
        }
    }

    function addMessage(type, content, attachments = []) {
        // Hide welcome message
        if (elements.welcomeMessage) {
            elements.welcomeMessage.classList.add('hidden');
        }

        const messageEl = createMessageElement(type, content);
        const contentEl = messageEl.querySelector('.message-content');

        // Add attachments for user messages
        if (type === 'user' && attachments.length > 0) {
            const images = attachments.filter(att => att.type === 'image');
            const files = attachments.filter(att => att.type !== 'image');

            // Add images
            if (images.length > 0) {
                const imagesHtml = images.map(att =>
                    `<img src="${att.preview}" class="message-image" alt="Attached image">`
                ).join('');
                contentEl.insertAdjacentHTML('afterbegin', `<div class="message-images">${imagesHtml}</div>`);
            }

            // Add files (PDF, text, etc.)
            if (files.length > 0) {
                const filesHtml = files.map(att => {
                    const iconSvg = getFileIconSvg(att.iconType || 'document');
                    return `<div class="message-file">
                        <span class="file-icon">${iconSvg}</span>
                        <span>${escapeHtml(att.name)}</span>
                        ${att.size ? `<span style="color: var(--text-muted);">(${att.size})</span>` : ''}
                    </div>`;
                }).join('');
                contentEl.insertAdjacentHTML('afterbegin', `<div class="message-files">${filesHtml}</div>`);
            }
        }

        elements.messagesWrapper.appendChild(messageEl);
        scrollToBottom();

        state.messages.push({ type, content, attachments });

        // Add message actions (bookmark, copy)
        addMessageActions(messageEl, state.messages.length - 1);

        // Enhance code blocks
        enhanceCodeBlocks();

        return messageEl;
    }

    function createStreamingMessage() {
        const messageEl = createMessageElement('assistant', '', true);
        const contentEl = messageEl.querySelector('.message-content');

        // Create separate containers for tools and text
        contentEl.innerHTML = `
            <div class="tools-container"></div>
            <div class="text-container">
                <div class="loading-indicator">
                    <div class="loading-dots">
                        <span></span>
                        <span></span>
                        <span></span>
                    </div>
                </div>
            </div>
        `;

        elements.messagesWrapper.appendChild(messageEl);
        scrollToBottom();

        // Return references to both containers
        const toolsContainer = contentEl.querySelector('.tools-container');
        const textContainer = contentEl.querySelector('.text-container');

        return { messageEl, contentEl, toolsContainer, textContainer };
    }

    function addToolIndicator(contentEl, toolName, description) {
        const indicator = document.createElement('div');
        indicator.className = 'tool-indicator';
        indicator.innerHTML = `${icons.tool} <span>Using: ${escapeHtml(toolName)}${description ? ' - ' + escapeHtml(description) : ''}</span>`;
        contentEl.appendChild(indicator);
        scrollToBottom();
    }

    // ============================================
    // WebSocket Connection
    // ============================================
    function connectWebSocket() {
        console.log('Connecting to WebSocket...');
        setStatus('busy', 'Connecting...');

        state.ws = new WebSocket(getWsUrl());

        state.ws.onopen = function () {
            console.log('WebSocket connected');
            setStatus('ready', 'Connected');
        };

        state.ws.onmessage = function (event) {
            const data = JSON.parse(event.data);
            handleMessage(data);
        };

        state.ws.onclose = function () {
            console.log('WebSocket disconnected');
            setStatus('error', 'Disconnected');
            // Attempt to reconnect after 3 seconds
            setTimeout(connectWebSocket, 3000);
        };

        state.ws.onerror = function (error) {
            console.error('WebSocket error:', error);
            setStatus('error', 'Error');
        };
    }

    function handleMessage(data) {
        console.log('Received:', data.type);

        switch (data.type) {
            case 'connected':
                setStatus('ready', 'Ready');
                // 连接成功后从服务端加载当前 session 的消息
                loadCurrentSessionMessages();
                break;

            case 'user_message':
                // 系统通知（来自回调或超时）
                if (data.source !== 'browser') {
                    // 隐藏欢迎消息
                    if (elements.welcomeMessage) {
                        elements.welcomeMessage.classList.add('hidden');
                    }
                    // 显示系统通知
                    addMessage('user', `[${data.source || 'system'}] ${data.content}`);
                    // 创建流式消息容器，准备接收 Claude 的回复
                    const { messageEl, contentEl, toolsContainer, textContainer } = createStreamingMessage();
                    state.currentMessageEl = messageEl;
                    state.toolsContainer = toolsContainer;
                    state.textContainer = textContainer;
                    state.fullContent = '';
                    state.isLoading = true;
                    updateButtonState();
                    setStatus('busy', 'Processing...');
                }
                break;

            case 'text':
                if (state.textContainer) {
                    // Clear loading indicator on first text
                    if (state.fullContent === '' && !currentTypewriter) {
                        state.textContainer.innerHTML = '';

                        // Initialize typewriter if enabled
                        if (TYPEWRITER_CONFIG.enabled) {
                            currentTypewriter = new TypewriterEngine(state.textContainer, TYPEWRITER_CONFIG);
                            currentTypewriter.start(
                                // Render callback - update display
                                (text) => {
                                    state.textContainer.innerHTML = renderMarkdown(text);
                                    // Apply syntax highlighting
                                    if (typeof hljs !== 'undefined') {
                                        state.textContainer.querySelectorAll('pre code:not(.hljs)').forEach((block) => {
                                            hljs.highlightElement(block);
                                        });
                                    }
                                    scrollToBottom();
                                },
                                // Completion callback
                                (finalText) => {
                                    enhanceCodeBlocks();
                                }
                            );
                        }
                    }

                    state.fullContent += data.content;

                    if (TYPEWRITER_CONFIG.enabled && currentTypewriter) {
                        // Feed to typewriter
                        currentTypewriter.append(data.content);
                    } else {
                        // Direct render (non-typewriter mode)
                        state.textContainer.innerHTML = renderMarkdown(state.fullContent);

                        // Apply syntax highlighting
                        if (typeof hljs !== 'undefined') {
                            state.textContainer.querySelectorAll('pre code:not(.hljs)').forEach((block) => {
                                hljs.highlightElement(block);
                            });
                        }

                        scrollToBottom();
                    }
                }
                break;

            case 'tool':
                if (state.toolsContainer) {
                    const desc = data.subagent ? `Subagent: ${data.subagent}` : data.description || '';
                    addToolIndicator(state.toolsContainer, data.name, desc);
                    setStatus('busy', `Using ${data.name}...`);
                }
                break;

            case 'result':
                // 显示本轮上下文统计
                if (data.usage || data.cost_usd != null) {
                    const parts = [];
                    if (data.usage) {
                        const inp = data.usage.input_tokens || 0;
                        const out = data.usage.output_tokens || 0;
                        const cache_read = data.usage.cache_read_input_tokens || 0;
                        parts.push(`${inp.toLocaleString()} in / ${out.toLocaleString()} out`);
                        if (cache_read) {
                            parts.push(`cache: ${cache_read.toLocaleString()}`);
                        }
                    }
                    if (data.cost_usd != null) {
                        parts.push(`$${data.cost_usd.toFixed(4)}`);
                    }
                    if (data.duration_ms) {
                        parts.push(`${(data.duration_ms / 1000).toFixed(1)}s`);
                    }
                    if (parts.length && state.textContainer) {
                        const infoEl = document.createElement('div');
                        infoEl.className = 'result-context-info';
                        infoEl.textContent = parts.join(' · ');
                        state.textContainer.appendChild(infoEl);
                    }
                }
                break;

            case 'done':
                // Message complete
                state.isLoading = false;
                updateButtonState();
                setStatus('ready', 'Ready');

                // Complete typewriter animation
                if (currentTypewriter) {
                    currentTypewriter.complete();
                    currentTypewriter = null;
                }

                // Store final content
                if (state.fullContent) {
                    state.messages.push({ type: 'assistant', content: state.fullContent });

                    // Add message actions to the completed message
                    if (state.currentMessageEl) {
                        addMessageActions(state.currentMessageEl, state.messages.length - 1);
                    }

                    // Update virtual scroll if enabled
                    if (virtualScrollManager) {
                        virtualScrollManager.addItem(state.messages.length - 1);
                    }
                }

                // 刷新 Claude sessions 列表（新对话会创建新 session）
                loadClaudeSessions();

                // Reset streaming state
                state.currentMessageEl = null;
                state.currentContentEl = null;
                state.toolsContainer = null;
                state.textContainer = null;
                state.fullContent = '';
                break;

            case 'cancelled':
                // Generation was cancelled but context preserved
                // Stop typewriter and flush remaining content
                if (currentTypewriter) {
                    currentTypewriter.complete();
                    currentTypewriter = null;
                }

                if (state.textContainer) {
                    const stopMsg = document.createElement('div');
                    stopMsg.className = 'message-stopped';
                    stopMsg.innerHTML = `
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                        </svg>
                        <em>${window.i18n?.t('message.stopped') || '[Stopped by user]'}</em>
                    `;
                    state.textContainer.appendChild(stopMsg);
                }
                state.isLoading = false;
                updateButtonState();
                setStatus('ready', 'Stopped');

                // Store partial content
                if (state.fullContent) {
                    state.messages.push({ type: 'assistant', content: state.fullContent + '\n[Stopped]' });
                }

                // Reset streaming state
                state.currentMessageEl = null;
                state.currentContentEl = null;
                state.toolsContainer = null;
                state.textContainer = null;
                state.fullContent = '';
                break;

            case 'system':
                // 系统消息（如 compact_boundary）
                console.log('System message:', data.subtype, data.data);
                if (data.subtype === 'compact_boundary') {
                    // 显示压缩通知
                    if (state.textContainer) {
                        const compactMsg = document.createElement('div');
                        compactMsg.innerHTML = '<em>[Context compacted]</em>';
                        compactMsg.style.color = 'var(--text-muted)';
                        state.textContainer.appendChild(compactMsg);
                    }
                }
                break;

            case 'error':
                if (state.currentContentEl) {
                    state.currentContentEl.innerHTML = `<p style="color: #f87171;">Error: ${escapeHtml(data.message)}</p>`;
                }
                state.isLoading = false;
                updateButtonState();
                setStatus('error', 'Error');
                break;

            case 'task_update':
                enhancedHandleTaskUpdate(data);
                break;

            case 'session_changed':
                // 来自后端的 session 切换通知
                console.log('Session changed:', data);
                if (_sessionChangeInitiatedLocally) {
                    // 本设备发起的，UI 已处理，跳过
                    _sessionChangeInitiatedLocally = false;
                    break;
                }
                // 其他设备/API 触发了 session 切换，同步本地 UI
                currentClaudeSessionId = data.session_id || null;
                elements.messagesWrapper.innerHTML = '';
                state.messages = [];
                if (data.is_new) {
                    showWelcomeMessage();
                    showToast('New Chat', 'New conversation started from another device', 'info', 2000);
                } else {
                    showToast('Session Switched', `Switched to "${data.title || 'another session'}" from another device`, 'info', 2000);
                    // 从服务端加载切换后 session 的消息
                    loadCurrentSessionMessages();
                }
                loadClaudeSessions();
                break;
        }
    }

    // ============================================
    // Send Message
    // ============================================
    function sendMessage(message, attachments = []) {
        if (state.isLoading || (!message.trim() && attachments.length === 0) || !state.ws || state.ws.readyState !== WebSocket.OPEN) {
            return;
        }

        state.isLoading = true;
        updateButtonState();
        setStatus('busy', 'Thinking...');

        // Add user message with attachments preview
        addMessage('user', message, attachments);

        // Create streaming message container
        const { messageEl, contentEl, toolsContainer, textContainer } = createStreamingMessage();
        state.currentMessageEl = messageEl;
        state.currentContentEl = contentEl;
        state.toolsContainer = toolsContainer;
        state.textContainer = textContainer;
        state.fullContent = '';

        // Build message payload
        const payload = { message: message };

        if (attachments.length > 0) {
            payload.attachments = attachments.map(att => {
                if (att.type === 'image' || att.type === 'document') {
                    return {
                        type: att.type,
                        media_type: att.media_type,
                        data: att.data
                    };
                } else if (att.type === 'text_file') {
                    return {
                        type: 'text_file',
                        name: att.name,
                        content: att.content
                    };
                }
                return att;
            });
        }

        // Send to WebSocket
        state.ws.send(JSON.stringify(payload));
    }

    function clearSession() {
        // Close and reconnect WebSocket
        if (state.ws) {
            state.ws.close();
        }

        // Clear UI
        elements.messagesWrapper.innerHTML = '';
        if (elements.welcomeMessage) {
            elements.messagesWrapper.appendChild(elements.welcomeMessage);
            elements.welcomeMessage.classList.remove('hidden');
        } else {
            elements.messagesWrapper.innerHTML = `
                <div class="welcome-message" id="welcomeMessage">
                    <div class="welcome-icon">
                        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1">
                            <path d="M12 2L2 7L12 12L22 7L12 2Z"/>
                            <path d="M2 17L12 22L22 17"/>
                            <path d="M2 12L12 17L22 12"/>
                        </svg>
                    </div>
                    <h2>Start a Conversation</h2>
                    <p>Send a message to begin chatting with the AI agent.</p>
                </div>
            `;
        }

        // Clear attachments
        state.attachments = [];
        renderAttachmentPreviews();

        state.messages = [];
        state.currentMessageEl = null;
        state.currentContentEl = null;
        state.toolsContainer = null;
        state.textContainer = null;
        state.fullContent = '';

        // Reconnect
        setTimeout(connectWebSocket, 100);
    }

    // ============================================
    // Event Handlers
    // ============================================
    function updateButtonState() {
        const hasContent = elements.messageInput.value.trim() || state.attachments.length > 0;

        if (state.isLoading) {
            // Show Stop button
            elements.sendBtn.innerHTML = icons.stop;
            elements.sendBtn.classList.add('stop-btn');
            elements.sendBtn.disabled = false;
            elements.sendBtn.title = 'Stop generating';
        } else {
            // Show Send button
            elements.sendBtn.innerHTML = icons.send;
            elements.sendBtn.classList.remove('stop-btn');
            elements.sendBtn.disabled = !hasContent;
            elements.sendBtn.title = 'Send message';
        }
    }

    function handleStop() {
        if (state.ws && state.ws.readyState === WebSocket.OPEN) {
            // Send cancel message instead of closing connection
            state.ws.send(JSON.stringify({ type: 'cancel' }));
            console.log('[WS] Cancel request sent');
        }
    }

    function handleSend() {
        if (state.isLoading) {
            handleStop();
            return;
        }

        const message = elements.messageInput.value.trim();
        const attachments = [...state.attachments];

        if (message || attachments.length > 0) {
            elements.messageInput.value = '';
            state.attachments = [];
            renderAttachmentPreviews();
            autoResizeTextarea();
            sendMessage(message, attachments);
        }
    }

    function handleKeydown(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    }

    function handleInput() {
        autoResizeTextarea();
        if (!state.isLoading) {
            updateButtonState();
        }
    }

    // Drag and Drop Handlers
    function handleDragOver(e) {
        e.preventDefault();
        e.stopPropagation();
        elements.inputContainer.classList.add('drag-over');
    }

    function handleDragLeave(e) {
        e.preventDefault();
        e.stopPropagation();
        elements.inputContainer.classList.remove('drag-over');
    }

    function handleDrop(e) {
        e.preventDefault();
        e.stopPropagation();
        elements.inputContainer.classList.remove('drag-over');

        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleFiles(files);
        }
    }

    // Paste handler for images
    function handlePaste(e) {
        const items = e.clipboardData?.items;
        if (!items) return;

        const files = [];
        for (const item of items) {
            const file = item.getAsFile();
            if (file && getFileType(file)) {
                files.push(file);
            }
        }
        if (files.length > 0) {
            e.preventDefault();
            handleFiles(files);
        }
    }

    // ============================================
    // Theme Management
    // ============================================
    function initTheme() {
        // Always use Claude-style parchment theme
        localStorage.removeItem('theme');  // Clear any old theme setting
        document.documentElement.setAttribute('data-theme', 'parchment');
    }

    // ============================================
    // Mobile Menu
    // ============================================
    function initMobileMenu() {
        const sidebar = document.querySelector('.sidebar');
        const overlay = document.getElementById('sidebarOverlay');
        const menuBtn = document.getElementById('mobileMenuBtn');

        if (!sidebar || !overlay || !menuBtn) return;

        function openMenu() {
            sidebar.classList.add('open');
            overlay.style.display = 'block';
        }

        function closeMenu() {
            sidebar.classList.remove('open');
            overlay.style.display = 'none';
        }

        menuBtn.addEventListener('click', () => {
            if (sidebar.classList.contains('open')) {
                closeMenu();
            } else {
                openMenu();
            }
        });

        overlay.addEventListener('click', closeMenu);

        // Close on session switch
        const originalSwitchClaudeSession = window.switchClaudeSession;
        window.switchClaudeSession = async function(sessionId) {
            await originalSwitchClaudeSession(sessionId);
            closeMenu();
        };
    }

    // ============================================
    // Keyboard Shortcuts
    // ============================================
    const shortcutsPanel = document.getElementById('shortcutsPanel');

    function showShortcutsPanel() {
        shortcutsPanel?.classList.add('active');
    }

    function hideShortcutsPanel() {
        shortcutsPanel?.classList.remove('active');
    }

    function initKeyboardShortcuts() {
        // Shortcuts panel close handlers
        document.getElementById('closeShortcutsBtn')?.addEventListener('click', hideShortcutsPanel);
        shortcutsPanel?.querySelector('.shortcuts-backdrop')?.addEventListener('click', hideShortcutsPanel);

        document.addEventListener('keydown', (e) => {
            // Don't trigger shortcuts when typing in inputs (except for specific ones)
            const isInputFocused = document.activeElement.tagName === 'INPUT' ||
                                   document.activeElement.tagName === 'TEXTAREA';

            // Escape: Close modals/panels or stop generation
            if (e.key === 'Escape') {
                if (searchBar?.classList.contains('active')) {
                    closeSearch();
                    return;
                }
                if (bookmarksPanel?.classList.contains('active')) {
                    closeBookmarksPanel();
                    return;
                }
                if (shortcutsPanel?.classList.contains('active')) {
                    hideShortcutsPanel();
                    return;
                }
                if (state.isLoading) {
                    handleStop();
                    return;
                }
                // Blur input if focused
                if (isInputFocused) {
                    document.activeElement.blur();
                    return;
                }
            }

            // Ctrl/Cmd + /: Show shortcuts panel
            if ((e.ctrlKey || e.metaKey) && e.key === '/') {
                e.preventDefault();
                if (shortcutsPanel?.classList.contains('active')) {
                    hideShortcutsPanel();
                } else {
                    showShortcutsPanel();
                }
                return;
            }

            // Ctrl/Cmd + F: Toggle search
            if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
                e.preventDefault();
                toggleSearch();
                return;
            }

            // Ctrl/Cmd + B: Toggle bookmarks
            if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
                e.preventDefault();
                toggleBookmarksPanel();
                return;
            }

            // Ctrl/Cmd + E: Export chat
            if ((e.ctrlKey || e.metaKey) && e.key === 'e') {
                e.preventDefault();
                exportToMarkdown();
                return;
            }

            // Ctrl/Cmd + ,: Open settings
            if ((e.ctrlKey || e.metaKey) && e.key === ',') {
                e.preventDefault();
                window.location.href = '/settings';
                return;
            }

            // Ctrl/Cmd + N: New session
            if ((e.ctrlKey || e.metaKey) && e.key === 'n') {
                e.preventDefault();
                createNewSession();
                return;
            }

            // Ctrl/Cmd + K: Focus input and clear (works even in input)
            if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                e.preventDefault();
                elements.messageInput.value = '';
                elements.messageInput.focus();
                autoResizeTextarea();
                updateButtonState();
                return;
            }

            // Only handle these when not in input
            if (!isInputFocused) {
                // /: Focus input
                if (e.key === '/') {
                    e.preventDefault();
                    elements.messageInput.focus();
                    return;
                }

                // ?: Show shortcuts (shift + /)
                if (e.key === '?') {
                    e.preventDefault();
                    showShortcutsPanel();
                    return;
                }

                // j/k: Scroll messages
                if (e.key === 'j') {
                    elements.messagesContainer.scrollBy({ top: 100, behavior: 'smooth' });
                    return;
                }
                if (e.key === 'k') {
                    elements.messagesContainer.scrollBy({ top: -100, behavior: 'smooth' });
                    return;
                }

                // g: Go to top
                if (e.key === 'g') {
                    elements.messagesContainer.scrollTo({ top: 0, behavior: 'smooth' });
                    return;
                }

                // G: Go to bottom
                if (e.key === 'G') {
                    scrollToBottom();
                    return;
                }
            }
        });
    }

    // ============================================
    // Search Functionality
    // ============================================
    const searchBar = document.getElementById('searchBar');
    const searchInput = document.getElementById('searchInput');
    const searchResultsCount = document.getElementById('searchResultsCount');
    const searchPrevBtn = document.getElementById('searchPrevBtn');
    const searchNextBtn = document.getElementById('searchNextBtn');
    const searchCloseBtn = document.getElementById('searchCloseBtn');
    const searchToggleBtn = document.getElementById('searchToggleBtn');

    function toggleSearch() {
        if (searchBar.classList.contains('active')) {
            closeSearch();
        } else {
            openSearch();
        }
    }

    function openSearch() {
        searchBar.classList.add('active');
        searchToggleBtn?.classList.add('active');
        searchInput.focus();
    }

    function closeSearch() {
        searchBar.classList.remove('active');
        searchToggleBtn?.classList.remove('active');
        searchInput.value = '';
        clearSearchHighlights();
        state.searchResults = [];
        state.currentSearchIndex = -1;
        state.searchQuery = '';
        updateSearchResultsCount();
    }

    function performSearch(query) {
        clearSearchHighlights();
        state.searchResults = [];
        state.currentSearchIndex = -1;
        state.searchQuery = query.toLowerCase().trim();

        if (!state.searchQuery) {
            updateSearchResultsCount();
            return;
        }

        const messages = elements.messagesWrapper.querySelectorAll('.message');
        messages.forEach((msg, index) => {
            const content = msg.querySelector('.message-content');
            if (content) {
                const text = content.textContent.toLowerCase();
                if (text.includes(state.searchQuery)) {
                    state.searchResults.push({ index, element: msg, content });
                    highlightSearchMatches(content, state.searchQuery);
                }
            }
        });

        updateSearchResultsCount();

        if (state.searchResults.length > 0) {
            state.currentSearchIndex = 0;
            scrollToSearchResult(0);
        }
    }

    function highlightSearchMatches(element, query) {
        const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT, null, false);
        const textNodes = [];
        while (walker.nextNode()) {
            textNodes.push(walker.currentNode);
        }

        textNodes.forEach(node => {
            const text = node.textContent;
            const lowerText = text.toLowerCase();
            const index = lowerText.indexOf(query);
            if (index !== -1) {
                const before = text.substring(0, index);
                const match = text.substring(index, index + query.length);
                const after = text.substring(index + query.length);

                const span = document.createElement('span');
                span.className = 'search-highlight';
                span.textContent = match;

                const fragment = document.createDocumentFragment();
                if (before) fragment.appendChild(document.createTextNode(before));
                fragment.appendChild(span);
                if (after) fragment.appendChild(document.createTextNode(after));

                node.parentNode.replaceChild(fragment, node);
            }
        });
    }

    function clearSearchHighlights() {
        const highlights = elements.messagesWrapper.querySelectorAll('.search-highlight');
        highlights.forEach(highlight => {
            const parent = highlight.parentNode;
            parent.replaceChild(document.createTextNode(highlight.textContent), highlight);
            parent.normalize();
        });
    }

    function scrollToSearchResult(index) {
        if (index < 0 || index >= state.searchResults.length) return;

        // Remove current highlight
        elements.messagesWrapper.querySelectorAll('.search-highlight.current').forEach(el => {
            el.classList.remove('current');
        });

        const result = state.searchResults[index];
        result.element.scrollIntoView({ behavior: 'smooth', block: 'center' });

        // Add current highlight to first match in this message
        const firstHighlight = result.content.querySelector('.search-highlight');
        if (firstHighlight) {
            firstHighlight.classList.add('current');
        }

        updateSearchResultsCount();
    }

    function updateSearchResultsCount() {
        if (!state.searchQuery || state.searchResults.length === 0) {
            searchResultsCount.textContent = '';
            searchResultsCount.classList.remove('has-results');
            searchPrevBtn.disabled = true;
            searchNextBtn.disabled = true;
        } else {
            searchResultsCount.textContent = `${state.currentSearchIndex + 1}/${state.searchResults.length}`;
            searchResultsCount.classList.add('has-results');
            searchPrevBtn.disabled = state.searchResults.length <= 1;
            searchNextBtn.disabled = state.searchResults.length <= 1;
        }
    }

    function searchPrev() {
        if (state.searchResults.length === 0) return;
        state.currentSearchIndex = (state.currentSearchIndex - 1 + state.searchResults.length) % state.searchResults.length;
        scrollToSearchResult(state.currentSearchIndex);
    }

    function searchNext() {
        if (state.searchResults.length === 0) return;
        state.currentSearchIndex = (state.currentSearchIndex + 1) % state.searchResults.length;
        scrollToSearchResult(state.currentSearchIndex);
    }

    // ============================================
    // Bookmark Functionality
    // ============================================
    const bookmarksPanel = document.getElementById('bookmarksPanel');
    const bookmarksList = document.getElementById('bookmarksList');
    const bookmarksToggleBtn = document.getElementById('bookmarksToggleBtn');
    const closeBookmarksBtn = document.getElementById('closeBookmarksBtn');
    const clearBookmarksBtn = document.getElementById('clearBookmarksBtn');

    function loadBookmarks() {
        try {
            const data = localStorage.getItem(BOOKMARKS_KEY);
            if (data) {
                state.bookmarks = JSON.parse(data);
            }
        } catch (e) {
            console.warn('Failed to load bookmarks:', e);
            state.bookmarks = [];
        }
    }

    function saveBookmarks() {
        try {
            localStorage.setItem(BOOKMARKS_KEY, JSON.stringify(state.bookmarks));
        } catch (e) {
            console.warn('Failed to save bookmarks:', e);
        }
    }

    function toggleBookmarksPanel() {
        if (bookmarksPanel.classList.contains('active')) {
            closeBookmarksPanel();
        } else {
            openBookmarksPanel();
        }
    }

    function openBookmarksPanel() {
        bookmarksPanel.classList.add('active');
        bookmarksToggleBtn?.classList.add('active');
        renderBookmarks();
    }

    function closeBookmarksPanel() {
        bookmarksPanel.classList.remove('active');
        bookmarksToggleBtn?.classList.remove('active');
    }

    function renderBookmarks() {
        if (!bookmarksList) return;

        if (state.bookmarks.length === 0) {
            bookmarksList.innerHTML = `
                <div class="bookmarks-empty">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
                    </svg>
                    <p>No bookmarked messages yet.</p>
                    <p>Click the bookmark icon on any message to save it.</p>
                </div>
            `;
            return;
        }

        bookmarksList.innerHTML = state.bookmarks.map((bookmark, index) => {
            const senderIcon = bookmark.type === 'user'
                ? `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                       <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                       <circle cx="12" cy="7" r="4"/>
                   </svg>`
                : `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                       <path d="M12 2L2 7L12 12L22 7L12 2Z"/>
                       <path d="M2 17L12 22L22 17"/>
                       <path d="M2 12L12 17L22 12"/>
                   </svg>`;

            const preview = bookmark.content.length > 200
                ? bookmark.content.substring(0, 200) + '...'
                : bookmark.content;

            return `
                <div class="bookmark-item" data-index="${index}">
                    <div class="bookmark-item-header">
                        <span class="bookmark-item-sender ${bookmark.type}">
                            ${senderIcon}
                            ${bookmark.type === 'user' ? 'You' : 'Agent'}
                        </span>
                        <span class="bookmark-item-time">${formatTime(bookmark.timestamp)}</span>
                    </div>
                    <div class="bookmark-item-content">${escapeHtml(preview)}</div>
                    <div class="bookmark-item-actions">
                        <button class="bookmark-action-btn" onclick="window.copyBookmark(${index})">Copy</button>
                        <button class="bookmark-action-btn delete" onclick="window.removeBookmark(${index})">Remove</button>
                    </div>
                </div>
            `;
        }).join('');
    }

    function addBookmark(messageIndex) {
        if (messageIndex < 0 || messageIndex >= state.messages.length) return;

        const message = state.messages[messageIndex];
        const bookmark = {
            type: message.type,
            content: message.content,
            timestamp: Date.now(),
            messageIndex: messageIndex
        };

        // Check if already bookmarked
        const existingIndex = state.bookmarks.findIndex(b =>
            b.content === bookmark.content && b.type === bookmark.type
        );

        if (existingIndex === -1) {
            state.bookmarks.unshift(bookmark);
            saveBookmarks();
            showToast('Bookmarked', 'Message saved to bookmarks', 'success', 2000);
            updateBookmarkButtons();
        }
    }

    function removeBookmarkByContent(type, content) {
        const index = state.bookmarks.findIndex(b =>
            b.content === content && b.type === type
        );
        if (index !== -1) {
            state.bookmarks.splice(index, 1);
            saveBookmarks();
            renderBookmarks();
            updateBookmarkButtons();
            showToast('Removed', 'Bookmark removed', 'info', 2000);
        }
    }

    window.removeBookmark = function(index) {
        if (index >= 0 && index < state.bookmarks.length) {
            state.bookmarks.splice(index, 1);
            saveBookmarks();
            renderBookmarks();
            updateBookmarkButtons();
        }
    };

    window.copyBookmark = function(index) {
        if (index >= 0 && index < state.bookmarks.length) {
            const content = state.bookmarks[index].content;
            navigator.clipboard.writeText(content).then(() => {
                showToast('Copied', 'Content copied to clipboard', 'success', 2000);
            }).catch(() => {
                showToast('Error', 'Failed to copy content', 'error');
            });
        }
    };

    function clearAllBookmarks() {
        if (state.bookmarks.length === 0) return;
        state.bookmarks = [];
        saveBookmarks();
        renderBookmarks();
        updateBookmarkButtons();
        showToast('Cleared', 'All bookmarks removed', 'info', 2000);
    }

    function isBookmarked(type, content) {
        return state.bookmarks.some(b => b.content === content && b.type === type);
    }

    function updateBookmarkButtons() {
        const messages = elements.messagesWrapper.querySelectorAll('.message');
        messages.forEach((msg, index) => {
            const btn = msg.querySelector('.bookmark-btn');
            if (btn && state.messages[index]) {
                const message = state.messages[index];
                const bookmarked = isBookmarked(message.type, message.content);
                btn.classList.toggle('bookmarked', bookmarked);
            }
        });
    }

    // ============================================
    // Export to Markdown
    // ============================================
    const exportBtn = document.getElementById('exportBtn');

    function exportToMarkdown() {
        if (state.messages.length === 0) {
            showToast('No Messages', 'Nothing to export', 'warning');
            return;
        }

        // Show progress indicator
        const progress = document.createElement('div');
        progress.className = 'export-progress';
        progress.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 12a9 9 0 11-6.219-8.56"/>
            </svg>
            Exporting...
        `;
        document.body.appendChild(progress);

        setTimeout(() => {
            try {
                const instanceName = currentInstance;
                const timestamp = new Date().toISOString().split('T')[0];
                const filename = `chat-${instanceName}-${timestamp}.md`;

                let markdown = `# Chat Export\n\n`;
                markdown += `**Instance:** ${instanceName}\n`;
                markdown += `**Date:** ${new Date().toLocaleString()}\n`;
                markdown += `**Messages:** ${state.messages.length}\n\n`;
                markdown += `---\n\n`;

                state.messages.forEach((msg, index) => {
                    const sender = msg.type === 'user' ? 'You' : 'Agent';
                    const icon = msg.type === 'user' ? 'USER' : 'AGENT';

                    markdown += `## [${icon}] ${sender}\n\n`;
                    markdown += `${msg.content}\n\n`;

                    if (index < state.messages.length - 1) {
                        markdown += `---\n\n`;
                    }
                });

                // Add bookmarked messages section if any
                if (state.bookmarks.length > 0) {
                    markdown += `\n---\n\n# Bookmarked Messages\n\n`;
                    state.bookmarks.forEach((bookmark, index) => {
                        const sender = bookmark.type === 'user' ? 'You' : 'Agent';
                        markdown += `### Bookmark ${index + 1} (${sender})\n\n`;
                        markdown += `${bookmark.content}\n\n`;
                    });
                }

                // Create and download file
                const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);

                showToast('Exported', `Saved as ${filename}`, 'success');
            } catch (e) {
                console.error('Export failed:', e);
                showToast('Export Failed', 'Could not export chat', 'error');
            } finally {
                progress.remove();
            }
        }, 500);
    }

    // ============================================
    // Code Block Enhancements
    // ============================================
    function enhanceCodeBlocks() {
        const codeBlocks = elements.messagesWrapper.querySelectorAll('pre code');
        codeBlocks.forEach(code => {
            const pre = code.parentElement;
            if (pre.querySelector('.code-copy-btn')) return; // Already enhanced

            // Detect language from class
            const langClass = Array.from(code.classList).find(c => c.startsWith('language-'));
            const language = langClass ? langClass.replace('language-', '').toUpperCase() : 'CODE';
            pre.setAttribute('data-language', language);

            // Add copy button
            const copyBtn = document.createElement('button');
            copyBtn.className = 'code-copy-btn';
            copyBtn.textContent = 'Copy';
            copyBtn.onclick = function() {
                navigator.clipboard.writeText(code.textContent).then(() => {
                    copyBtn.textContent = 'Copied';
                    copyBtn.classList.add('copied');
                    setTimeout(() => {
                        copyBtn.textContent = 'Copy';
                        copyBtn.classList.remove('copied');
                    }, 2000);
                });
            };
            pre.appendChild(copyBtn);

            // Apply syntax highlighting if not already done
            if (typeof hljs !== 'undefined' && !code.classList.contains('hljs')) {
                hljs.highlightElement(code);
            }
        });
    }

    // ============================================
    // Message Actions (Bookmark, Copy, Edit)
    // ============================================
    function addMessageActions(messageEl, messageIndex) {
        // Check if actions already exist
        if (messageEl.querySelector('.message-actions')) return;

        const actionsDiv = document.createElement('div');
        actionsDiv.className = 'message-actions';

        const message = state.messages[messageIndex];
        if (!message) return;

        const bookmarked = isBookmarked(message.type, message.content);
        const isUserMessage = message.type === 'user';

        actionsDiv.innerHTML = `
            ${isUserMessage ? `
                <button class="message-action-btn edit-btn" title="${window.i18n?.t('message.edit') || 'Edit message'}">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                    </svg>
                </button>
            ` : ''}
            <button class="message-action-btn bookmark-btn ${bookmarked ? 'bookmarked' : ''}" title="${window.i18n?.t('message.bookmark') || 'Bookmark message'}">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
                </svg>
            </button>
            <button class="message-action-btn copy-btn" title="${window.i18n?.t('message.copy') || 'Copy message'}">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                </svg>
            </button>
        `;

        // Edit button handler (only for user messages)
        const editBtn = actionsDiv.querySelector('.edit-btn');
        if (editBtn) {
            editBtn.onclick = function(e) {
                e.stopPropagation();
                openEditModal(messageIndex);
            };
        }

        const bookmarkBtn = actionsDiv.querySelector('.bookmark-btn');
        bookmarkBtn.onclick = function(e) {
            e.stopPropagation();
            if (bookmarkBtn.classList.contains('bookmarked')) {
                removeBookmarkByContent(message.type, message.content);
                bookmarkBtn.classList.remove('bookmarked');
            } else {
                addBookmark(messageIndex);
                bookmarkBtn.classList.add('bookmarked');
            }
        };

        const copyBtn = actionsDiv.querySelector('.copy-btn');
        copyBtn.onclick = function(e) {
            e.stopPropagation();
            if (message) {
                navigator.clipboard.writeText(message.content).then(() => {
                    showToast('Copied', 'Message copied to clipboard', 'success', 2000);
                });
            }
        };

        messageEl.appendChild(actionsDiv);
    }

    // ============================================
    // Status Drawer (Right Side Panel)
    // ============================================
    const statusDrawer = document.getElementById('statusDrawer');
    const statusDrawerToggle = document.getElementById('statusDrawerToggle');
    const closeStatusDrawerBtn = document.getElementById('closeStatusDrawerBtn');
    const drawerTaskList = document.getElementById('drawerTaskList');
    const taskBadge = document.getElementById('taskBadge');

    // Drawer UI Management
    function openStatusDrawer() {
        statusDrawer?.classList.add('visible');
        loadTasksForDrawer();
    }

    function closeStatusDrawer() {
        statusDrawer?.classList.remove('visible');
    }

    function toggleStatusDrawer() {
        if (statusDrawer?.classList.contains('visible')) {
            closeStatusDrawer();
        } else {
            openStatusDrawer();
        }
    }

    // Task filter state
    let currentTaskFilter = 'all';

    // Load and render tasks in drawer
    async function loadTasksForDrawer() {
        try {
            const response = await fetch('/task/list');
            const data = await response.json();
            state.tasks = data.tasks || [];
            renderDrawerTasks();
            renderTasks(); // Also update the bottom bar
            updateTaskBadge();
            updateFilterCounts();
        } catch (error) {
            console.error('Failed to load tasks for drawer:', error);
        }
    }

    // Update filter tab counts
    function updateFilterCounts() {
        const all = state.tasks.length;
        const running = state.tasks.filter(t => t.status === 'running').length;
        const done = state.tasks.filter(t => t.status === 'done').length;
        const blocked = state.tasks.filter(t => t.status === 'blocked' || t.status === 'timeout').length;

        const countAll = document.getElementById('filterCountAll');
        const countRunning = document.getElementById('filterCountRunning');
        const countDone = document.getElementById('filterCountDone');
        const countBlocked = document.getElementById('filterCountBlocked');

        if (countAll) countAll.textContent = all;
        if (countRunning) countRunning.textContent = running;
        if (countDone) countDone.textContent = done;
        if (countBlocked) countBlocked.textContent = blocked;
    }

    // Initialize task filter tabs
    function initTaskFilters() {
        const tabs = document.querySelectorAll('.task-filter-tab');
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                tabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                currentTaskFilter = tab.dataset.filter;
                renderDrawerTasks();
            });
        });
    }

    // Get filtered tasks
    function getFilteredTasks() {
        if (currentTaskFilter === 'all') return state.tasks;
        if (currentTaskFilter === 'running') return state.tasks.filter(t => t.status === 'running');
        if (currentTaskFilter === 'done') return state.tasks.filter(t => t.status === 'done');
        if (currentTaskFilter === 'blocked') return state.tasks.filter(t => t.status === 'blocked' || t.status === 'timeout');
        return state.tasks;
    }

    function renderDrawerTasks() {
        if (!drawerTaskList) return;

        const filteredTasks = getFilteredTasks();

        if (filteredTasks.length === 0) {
            const emptyMessage = currentTaskFilter === 'all' ? 'No tasks' : `No ${currentTaskFilter} tasks`;
            drawerTaskList.innerHTML = `<div class="drawer-empty-state">${emptyMessage}</div>`;
            return;
        }

        drawerTaskList.innerHTML = filteredTasks.map(task => {
            const progress = task.total_steps > 0 ? (task.progress || 0) : 0;
            const percent = task.total_steps > 0 ? Math.round((progress / task.total_steps) * 100) : 0;
            const elapsed = formatElapsedTime(task.registered_at);
            const remaining = formatRemainingTime(task.expires_at);

            return `
                <div class="drawer-task-item" data-task-id="${escapeHtml(task.task_id)}">
                    <button class="drawer-task-delete-btn" onclick="window.removeTaskFromDrawer('${escapeHtml(task.task_id)}')" title="Delete task">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="18" y1="6" x2="6" y2="18"></line>
                            <line x1="6" y1="6" x2="18" y2="18"></line>
                        </svg>
                    </button>
                    <div class="drawer-task-item-header">
                        <span class="drawer-task-id">${escapeHtml(task.task_id)}</span>
                        <span class="drawer-task-status ${task.status}">${task.status}</span>
                    </div>
                    ${task.description ? `<div class="drawer-task-desc">${escapeHtml(task.description)}</div>` : ''}
                    ${task.total_steps > 0 ? `
                        <div class="drawer-task-progress">
                            <div class="drawer-task-progress-bar" style="width: ${percent}%"></div>
                        </div>
                    ` : ''}
                    <div class="drawer-task-meta">
                        <span>${elapsed || 'Just started'}</span>
                        <span>${remaining}</span>
                    </div>
                    ${task.current_step ? `<div class="drawer-task-desc" style="font-size: 11px; margin-top: 4px;">${escapeHtml(task.current_step)}</div>` : ''}
                </div>
            `;
        }).join('');
    }

    function updateTaskBadge() {
        if (!taskBadge) return;

        const runningTasks = state.tasks.filter(t => t.status === 'running').length;
        if (runningTasks > 0) {
            taskBadge.textContent = runningTasks.toString();
            taskBadge.style.display = 'flex';
        } else {
            taskBadge.style.display = 'none';
        }
    }

    window.removeTaskFromDrawer = async function(taskId) {
        try {
            await fetch(`/task/${taskId}`, { method: 'DELETE' });
            await loadTasksForDrawer();
            showToast('Task Removed', `Task ${taskId} has been removed`, 'info', 2000);
        } catch (error) {
            console.error('Failed to remove task:', error);
            showToast('Error', 'Failed to remove task', 'error');
        }
    };

    // ============================================
    // Task Registration (from Drawer)
    // ============================================
    async function registerNewTask() {
        const taskIdInput = document.getElementById('newTaskId');
        const taskDescInput = document.getElementById('newTaskDesc');
        const taskTimeoutInput = document.getElementById('newTaskTimeout');

        const taskId = taskIdInput?.value.trim();
        const description = taskDescInput?.value.trim();
        const timeout = parseInt(taskTimeoutInput?.value) || 20;

        if (!taskId) {
            showToast('Error', 'Task ID is required', 'error');
            return;
        }

        try {
            const response = await fetch('/task/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    task_id: taskId,
                    description: description,
                    timeout_minutes: timeout,
                    total_steps: 0
                })
            });

            if (response.ok) {
                showToast('Task Registered', `Task "${taskId}" has been registered`, 'success');
                // Clear form
                if (taskIdInput) taskIdInput.value = '';
                if (taskDescInput) taskDescInput.value = '';
                if (taskTimeoutInput) taskTimeoutInput.value = '20';
                // Refresh task list
                await loadTasksForDrawer();
            } else {
                const errorData = await response.json();
                showToast('Error', errorData.detail || 'Failed to register task', 'error');
            }
        } catch (error) {
            console.error('Failed to register task:', error);
            showToast('Error', 'Failed to register task', 'error');
        }
    }

    // ============================================
    // Patrol Task Configuration
    // ============================================
    const PATROL_CONFIG_KEY = 'jarvis_patrol_config';
    const PATROL_HISTORY_KEY = 'jarvis_patrol_history';
    let patrolTimer = null;

    function loadPatrolConfig() {
        try {
            const data = localStorage.getItem(PATROL_CONFIG_KEY);
            if (data) {
                return JSON.parse(data);
            }
        } catch (e) {
            console.warn('Failed to load patrol config:', e);
        }
        return {
            enabled: false,
            interval: 5,
            message: 'Please check task progress and report status.'
        };
    }

    function savePatrolConfig(config) {
        try {
            localStorage.setItem(PATROL_CONFIG_KEY, JSON.stringify(config));
        } catch (e) {
            console.warn('Failed to save patrol config:', e);
        }
    }

    // Patrol History Management
    function loadPatrolHistory() {
        try {
            const data = localStorage.getItem(PATROL_HISTORY_KEY);
            if (data) return JSON.parse(data);
        } catch (e) {
            console.warn('Failed to load patrol history:', e);
        }
        return [];
    }

    function savePatrolHistory(history) {
        try {
            localStorage.setItem(PATROL_HISTORY_KEY, JSON.stringify(history));
        } catch (e) {
            console.warn('Failed to save patrol history:', e);
        }
    }

    function addPatrolHistoryEntry(message) {
        const history = loadPatrolHistory();
        const entry = {
            time: new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }),
            message: message.substring(0, 50)
        };
        history.unshift(entry);
        // Keep only last 10 entries
        if (history.length > 10) history.length = 10;
        savePatrolHistory(history);
        renderPatrolHistory();
    }

    function renderPatrolHistory() {
        const list = document.getElementById('patrolHistoryList');
        if (!list) return;

        const history = loadPatrolHistory();
        if (history.length === 0) {
            list.innerHTML = '<div class="drawer-empty-state" style="padding: 10px; font-size: 11px;">No history yet</div>';
            return;
        }

        list.innerHTML = history.map(entry => `
            <div class="patrol-history-item">
                <span class="patrol-history-time">${entry.time}</span>
                <span class="patrol-history-message">${escapeHtml(entry.message)}</span>
            </div>
        `).join('');
    }

    function clearPatrolHistory() {
        savePatrolHistory([]);
        renderPatrolHistory();
        showToast('History Cleared', 'Patrol history has been cleared', 'info', 2000);
    }

    function initPatrolTask() {
        const config = loadPatrolConfig();
        const enabledCheckbox = document.getElementById('patrolEnabled');
        const intervalInput = document.getElementById('patrolInterval');
        const messageInput = document.getElementById('patrolMessage');
        const statusValue = document.getElementById('patrolStatusValue');
        const clearHistoryBtn = document.getElementById('clearPatrolHistoryBtn');

        if (enabledCheckbox) enabledCheckbox.checked = config.enabled;
        if (intervalInput) intervalInput.value = config.interval;
        if (messageInput) messageInput.value = config.message;

        updatePatrolStatus(config.enabled);
        renderPatrolHistory();

        if (config.enabled) {
            startPatrolTask(config);
        }

        // Clear history button
        clearHistoryBtn?.addEventListener('click', clearPatrolHistory);

        // Event listeners
        enabledCheckbox?.addEventListener('change', function() {
            const newConfig = {
                enabled: this.checked,
                interval: parseInt(intervalInput?.value) || 5,
                message: messageInput?.value || 'Please check task progress.'
            };
            savePatrolConfig(newConfig);
            updatePatrolStatus(newConfig.enabled);

            if (newConfig.enabled) {
                startPatrolTask(newConfig);
                showToast('Patrol Task', 'Patrol task enabled', 'success', 2000);
            } else {
                stopPatrolTask();
                showToast('Patrol Task', 'Patrol task disabled', 'info', 2000);
            }
        });

        intervalInput?.addEventListener('change', function() {
            const config = loadPatrolConfig();
            config.interval = parseInt(this.value) || 5;
            savePatrolConfig(config);
            if (config.enabled) {
                stopPatrolTask();
                startPatrolTask(config);
            }
        });

        messageInput?.addEventListener('change', function() {
            const config = loadPatrolConfig();
            config.message = this.value || 'Please check task progress.';
            savePatrolConfig(config);
        });
    }

    function updatePatrolStatus(enabled) {
        const statusValue = document.getElementById('patrolStatusValue');
        if (statusValue) {
            statusValue.textContent = enabled ? 'Active' : 'Disabled';
            statusValue.classList.toggle('active', enabled);
        }
    }

    function startPatrolTask(config) {
        stopPatrolTask(); // Clear any existing timer

        if (!config.enabled || !config.interval) return;

        const intervalMs = config.interval * 60 * 1000;

        patrolTimer = setInterval(() => {
            if (state.ws && state.ws.readyState === WebSocket.OPEN && !state.isLoading) {
                console.log('[Patrol] Sending patrol message');
                sendMessage(config.message);
                addPatrolHistoryEntry(config.message);
            }
        }, intervalMs);

        console.log(`[Patrol] Started with interval: ${config.interval} minutes`);
    }

    function stopPatrolTask() {
        if (patrolTimer) {
            clearInterval(patrolTimer);
            patrolTimer = null;
            console.log('[Patrol] Stopped');
        }
    }

    // ============================================
    // Scheduled Tasks Configuration
    // ============================================
    const SCHEDULED_TASKS_KEY = 'jarvis_scheduled_tasks';
    const SCHEDULED_TASKS_ENABLED_KEY = 'jarvis_scheduled_tasks_enabled';
    let scheduledTaskTimers = [];
    let scheduledTasksEnabled = false;

    function loadScheduledTasks() {
        try {
            const data = localStorage.getItem(SCHEDULED_TASKS_KEY);
            if (data) {
                return JSON.parse(data);
            }
        } catch (e) {
            console.warn('Failed to load scheduled tasks:', e);
        }
        return [];
    }

    function saveScheduledTasks(tasks) {
        try {
            localStorage.setItem(SCHEDULED_TASKS_KEY, JSON.stringify(tasks));
        } catch (e) {
            console.warn('Failed to save scheduled tasks:', e);
        }
    }

    function renderScheduledTasks() {
        const list = document.getElementById('scheduledTaskList');
        if (!list) return;

        const tasks = loadScheduledTasks();

        if (tasks.length === 0) {
            list.innerHTML = '<div class="drawer-empty-state">No scheduled tasks</div>';
            return;
        }

        list.innerHTML = tasks.map((task, index) => `
            <div class="scheduled-task-item" data-index="${index}">
                <div class="scheduled-task-info">
                    <span class="scheduled-task-time">${task.time}</span>
                    <span class="scheduled-task-preview">${escapeHtml(task.message.substring(0, 30))}${task.message.length > 30 ? '...' : ''}</span>
                </div>
                ${task.repeat ? '<span class="scheduled-task-badge">Daily</span>' : '<span class="scheduled-task-badge">Once</span>'}
                <div class="scheduled-task-actions">
                    <button class="scheduled-task-action-btn" onclick="window.editScheduledTask(${index})" title="Edit">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                        </svg>
                    </button>
                    <button class="scheduled-task-action-btn delete" onclick="window.deleteScheduledTask(${index})" title="Delete">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="18" y1="6" x2="6" y2="18"></line>
                            <line x1="6" y1="6" x2="18" y2="18"></line>
                        </svg>
                    </button>
                </div>
            </div>
        `).join('');
    }

    // Edit scheduled task
    let editingScheduledTaskIndex = -1;

    window.editScheduledTask = function(index) {
        const tasks = loadScheduledTasks();
        if (index < 0 || index >= tasks.length) return;

        const task = tasks[index];
        editingScheduledTaskIndex = index;

        // Open modal with existing data
        const modal = document.getElementById('scheduledTaskModal');
        const timeInput = document.getElementById('scheduledTaskTime');
        const messageInput = document.getElementById('scheduledTaskMessage');
        const repeatInput = document.getElementById('scheduledTaskRepeat');

        if (timeInput) timeInput.value = task.time;
        if (messageInput) messageInput.value = task.message;
        if (repeatInput) repeatInput.checked = task.repeat || false;

        // Update modal title
        const modalTitle = modal?.querySelector('.modal-header h3');
        if (modalTitle) modalTitle.textContent = 'Edit Scheduled Task';

        modal?.classList.add('active');
    };

    function initScheduledTasks() {
        // Load enabled state
        scheduledTasksEnabled = localStorage.getItem(SCHEDULED_TASKS_ENABLED_KEY) === 'true';

        const enabledToggle = document.getElementById('scheduledTasksEnabled');
        if (enabledToggle) {
            enabledToggle.checked = scheduledTasksEnabled;
            enabledToggle.addEventListener('change', () => {
                scheduledTasksEnabled = enabledToggle.checked;
                localStorage.setItem(SCHEDULED_TASKS_ENABLED_KEY, scheduledTasksEnabled);
                scheduleAllTasks();
                showToast('Scheduled Tasks', scheduledTasksEnabled ? 'Enabled' : 'Disabled', 'info', 2000);
            });
        }

        renderScheduledTasks();
        scheduleAllTasks();

        const addBtn = document.getElementById('addScheduledTaskBtn');
        const modal = document.getElementById('scheduledTaskModal');
        const closeBtn = document.getElementById('closeScheduledTaskModalBtn');
        const cancelBtn = document.getElementById('cancelScheduledTaskBtn');
        const saveBtn = document.getElementById('saveScheduledTaskBtn');

        addBtn?.addEventListener('click', () => {
            editingScheduledTaskIndex = -1; // Reset editing index
            // Update modal title
            const modalTitle = modal?.querySelector('.modal-header h3');
            if (modalTitle) modalTitle.textContent = 'Add Scheduled Task';

            modal?.classList.add('active');
            document.getElementById('scheduledTaskTime').value = '';
            document.getElementById('scheduledTaskMessage').value = '';
            document.getElementById('scheduledTaskRepeat').checked = false;
        });

        closeBtn?.addEventListener('click', () => modal?.classList.remove('active'));
        cancelBtn?.addEventListener('click', () => modal?.classList.remove('active'));
        modal?.querySelector('.modal-backdrop')?.addEventListener('click', () => modal?.classList.remove('active'));

        saveBtn?.addEventListener('click', saveNewScheduledTask);
    }

    function saveNewScheduledTask() {
        const timeInput = document.getElementById('scheduledTaskTime');
        const messageInput = document.getElementById('scheduledTaskMessage');
        const repeatInput = document.getElementById('scheduledTaskRepeat');

        const time = timeInput?.value;
        const message = messageInput?.value.trim();
        const repeat = repeatInput?.checked || false;

        if (!time) {
            showToast('Error', 'Please select a time', 'error');
            timeInput?.classList.add('error');
            return;
        }
        timeInput?.classList.remove('error');

        if (!message) {
            showToast('Error', 'Please enter a message', 'error');
            messageInput?.classList.add('error');
            return;
        }
        messageInput?.classList.remove('error');

        const tasks = loadScheduledTasks();

        if (editingScheduledTaskIndex >= 0 && editingScheduledTaskIndex < tasks.length) {
            // Update existing task
            tasks[editingScheduledTaskIndex] = {
                ...tasks[editingScheduledTaskIndex],
                time: time,
                message: message,
                repeat: repeat
            };
            showToast('Scheduled Task', `Task updated for ${time}`, 'success', 2000);
        } else {
            // Create new task
            tasks.push({
                id: Date.now().toString(),
                time: time,
                message: message,
                repeat: repeat,
                enabled: true
            });
            showToast('Scheduled Task', `Task scheduled for ${time}`, 'success', 2000);
        }

        saveScheduledTasks(tasks);
        renderScheduledTasks();
        scheduleAllTasks();

        editingScheduledTaskIndex = -1; // Reset editing index
        document.getElementById('scheduledTaskModal')?.classList.remove('active');
    }

    window.deleteScheduledTask = function(index) {
        const tasks = loadScheduledTasks();
        if (index >= 0 && index < tasks.length) {
            tasks.splice(index, 1);
            saveScheduledTasks(tasks);
            renderScheduledTasks();
            scheduleAllTasks();
            showToast('Deleted', 'Scheduled task removed', 'info', 2000);
        }
    };

    function scheduleAllTasks() {
        // Clear existing timers
        scheduledTaskTimers.forEach(timer => clearTimeout(timer));
        scheduledTaskTimers = [];

        // Check global toggle
        if (!scheduledTasksEnabled) {
            console.log('[Scheduled] Scheduled tasks disabled');
            return;
        }

        const tasks = loadScheduledTasks();

        tasks.forEach((task, index) => {
            if (!task.enabled) return;

            const scheduleTask = () => {
                const now = new Date();
                const [hours, minutes] = task.time.split(':').map(Number);
                const targetTime = new Date();
                targetTime.setHours(hours, minutes, 0, 0);

                // If time has passed today, schedule for tomorrow
                if (targetTime <= now) {
                    targetTime.setDate(targetTime.getDate() + 1);
                }

                const delay = targetTime.getTime() - now.getTime();

                const timer = setTimeout(() => {
                    if (state.ws && state.ws.readyState === WebSocket.OPEN && !state.isLoading) {
                        console.log(`[Scheduled] Executing task at ${task.time}`);
                        sendMessage(task.message);
                    }

                    if (task.repeat) {
                        // Reschedule for next day
                        scheduleTask();
                    } else {
                        // Remove one-time task after execution
                        const currentTasks = loadScheduledTasks();
                        const taskIndex = currentTasks.findIndex(t => t.id === task.id);
                        if (taskIndex >= 0) {
                            currentTasks.splice(taskIndex, 1);
                            saveScheduledTasks(currentTasks);
                            renderScheduledTasks();
                        }
                    }
                }, delay);

                scheduledTaskTimers.push(timer);
                console.log(`[Scheduled] Task scheduled for ${task.time} (in ${Math.round(delay / 60000)} minutes)`);
            };

            scheduleTask();
        });
    }

    // Initialize drawer event listeners
    function initStatusDrawer() {
        statusDrawerToggle?.addEventListener('click', toggleStatusDrawer);
        closeStatusDrawerBtn?.addEventListener('click', closeStatusDrawer);
        statusDrawer?.querySelector('.status-drawer-backdrop')?.addEventListener('click', closeStatusDrawer);

        // Refresh tasks button in drawer
        document.getElementById('refreshTasksBtn')?.addEventListener('click', () => {
            const btn = document.getElementById('refreshTasksBtn');
            btn?.classList.add('refreshing');
            loadTasksForDrawer().finally(() => {
                setTimeout(() => {
                    btn?.classList.remove('refreshing');
                }, 500);
            });
        });

        // Register task button
        document.getElementById('registerTaskBtn')?.addEventListener('click', registerNewTask);

        // Initialize task filters
        initTaskFilters();

        // Collapse/expand sections
        document.querySelectorAll('.drawer-collapse-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                const targetId = this.dataset.target;
                const targetEl = document.getElementById(targetId);
                if (targetEl) {
                    targetEl.classList.toggle('collapsed');
                    this.classList.toggle('collapsed');
                }
            });
        });

        // Initialize patrol and scheduled tasks
        initPatrolTask();
        initScheduledTasks();

        // Enhanced keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            // Check if user is typing in an input field
            const isTyping = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName);

            // Escape to close drawer/modals
            if (e.key === 'Escape') {
                if (statusDrawer?.classList.contains('visible')) {
                    closeStatusDrawer();
                    e.preventDefault();
                }
                // Also close any open modals
                const activeModal = document.querySelector('.modal.active, .modal.visible');
                if (activeModal) {
                    activeModal.classList.remove('active', 'visible');
                    e.preventDefault();
                }
            }

            // Only handle other shortcuts when not typing
            if (!isTyping) {
                // T to toggle task drawer
                if (e.key === 't' || e.key === 'T') {
                    toggleStatusDrawer();
                    e.preventDefault();
                }
                // R to refresh tasks (when drawer is open)
                if ((e.key === 'r' || e.key === 'R') && statusDrawer?.classList.contains('visible')) {
                    document.getElementById('refreshTasksBtn')?.click();
                    e.preventDefault();
                }
            }
        });
    }

    // Override handleTaskUpdate to also update drawer
    const originalHandleTaskUpdate = handleTaskUpdate;
    function enhancedHandleTaskUpdate(data) {
        if (typeof originalHandleTaskUpdate === 'function') {
            // Call original
            console.log('Task update:', data.event, data.task);

            const prevTasks = [...state.tasks];

            if (data.all_tasks) {
                state.tasks = data.all_tasks;
            } else if (data.task) {
                const index = state.tasks.findIndex(t => t.task_id === data.task.task_id);
                if (index >= 0) {
                    if (data.event === 'removed' || data.event === 'completed') {
                        state.tasks.splice(index, 1);
                    } else {
                        state.tasks[index] = data.task;
                    }
                } else if (data.event === 'registered') {
                    state.tasks.push(data.task);
                }
            }

            renderTasks();

            // Show notifications for task events
            if (data.task && data.event) {
                const taskId = data.task.task_id;
                const desc = data.task.description || taskId;

                switch (data.event) {
                    case 'completed':
                        showToast('Task Completed', desc, 'success');
                        break;
                    case 'blocked':
                        showToast('Task Blocked', `${desc}: ${data.task.block_reason || 'Unknown reason'}`, 'warning');
                        break;
                    case 'timeout':
                        showToast('Task Timeout', desc, 'error');
                        break;
                    case 'registered':
                        showToast('Task Started', desc, 'info', 2000);
                        break;
                }
            }
        }

        // Also update drawer
        renderDrawerTasks();
        updateTaskBadge();
    }

    // ============================================
    // Initialize
    // ============================================
    async function init() {
        // Initialize theme
        initTheme();

        // Initialize i18n if available
        if (window.i18n) {
            window.i18n.initLanguage();
            window.i18n.updateDOM();

            // Listen for language changes
            window.addEventListener('languagechange', () => {
                window.i18n.updateDOM();
            });
        }

        // Initialize edit modal
        initEditModal();

        // Initialize keyboard shortcuts
        initKeyboardShortcuts();

        // Initialize mobile menu
        initMobileMenu();

        // Initialize status drawer
        initStatusDrawer();

        // Initialize enhanced drag & drop
        initEnhancedDragDrop();

        // Initialize virtual scroll manager
        virtualScrollManager = new VirtualScrollManager(
            elements.messagesContainer,
            elements.messagesWrapper,
            VIRTUAL_SCROLL_CONFIG
        );
        virtualScrollManager.init();

        // Event listeners
        elements.sendBtn.addEventListener('click', handleSend);
        elements.messageInput.addEventListener('keydown', handleKeydown);
        elements.messageInput.addEventListener('input', handleInput);
        elements.messageInput.addEventListener('paste', handlePaste);
        elements.newChatBtn.addEventListener('click', createNewSession);

        // Attachment handling
        elements.attachBtn.addEventListener('click', handleAttachClick);
        elements.fileInput.addEventListener('change', handleFileSelect);

        // Local drag & drop listeners (for input area visual feedback)
        const container = elements.inputContainer;
        container.addEventListener('dragover', handleDragOver);
        container.addEventListener('dragleave', handleDragLeave);
        container.addEventListener('drop', handleDrop);

        // Initial state
        updateButtonState();

        // Claude sessions 列表在 WebSocket 连接后由 loadCurrentSessionMessages 加载

        // 加载任务列表
        await loadTasks();
        renderDrawerTasks();
        updateTaskBadge();

        // Task refresh button
        const taskRefreshBtn = document.getElementById('taskRefreshBtn');
        if (taskRefreshBtn) {
            taskRefreshBtn.addEventListener('click', handleTaskRefresh);
        }

        // Connect WebSocket（连接后从服务端加载当前 session 消息）
        connectWebSocket();

        // Periodic task polling (every 30 seconds as fallback)
        setInterval(loadTasks, 30000);

        // Update elapsed time display every second
        setInterval(() => {
            if (state.tasks.length > 0) {
                renderTasks();
            }
        }, 1000);

        // Focus input
        elements.messageInput.focus();

        // Load bookmarks
        loadBookmarks();

        // Search event listeners
        searchToggleBtn?.addEventListener('click', toggleSearch);
        searchCloseBtn?.addEventListener('click', closeSearch);
        searchInput?.addEventListener('input', (e) => performSearch(e.target.value));
        searchInput?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                if (e.shiftKey) {
                    searchPrev();
                } else {
                    searchNext();
                }
            }
            if (e.key === 'Escape') {
                closeSearch();
            }
        });
        searchPrevBtn?.addEventListener('click', searchPrev);
        searchNextBtn?.addEventListener('click', searchNext);

        // Bookmarks event listeners
        bookmarksToggleBtn?.addEventListener('click', toggleBookmarksPanel);
        closeBookmarksBtn?.addEventListener('click', closeBookmarksPanel);
        clearBookmarksBtn?.addEventListener('click', clearAllBookmarks);
        bookmarksPanel?.querySelector('.bookmarks-backdrop')?.addEventListener('click', closeBookmarksPanel);

        // Export event listener
        exportBtn?.addEventListener('click', exportToMarkdown);

        // Observe for new messages to enhance code blocks
        const observer = new MutationObserver((mutations) => {
            mutations.forEach(() => {
                enhanceCodeBlocks();
            });
        });
        observer.observe(elements.messagesWrapper, { childList: true, subtree: true });

        console.log('Claude Agent Chat initialized');
    }

    // Start the application
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
