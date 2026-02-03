/**
 * Internationalization (i18n) Module
 * Multi-language support framework for Claude Agent SDK
 */

(function() {
    'use strict';

    const I18N_STORAGE_KEY = 'jarvis_language';

    // Language definitions
    const languages = {
        en: {
            name: 'English',
            nativeName: 'English',
            dir: 'ltr'
        },
        zh: {
            name: 'Chinese',
            nativeName: '中文',
            dir: 'ltr'
        },
        ja: {
            name: 'Japanese',
            nativeName: '日本語',
            dir: 'ltr'
        },
        ko: {
            name: 'Korean',
            nativeName: '한국어',
            dir: 'ltr'
        },
        es: {
            name: 'Spanish',
            nativeName: 'Español',
            dir: 'ltr'
        },
        fr: {
            name: 'French',
            nativeName: 'Français',
            dir: 'ltr'
        },
        de: {
            name: 'German',
            nativeName: 'Deutsch',
            dir: 'ltr'
        }
    };

    // Translation strings
    const translations = {
        en: {
            // Header
            'header.title': 'Agent Terminal',
            'header.role': 'Role:',

            // Sidebar
            'sidebar.newSession': 'Initialize Session',
            'sidebar.agentProfile': 'Agent Profile',
            'sidebar.sessionArchive': 'Session Archive',
            'sidebar.noSessions': '// No sessions yet',
            'sidebar.online': 'ONLINE',
            'sidebar.connecting': 'Connecting...',
            'sidebar.disconnected': 'Disconnected',

            // Welcome
            'welcome.title': 'System Ready',
            'welcome.subtitle': '// Initialize connection with Agent',

            // Input
            'input.placeholder': 'Enter command...',
            'input.hint': 'ENTER to transmit // SHIFT+ENTER for new line',
            'input.attachFile': 'Attach file',
            'input.send': 'Send message',
            'input.stop': 'Stop generating',

            // Messages
            'message.you': 'You',
            'message.agent': 'Agent',
            'message.stopped': '[Stopped by user]',
            'message.contextCompacted': '[Context compacted]',
            'message.edit': 'Edit',
            'message.copy': 'Copy',
            'message.bookmark': 'Bookmark',
            'message.regenerate': 'Regenerate',

            // Search
            'search.placeholder': 'Search messages...',
            'search.noResults': 'No results found',

            // Bookmarks
            'bookmarks.title': 'Bookmarked Messages',
            'bookmarks.empty': 'No bookmarked messages yet.',
            'bookmarks.emptyHint': 'Click the bookmark icon on any message to save it.',
            'bookmarks.clearAll': 'Clear All',

            // Modals
            'modal.rename.title': 'Rename Session',
            'modal.rename.label': 'Session Name',
            'modal.rename.placeholder': 'Enter session name',
            'modal.rename.cancel': 'Cancel',
            'modal.rename.save': 'Save',

            'modal.delete.title': 'Delete Session',
            'modal.delete.confirm': 'Are you sure you want to delete this session?',
            'modal.delete.cancel': 'Cancel',
            'modal.delete.delete': 'Delete',

            'modal.edit.title': 'Edit Message',
            'modal.edit.cancel': 'Cancel',
            'modal.edit.save': 'Save & Resend',

            // Shortcuts
            'shortcuts.title': 'Keyboard Shortcuts',
            'shortcuts.navigation': 'Navigation',
            'shortcuts.session': 'Session',
            'shortcuts.display': 'Display',
            'shortcuts.input': 'Input',
            'shortcuts.focusInput': 'Focus message input',
            'shortcuts.clearInput': 'Clear & focus input',
            'shortcuts.searchMessages': 'Search messages',
            'shortcuts.viewBookmarks': 'View bookmarks',
            'shortcuts.exportChat': 'Export chat',
            'shortcuts.openSettings': 'Open settings',
            'shortcuts.newSession': 'New session',
            'shortcuts.stopGeneration': 'Stop generation',
            'shortcuts.toggleTheme': 'Toggle theme',
            'shortcuts.showShortcuts': 'Show shortcuts',
            'shortcuts.sendMessage': 'Send message',
            'shortcuts.newLine': 'New line',

            // Tasks
            'tasks.title': 'Active Tasks',
            'tasks.refresh': 'Refresh tasks',

            // Toasts
            'toast.sessionCreated': 'Session Created',
            'toast.sessionCreatedMsg': 'New session initialized',
            'toast.renamed': 'Renamed',
            'toast.renamedMsg': 'Session renamed successfully',
            'toast.deleted': 'Deleted',
            'toast.deletedMsg': 'Session deleted successfully',
            'toast.copied': 'Copied',
            'toast.copiedMsg': 'Content copied to clipboard',
            'toast.bookmarked': 'Bookmarked',
            'toast.bookmarkedMsg': 'Message saved to bookmarks',
            'toast.removed': 'Removed',
            'toast.removedMsg': 'Bookmark removed',
            'toast.cleared': 'Cleared',
            'toast.clearedMsg': 'All bookmarks removed',
            'toast.exported': 'Exported',
            'toast.themeChanged': 'Theme Changed',
            'toast.themeDark': 'Switched to dark mode',
            'toast.themeLight': 'Switched to light mode',
            'toast.error': 'Error',
            'toast.unsupportedFile': 'File type not supported',
            'toast.messageSent': 'Message sent',
            'toast.messageEdited': 'Message edited',

            // Drag & Drop
            'dragdrop.title': 'Drop files here',
            'dragdrop.subtitle': 'Release to upload images and documents',

            // Status
            'status.ready': 'Ready',
            'status.processing': 'Processing...',
            'status.thinking': 'Thinking...',
            'status.connecting': 'Connecting...',
            'status.switching': 'Switching...',
            'status.creating': 'Creating...',
            'status.error': 'Error',

            // Export
            'export.title': 'Chat Export',
            'export.agent': 'Agent',
            'export.date': 'Date',
            'export.messages': 'Messages',
            'export.bookmarkedMessages': 'Bookmarked Messages',
            'export.bookmark': 'Bookmark',

            // Settings
            'settings.title': 'System Config',
            'settings.language': 'Language'
        },

        zh: {
            // Header
            'header.title': '代理终端',
            'header.role': '角色:',

            // Sidebar
            'sidebar.newSession': '初始化会话',
            'sidebar.agentProfile': '代理配置',
            'sidebar.sessionArchive': '会话存档',
            'sidebar.noSessions': '// 暂无会话',
            'sidebar.online': '在线',
            'sidebar.connecting': '连接中...',
            'sidebar.disconnected': '已断开',

            // Welcome
            'welcome.title': '系统就绪',
            'welcome.subtitle': '// 初始化与代理的连接',

            // Input
            'input.placeholder': '输入命令...',
            'input.hint': 'ENTER 发送 // SHIFT+ENTER 换行',
            'input.attachFile': '附加文件',
            'input.send': '发送消息',
            'input.stop': '停止生成',

            // Messages
            'message.you': '你',
            'message.agent': '代理',
            'message.stopped': '[已被用户停止]',
            'message.contextCompacted': '[上下文已压缩]',
            'message.edit': '编辑',
            'message.copy': '复制',
            'message.bookmark': '书签',
            'message.regenerate': '重新生成',

            // Search
            'search.placeholder': '搜索消息...',
            'search.noResults': '未找到结果',

            // Bookmarks
            'bookmarks.title': '已收藏的消息',
            'bookmarks.empty': '暂无收藏的消息。',
            'bookmarks.emptyHint': '点击任意消息上的收藏图标来保存。',
            'bookmarks.clearAll': '清除全部',

            // Modals
            'modal.rename.title': '重命名会话',
            'modal.rename.label': '会话名称',
            'modal.rename.placeholder': '输入会话名称',
            'modal.rename.cancel': '取消',
            'modal.rename.save': '保存',

            'modal.delete.title': '删除会话',
            'modal.delete.confirm': '确定要删除此会话吗?',
            'modal.delete.cancel': '取消',
            'modal.delete.delete': '删除',

            'modal.edit.title': '编辑消息',
            'modal.edit.cancel': '取消',
            'modal.edit.save': '保存并重发',

            // Shortcuts
            'shortcuts.title': '键盘快捷键',
            'shortcuts.navigation': '导航',
            'shortcuts.session': '会话',
            'shortcuts.display': '显示',
            'shortcuts.input': '输入',
            'shortcuts.focusInput': '聚焦消息输入',
            'shortcuts.clearInput': '清空并聚焦输入',
            'shortcuts.searchMessages': '搜索消息',
            'shortcuts.viewBookmarks': '查看书签',
            'shortcuts.exportChat': '导出聊天',
            'shortcuts.openSettings': '打开设置',
            'shortcuts.newSession': '新建会话',
            'shortcuts.stopGeneration': '停止生成',
            'shortcuts.toggleTheme': '切换主题',
            'shortcuts.showShortcuts': '显示快捷键',
            'shortcuts.sendMessage': '发送消息',
            'shortcuts.newLine': '换行',

            // Tasks
            'tasks.title': '活动任务',
            'tasks.refresh': '刷新任务',

            // Toasts
            'toast.sessionCreated': '会话已创建',
            'toast.sessionCreatedMsg': '新会话已初始化',
            'toast.renamed': '已重命名',
            'toast.renamedMsg': '会话重命名成功',
            'toast.deleted': '已删除',
            'toast.deletedMsg': '会话删除成功',
            'toast.copied': '已复制',
            'toast.copiedMsg': '内容已复制到剪贴板',
            'toast.bookmarked': '已收藏',
            'toast.bookmarkedMsg': '消息已保存到书签',
            'toast.removed': '已移除',
            'toast.removedMsg': '书签已移除',
            'toast.cleared': '已清除',
            'toast.clearedMsg': '所有书签已清除',
            'toast.exported': '已导出',
            'toast.themeChanged': '主题已更改',
            'toast.themeDark': '已切换到深色模式',
            'toast.themeLight': '已切换到浅色模式',
            'toast.error': '错误',
            'toast.unsupportedFile': '不支持的文件类型',
            'toast.messageSent': '消息已发送',
            'toast.messageEdited': '消息已编辑',

            // Drag & Drop
            'dragdrop.title': '拖放文件到此处',
            'dragdrop.subtitle': '释放以上传图片和文档',

            // Status
            'status.ready': '就绪',
            'status.processing': '处理中...',
            'status.thinking': '思考中...',
            'status.connecting': '连接中...',
            'status.switching': '切换中...',
            'status.creating': '创建中...',
            'status.error': '错误',

            // Export
            'export.title': '聊天导出',
            'export.agent': '代理',
            'export.date': '日期',
            'export.messages': '消息数',
            'export.bookmarkedMessages': '收藏的消息',
            'export.bookmark': '书签',

            // Settings
            'settings.title': '系统配置',
            'settings.language': '语言'
        },

        ja: {
            // Header
            'header.title': 'エージェントターミナル',
            'header.role': 'ロール:',

            // Sidebar
            'sidebar.newSession': 'セッション初期化',
            'sidebar.agentProfile': 'エージェントプロファイル',
            'sidebar.sessionArchive': 'セッションアーカイブ',
            'sidebar.noSessions': '// セッションなし',
            'sidebar.online': 'オンライン',
            'sidebar.connecting': '接続中...',
            'sidebar.disconnected': '切断されました',

            // Welcome
            'welcome.title': 'システム準備完了',
            'welcome.subtitle': '// エージェントとの接続を初期化',

            // Input
            'input.placeholder': 'コマンドを入力...',
            'input.hint': 'ENTER で送信 // SHIFT+ENTER で改行',
            'input.attachFile': 'ファイルを添付',
            'input.send': 'メッセージを送信',
            'input.stop': '生成を停止',

            // Messages
            'message.you': 'あなた',
            'message.agent': 'エージェント',
            'message.stopped': '[ユーザーにより停止]',
            'message.contextCompacted': '[コンテキスト圧縮済み]',
            'message.edit': '編集',
            'message.copy': 'コピー',
            'message.bookmark': 'ブックマーク',
            'message.regenerate': '再生成',

            // Search
            'search.placeholder': 'メッセージを検索...',
            'search.noResults': '結果が見つかりません',

            // Bookmarks
            'bookmarks.title': 'ブックマークしたメッセージ',
            'bookmarks.empty': 'ブックマークしたメッセージはありません。',
            'bookmarks.emptyHint': 'メッセージのブックマークアイコンをクリックして保存。',
            'bookmarks.clearAll': 'すべてクリア',

            // Status
            'status.ready': '準備完了',
            'status.processing': '処理中...',
            'status.thinking': '思考中...',
            'status.connecting': '接続中...',
            'status.error': 'エラー',

            // Toasts
            'toast.copied': 'コピーしました',
            'toast.copiedMsg': 'クリップボードにコピーしました',
            'toast.error': 'エラー'
        },

        ko: {
            'header.title': '에이전트 터미널',
            'header.role': '역할:',
            'sidebar.newSession': '세션 초기화',
            'welcome.title': '시스템 준비 완료',
            'welcome.subtitle': '// 에이전트와 연결 초기화',
            'input.placeholder': '명령 입력...',
            'message.you': '사용자',
            'message.agent': '에이전트',
            'status.ready': '준비됨',
            'toast.copied': '복사됨',
            'toast.error': '오류'
        },

        es: {
            'header.title': 'Terminal de Agente',
            'header.role': 'Rol:',
            'sidebar.newSession': 'Iniciar Sesion',
            'welcome.title': 'Sistema Listo',
            'welcome.subtitle': '// Inicializando conexion con el Agente',
            'input.placeholder': 'Ingresa un comando...',
            'message.you': 'Tu',
            'message.agent': 'Agente',
            'status.ready': 'Listo',
            'toast.copied': 'Copiado',
            'toast.error': 'Error'
        },

        fr: {
            'header.title': 'Terminal Agent',
            'header.role': 'Role:',
            'sidebar.newSession': 'Initialiser Session',
            'welcome.title': 'Systeme Pret',
            'welcome.subtitle': '// Initialisation de la connexion avec l\'Agent',
            'input.placeholder': 'Entrez une commande...',
            'message.you': 'Vous',
            'message.agent': 'Agent',
            'status.ready': 'Pret',
            'toast.copied': 'Copie',
            'toast.error': 'Erreur'
        },

        de: {
            'header.title': 'Agent Terminal',
            'header.role': 'Rolle:',
            'sidebar.newSession': 'Sitzung Initialisieren',
            'welcome.title': 'System Bereit',
            'welcome.subtitle': '// Verbindung mit Agent initialisieren',
            'input.placeholder': 'Befehl eingeben...',
            'message.you': 'Du',
            'message.agent': 'Agent',
            'status.ready': 'Bereit',
            'toast.copied': 'Kopiert',
            'toast.error': 'Fehler'
        }
    };

    // Current language
    let currentLanguage = 'en';

    // Get stored language or detect from browser
    function getInitialLanguage() {
        const stored = localStorage.getItem(I18N_STORAGE_KEY);
        if (stored && languages[stored]) {
            return stored;
        }

        // Detect from browser
        const browserLang = navigator.language || navigator.userLanguage;
        const shortLang = browserLang.split('-')[0];

        if (languages[shortLang]) {
            return shortLang;
        }

        return 'en';
    }

    // Initialize language
    function initLanguage() {
        currentLanguage = getInitialLanguage();
        document.documentElement.setAttribute('lang', currentLanguage);
        document.documentElement.setAttribute('dir', languages[currentLanguage]?.dir || 'ltr');
    }

    // Get translation
    function t(key, params = {}) {
        let text = translations[currentLanguage]?.[key]
                || translations['en']?.[key]
                || key;

        // Replace parameters
        Object.keys(params).forEach(param => {
            text = text.replace(new RegExp(`{${param}}`, 'g'), params[param]);
        });

        return text;
    }

    // Set language
    function setLanguage(lang) {
        if (!languages[lang]) {
            console.warn(`Language '${lang}' not supported`);
            return false;
        }

        currentLanguage = lang;
        localStorage.setItem(I18N_STORAGE_KEY, lang);
        document.documentElement.setAttribute('lang', lang);
        document.documentElement.setAttribute('dir', languages[lang].dir);

        // Dispatch event for UI update
        window.dispatchEvent(new CustomEvent('languagechange', {
            detail: { language: lang }
        }));

        return true;
    }

    // Get current language
    function getLanguage() {
        return currentLanguage;
    }

    // Get all available languages
    function getAvailableLanguages() {
        return Object.entries(languages).map(([code, info]) => ({
            code,
            ...info
        }));
    }

    // Update all translatable elements in DOM
    function updateDOM() {
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            el.textContent = t(key);
        });

        document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
            const key = el.getAttribute('data-i18n-placeholder');
            el.placeholder = t(key);
        });

        document.querySelectorAll('[data-i18n-title]').forEach(el => {
            const key = el.getAttribute('data-i18n-title');
            el.title = t(key);
        });
    }

    // Export to global scope
    window.i18n = {
        t,
        setLanguage,
        getLanguage,
        getAvailableLanguages,
        initLanguage,
        updateDOM,
        languages
    };

    // Auto-initialize
    initLanguage();
})();
