/**
 * Jarvis 控制台
 */

// State
const state = {
    instances: [],
    tools: [],
    mcpServers: [],
    availableTools: [],
    selectedInstance: null,
    currentDetailInstance: null,
    refreshInterval: null
};

// DOM Elements
const elements = {
    totalInstances: document.getElementById('totalInstances'),
    healthyInstances: document.getElementById('healthyInstances'),
    processingInstances: document.getElementById('processingInstances'),
    stoppedInstances: document.getElementById('stoppedInstances'),
    instancesGrid: document.getElementById('instancesGrid'),
    toolsGrid: document.getElementById('toolsGrid'),
    refreshBtn: document.getElementById('refreshBtn'),
    restartAllBtn: document.getElementById('restartAllBtn'),
    lastUpdate: document.getElementById('lastUpdate'),
    // Message Modal
    messageModal: document.getElementById('messageModal'),
    modalInstanceId: document.getElementById('modalInstanceId'),
    messageInput: document.getElementById('messageInput'),
    modalClose: document.getElementById('modalClose'),
    modalCancel: document.getElementById('modalCancel'),
    modalSend: document.getElementById('modalSend'),
    // Detail Modal
    instanceDetailModal: document.getElementById('instanceDetailModal'),
    detailInstanceId: document.getElementById('detailInstanceId'),
    detailStatus: document.getElementById('detailStatus'),
    detailSessionId: document.getElementById('detailSessionId'),
    detailQueueSize: document.getElementById('detailQueueSize'),
    detailLastActive: document.getElementById('detailLastActive'),
    detailModalClose: document.getElementById('detailModalClose'),
    detailCancelBtn: document.getElementById('detailCancelBtn'),
    detailSaveBtn: document.getElementById('detailSaveBtn'),
    detailDeleteBtn: document.getElementById('detailDeleteBtn'),
    // Config fields
    configModel: document.getElementById('configModel'),
    configPermissionMode: document.getElementById('configPermissionMode'),
    configMcpEnabled: document.getElementById('configMcpEnabled'),
    mcpServersGrid: document.getElementById('mcpServersGrid'),
    toolsCheckboxGrid: document.getElementById('toolsCheckboxGrid'),
    configSystemPrompt: document.getElementById('configSystemPrompt'),
    // New Instance Modal
    newInstanceBtn: document.getElementById('newInstanceBtn'),
    newInstanceModal: document.getElementById('newInstanceModal'),
    newInstanceClose: document.getElementById('newInstanceClose'),
    newInstanceCancel: document.getElementById('newInstanceCancel'),
    newInstanceCreate: document.getElementById('newInstanceCreate'),
    newInstanceId: document.getElementById('newInstanceId'),
    newConfigModel: document.getElementById('newConfigModel'),
    newConfigPermissionMode: document.getElementById('newConfigPermissionMode'),
    newConfigMcpEnabled: document.getElementById('newConfigMcpEnabled')
};

// API Functions
async function fetchInstances() {
    try {
        const response = await fetch('/api/instances');
        if (!response.ok) throw new Error('Failed to fetch instances');
        return await response.json();
    } catch (error) {
        console.error('Error fetching instances:', error);
        return [];
    }
}

async function fetchMCPTools() {
    try {
        const response = await fetch('/mcp/mcp', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json, text/event-stream'
            },
            body: JSON.stringify({
                jsonrpc: '2.0',
                id: 1,
                method: 'tools/list'
            })
        });
        if (!response.ok) throw new Error('Failed to fetch tools');

        const text = await response.text();
        const lines = text.split('\n');
        for (const line of lines) {
            if (line.startsWith('data: ')) {
                const data = JSON.parse(line.slice(6));
                return data.result?.tools || [];
            }
        }
        return [];
    } catch (error) {
        console.error('Error fetching MCP tools:', error);
        return [];
    }
}

async function fetchMCPServers() {
    try {
        const response = await fetch('/api/mcp-servers');
        if (!response.ok) throw new Error('Failed to fetch MCP servers');
        return await response.json();
    } catch (error) {
        console.error('Error fetching MCP servers:', error);
        return [];
    }
}

async function fetchAvailableTools() {
    try {
        const response = await fetch('/api/available-tools');
        if (!response.ok) throw new Error('Failed to fetch available tools');
        return await response.json();
    } catch (error) {
        console.error('Error fetching available tools:', error);
        return [];
    }
}

async function fetchInstanceConfig(instanceId) {
    try {
        const response = await fetch(`/api/instances/${encodeURIComponent(instanceId)}/config`);
        if (!response.ok) {
            if (response.status === 404) {
                return { merged_config: {}, instance_overrides: {} };
            }
            throw new Error('Failed to fetch config');
        }
        return await response.json();
    } catch (error) {
        console.error('Error fetching instance config:', error);
        return { merged_config: {}, instance_overrides: {} };
    }
}

async function saveInstanceConfig(instanceId, config) {
    try {
        const response = await fetch(`/api/instances/${encodeURIComponent(instanceId)}/config`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        if (!response.ok) throw new Error('Failed to save config');
        return await response.json();
    } catch (error) {
        console.error('Error saving config:', error);
        throw error;
    }
}

async function createInstance(data) {
    try {
        const response = await fetch('/api/instances', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Failed to create instance');
        }
        return await response.json();
    } catch (error) {
        console.error('Error creating instance:', error);
        throw error;
    }
}

async function deleteInstance(instanceId) {
    try {
        const response = await fetch(`/api/instances/${encodeURIComponent(instanceId)}`, {
            method: 'DELETE'
        });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Failed to delete instance');
        }
        return await response.json();
    } catch (error) {
        console.error('Error deleting instance:', error);
        throw error;
    }
}

async function restartInstance(instanceId) {
    try {
        const response = await fetch(`/api/restart?instance_id=${encodeURIComponent(instanceId)}`, {
            method: 'POST'
        });
        if (!response.ok) throw new Error('Failed to restart instance');
        return await response.json();
    } catch (error) {
        console.error('Error restarting instance:', error);
        throw error;
    }
}

async function sendMessage(instanceId, message) {
    try {
        const response = await fetch(`/api/instances/${encodeURIComponent(instanceId)}/send`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, source: 'dashboard' })
        });
        if (!response.ok) throw new Error('Failed to send message');
        return await response.json();
    } catch (error) {
        console.error('Error sending message:', error);
        throw error;
    }
}

// Render Functions
function updateSummary() {
    const total = state.instances.length;
    const healthy = state.instances.filter(i => i.status === 'healthy').length;
    const processing = state.instances.filter(i => i.is_processing).length;
    const stopped = state.instances.filter(i => i.status === 'stopped').length;

    elements.totalInstances.textContent = total;
    elements.healthyInstances.textContent = healthy;
    elements.processingInstances.textContent = processing;
    elements.stoppedInstances.textContent = stopped;
}

function formatTimestamp(timestamp) {
    if (!timestamp) return '\u2014';
    const date = new Date(timestamp * 1000);
    const now = new Date();
    const diff = Math.floor((now - date) / 1000);

    if (diff < 60) return '\u521a\u521a';
    if (diff < 3600) return `${Math.floor(diff / 60)} \u5206\u949f\u524d`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} \u5c0f\u65f6\u524d`;
    return date.toLocaleDateString('zh-CN');
}

function statusText(instance) {
    if (instance.is_processing) return '\u5904\u7406\u4e2d';
    const map = { healthy: '\u8fd0\u884c\u4e2d', stopped: '\u5df2\u505c\u6b62', dead: '\u5df2\u5d29\u6e83' };
    return map[instance.status] || instance.status;
}

function statusClass(instance) {
    return instance.is_processing ? 'processing' : instance.status;
}

function createInstanceCard(instance) {
    const cls = statusClass(instance);
    const card = document.createElement('div');
    card.className = 'instance-card';
    card.innerHTML = `
        <div class="card-top">
            <span class="card-name">${escapeHtml(instance.instance_id)}</span>
            <span class="card-badge ${cls}">
                <span class="badge-dot"></span>
                ${statusText(instance)}
            </span>
        </div>
        <div class="card-meta">
            <div class="meta-row">
                <span class="meta-label">\u961f\u5217</span>
                <span class="meta-value">${instance.queue_size} \u6761\u6d88\u606f</span>
            </div>
            <div class="meta-row">
                <span class="meta-label">\u4f1a\u8bdd</span>
                <span class="meta-value">${instance.session_id ? instance.session_id.slice(0, 8) + '\u2026' : '\u2014'}</span>
            </div>
            <div class="meta-row">
                <span class="meta-label">\u6700\u540e\u6d3b\u8dc3</span>
                <span class="meta-value">${formatTimestamp(instance.last_active_at)}</span>
            </div>
        </div>
        <div class="card-actions">
            <button class="card-action action-message" data-id="${escapeHtml(instance.instance_id)}" ${instance.status === 'stopped' ? 'disabled' : ''}>
                \u2709 \u6d88\u606f
            </button>
            <button class="card-action action-restart" data-id="${escapeHtml(instance.instance_id)}" ${instance.status === 'stopped' ? 'disabled' : ''}>
                \u21bb \u91cd\u542f
            </button>
            ${instance.instance_id.startsWith('ws-') ? `
                <a href="/?instance=${encodeURIComponent(instance.instance_id)}" class="card-action action-chat">
                    \u2192 \u5bf9\u8bdd
                </a>
            ` : ''}
        </div>
    `;

    card.addEventListener('click', (e) => {
        if (e.target.closest('.card-action') || e.target.closest('a')) return;
        openDetailModal(instance);
    });

    const messageBtn = card.querySelector('.action-message');
    const restartBtn = card.querySelector('.action-restart');

    messageBtn?.addEventListener('click', (e) => {
        e.stopPropagation();
        openMessageModal(instance.instance_id);
    });
    restartBtn?.addEventListener('click', (e) => {
        e.stopPropagation();
        handleRestart(instance.instance_id);
    });

    return card;
}

function renderInstances() {
    if (state.instances.length === 0) {
        elements.instancesGrid.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">\u25cb</div>
                <p>\u6682\u65e0\u5b9e\u4f8b</p>
                <p style="font-size: 0.85rem; margin-top: 6px; color: var(--text-tertiary);">\u70b9\u51fb\u201c\u65b0\u5efa\u5b9e\u4f8b\u201d\u521b\u5efa\u7b2c\u4e00\u4e2a</p>
            </div>
        `;
        return;
    }

    elements.instancesGrid.innerHTML = '';
    state.instances.forEach(instance => {
        elements.instancesGrid.appendChild(createInstanceCard(instance));
    });
}

function getToolCategory(toolName) {
    if (toolName.startsWith('browser_')) return 'Browser';
    if (toolName.startsWith('jarvis_')) return 'Jarvis';
    return 'Other';
}

function renderTools() {
    if (state.tools.length === 0) {
        elements.toolsGrid.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">\u2699</div>
                <p>\u65e0 MCP \u5de5\u5177</p>
            </div>
        `;
        return;
    }

    elements.toolsGrid.innerHTML = '';

    const categories = {};
    state.tools.forEach(tool => {
        const category = getToolCategory(tool.name);
        if (!categories[category]) categories[category] = [];
        categories[category].push(tool);
    });

    Object.entries(categories).forEach(([category, tools]) => {
        tools.forEach(tool => {
            const chip = document.createElement('div');
            chip.className = 'tool-chip';
            chip.innerHTML = `
                <span class="chip-category">${category}</span>
                ${escapeHtml(tool.name)}
            `;
            chip.title = tool.description || '';
            elements.toolsGrid.appendChild(chip);
        });
    });
}

function renderMCPServersCheckboxes(disabledList = []) {
    if (state.mcpServers.length === 0) {
        elements.mcpServersGrid.innerHTML = '<p class="no-mcp-servers">\u672a\u627e\u5230 MCP \u670d\u52a1\u5668</p>';
        return;
    }

    elements.mcpServersGrid.innerHTML = '';
    state.mcpServers.forEach(server => {
        const isEnabled = !disabledList.includes(server.name);
        const sourceLabel = server.source === 'user' ? 'USER' : 'PROJECT';
        const sourceClass = server.source === 'user' ? 'source-user' : 'source-project';
        const item = document.createElement('div');
        item.className = 'chip-item';
        item.innerHTML = `
            <input type="checkbox" id="mcp_${escapeHtml(server.name)}"
                   data-server="${escapeHtml(server.name)}"
                   ${isEnabled ? 'checked' : ''}>
            <label for="mcp_${escapeHtml(server.name)}">${escapeHtml(server.name)}</label>
            <span class="source-badge ${sourceClass}">${sourceLabel}</span>
        `;
        elements.mcpServersGrid.appendChild(item);
    });

    updateMcpGridState();
}

function renderToolsCheckboxes(allowedTools = []) {
    elements.toolsCheckboxGrid.innerHTML = '';
    state.availableTools.forEach(tool => {
        const isAllowed = allowedTools.length === 0 || allowedTools.includes(tool.id);
        const item = document.createElement('div');
        item.className = 'chip-item';
        item.innerHTML = `
            <input type="checkbox" id="tool_${escapeHtml(tool.id)}"
                   data-tool="${escapeHtml(tool.id)}"
                   ${isAllowed ? 'checked' : ''}>
            <label for="tool_${escapeHtml(tool.id)}" title="${escapeHtml(tool.description || '')}">${escapeHtml(tool.name)}</label>
        `;
        elements.toolsCheckboxGrid.appendChild(item);
    });
}

function updateMcpGridState() {
    const isEnabled = elements.configMcpEnabled.checked;
    elements.mcpServersGrid.classList.toggle('disabled', !isEnabled);
}

function updateTimestamp() {
    const now = new Date();
    const h = String(now.getHours()).padStart(2, '0');
    const m = String(now.getMinutes()).padStart(2, '0');
    const s = String(now.getSeconds()).padStart(2, '0');
    elements.lastUpdate.textContent = `${h}:${m}:${s}`;
}

// Event Handlers
async function handleRefresh() {
    elements.refreshBtn.disabled = true;
    const svg = elements.refreshBtn.querySelector('svg');
    if (svg) svg.style.animation = 'spin 0.6s linear infinite';

    try {
        const [instances, tools, mcpServers, availableTools] = await Promise.all([
            fetchInstances(),
            fetchMCPTools(),
            fetchMCPServers(),
            fetchAvailableTools()
        ]);

        state.instances = instances;
        state.tools = tools;
        state.mcpServers = mcpServers;
        state.availableTools = availableTools;

        updateSummary();
        renderInstances();
        renderTools();
        updateTimestamp();
    } catch (error) {
        console.error('Refresh failed:', error);
    } finally {
        elements.refreshBtn.disabled = false;
        if (svg) svg.style.animation = '';
    }
}

async function handleRestart(instanceId) {
    if (!confirm(`\u786e\u8ba4\u91cd\u542f\u5b9e\u4f8b\u201c${instanceId}\u201d\uff1f\n\n\u5c06\u91cd\u65b0\u52a0\u8f7d\u914d\u7f6e\uff0c\u4f46\u4fdd\u7559\u5bf9\u8bdd\u8bb0\u5f55\u3002`)) {
        return;
    }

    try {
        await restartInstance(instanceId);
        await handleRefresh();
    } catch (error) {
        alert(`\u91cd\u542f\u5931\u8d25\uff1a${error.message}`);
    }
}

async function handleRestartAll() {
    const activeInstances = state.instances.filter(i => i.status !== 'stopped');
    if (activeInstances.length === 0) {
        alert('\u6ca1\u6709\u8fd0\u884c\u4e2d\u7684\u5b9e\u4f8b\u3002');
        return;
    }

    if (!confirm(`\u786e\u8ba4\u91cd\u542f\u5168\u90e8 ${activeInstances.length} \u4e2a\u5b9e\u4f8b\uff1f`)) {
        return;
    }

    try {
        await Promise.all(activeInstances.map(i => restartInstance(i.instance_id)));
        await handleRefresh();
    } catch (error) {
        alert(`\u90e8\u5206\u91cd\u542f\u5931\u8d25\uff1a${error.message}`);
    }
}

// Message Modal
function openMessageModal(instanceId) {
    state.selectedInstance = instanceId;
    elements.modalInstanceId.textContent = instanceId;
    elements.messageInput.value = '';
    elements.messageModal.classList.add('active');
    elements.messageInput.focus();
}

function closeMessageModal() {
    state.selectedInstance = null;
    elements.messageModal.classList.remove('active');
}

async function handleSendMessage() {
    const message = elements.messageInput.value.trim();
    if (!message || !state.selectedInstance) return;

    try {
        await sendMessage(state.selectedInstance, message);
        closeMessageModal();
        await handleRefresh();
    } catch (error) {
        alert(`\u53d1\u9001\u5931\u8d25\uff1a${error.message}`);
    }
}

// Detail Modal
async function openDetailModal(instance) {
    state.currentDetailInstance = instance;
    elements.detailInstanceId.textContent = instance.instance_id;

    elements.detailStatus.textContent = statusText(instance);
    elements.detailSessionId.textContent = instance.session_id ? instance.session_id.slice(0, 16) + '\u2026' : '\u2014';
    elements.detailQueueSize.textContent = `${instance.queue_size} \u6761\u6d88\u606f`;
    elements.detailLastActive.textContent = formatTimestamp(instance.last_active_at);

    const { merged_config, instance_overrides } = await fetchInstanceConfig(instance.instance_id);

    elements.configModel.value = merged_config.model || 'sonnet';
    elements.configPermissionMode.value = merged_config.permission_mode || 'bypassPermissions';
    elements.configMcpEnabled.checked = merged_config.mcp_enabled !== false;

    const disabledMcp = merged_config.mcp_servers_disabled || [];
    renderMCPServersCheckboxes(disabledMcp);

    const allowedTools = merged_config.allowed_tools || [];
    renderToolsCheckboxes(allowedTools);

    elements.configSystemPrompt.value = instance_overrides.system_prompt || '';

    elements.instanceDetailModal.classList.add('active');
}

function closeDetailModal() {
    state.currentDetailInstance = null;
    elements.instanceDetailModal.classList.remove('active');
}

async function handleSaveConfig() {
    if (!state.currentDetailInstance) return;

    const instanceId = state.currentDetailInstance.instance_id;

    const config = {
        model: elements.configModel.value,
        permission_mode: elements.configPermissionMode.value,
        mcp_enabled: elements.configMcpEnabled.checked
    };

    const disabledMcp = [];
    elements.mcpServersGrid.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        if (!cb.checked) disabledMcp.push(cb.dataset.server);
    });
    config.mcp_servers_disabled = disabledMcp;

    const allowedTools = [];
    elements.toolsCheckboxGrid.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        if (cb.checked) allowedTools.push(cb.dataset.tool);
    });
    config.allowed_tools = allowedTools;

    const systemPrompt = elements.configSystemPrompt.value.trim();
    if (systemPrompt) config.system_prompt = systemPrompt;

    try {
        elements.detailSaveBtn.disabled = true;
        elements.detailSaveBtn.textContent = '\u4fdd\u5b58\u4e2d\u2026';

        const result = await saveInstanceConfig(instanceId, config);

        if (result.restarted) {
            alert('\u914d\u7f6e\u5df2\u4fdd\u5b58\uff0c\u5b9e\u4f8b\u5df2\u91cd\u542f\u3002');
        } else {
            alert('\u914d\u7f6e\u5df2\u4fdd\u5b58\uff0c\u4e0b\u6b21\u542f\u52a8\u65f6\u751f\u6548\u3002');
        }

        closeDetailModal();
        await handleRefresh();
    } catch (error) {
        alert(`\u4fdd\u5b58\u5931\u8d25\uff1a${error.message}`);
    } finally {
        elements.detailSaveBtn.disabled = false;
        elements.detailSaveBtn.textContent = '\u4fdd\u5b58\u5e76\u91cd\u542f';
    }
}

async function handleDeleteInstance() {
    if (!state.currentDetailInstance) return;

    const instanceId = state.currentDetailInstance.instance_id;

    if (!confirm(`\u786e\u8ba4\u5220\u9664\u5b9e\u4f8b\u201c${instanceId}\u201d\uff1f\n\n\u5c06\u5220\u9664\u914d\u7f6e\u6587\u4ef6\uff0c\u6b64\u64cd\u4f5c\u4e0d\u53ef\u64a4\u9500\u3002`)) {
        return;
    }

    try {
        await deleteInstance(instanceId);
        alert(`\u5b9e\u4f8b\u201c${instanceId}\u201d\u5df2\u5220\u9664\u3002`);
        closeDetailModal();
        await handleRefresh();
    } catch (error) {
        alert(`\u5220\u9664\u5931\u8d25\uff1a${error.message}`);
    }
}

// New Instance Modal
function openNewInstanceModal() {
    elements.newInstanceId.value = '';
    elements.newConfigModel.value = 'sonnet';
    elements.newConfigPermissionMode.value = 'bypassPermissions';
    elements.newConfigMcpEnabled.checked = true;
    elements.newInstanceModal.classList.add('active');
    elements.newInstanceId.focus();
}

function closeNewInstanceModal() {
    elements.newInstanceModal.classList.remove('active');
}

async function handleCreateInstance() {
    const instanceId = elements.newInstanceId.value.trim();
    if (!instanceId) {
        alert('\u8bf7\u8f93\u5165\u5b9e\u4f8b ID');
        return;
    }

    if (!/^[a-zA-Z0-9_-]+$/.test(instanceId)) {
        alert('\u5b9e\u4f8b ID \u53ea\u80fd\u5305\u542b\u5b57\u6bcd\u3001\u6570\u5b57\u3001\u8fde\u5b57\u7b26\u548c\u4e0b\u5212\u7ebf');
        return;
    }

    const data = {
        instance_id: instanceId,
        model: elements.newConfigModel.value,
        permission_mode: elements.newConfigPermissionMode.value,
        mcp_enabled: elements.newConfigMcpEnabled.checked,
        mcp_servers_disabled: [],
        allowed_tools: state.availableTools.map(t => t.id)
    };

    try {
        elements.newInstanceCreate.disabled = true;
        elements.newInstanceCreate.textContent = '\u521b\u5efa\u4e2d\u2026';

        await createInstance(data);
        alert(`\u5b9e\u4f8b\u201c${instanceId}\u201d\u5df2\u521b\u5efa\u3002`);
        closeNewInstanceModal();
        await handleRefresh();
    } catch (error) {
        alert(`\u521b\u5efa\u5931\u8d25\uff1a${error.message}`);
    } finally {
        elements.newInstanceCreate.disabled = false;
        elements.newInstanceCreate.textContent = '\u521b\u5efa';
    }
}

// Utilities
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Initialize
function init() {
    elements.refreshBtn.addEventListener('click', handleRefresh);
    elements.restartAllBtn.addEventListener('click', handleRestartAll);
    elements.modalClose.addEventListener('click', closeMessageModal);
    elements.modalCancel.addEventListener('click', closeMessageModal);
    elements.modalSend.addEventListener('click', handleSendMessage);

    elements.messageModal.addEventListener('click', (e) => {
        if (e.target === elements.messageModal) closeMessageModal();
    });

    elements.messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) handleSendMessage();
    });

    elements.detailModalClose.addEventListener('click', closeDetailModal);
    elements.detailCancelBtn.addEventListener('click', closeDetailModal);
    elements.detailSaveBtn.addEventListener('click', handleSaveConfig);
    elements.detailDeleteBtn.addEventListener('click', handleDeleteInstance);

    elements.instanceDetailModal.addEventListener('click', (e) => {
        if (e.target === elements.instanceDetailModal) closeDetailModal();
    });

    elements.configMcpEnabled.addEventListener('change', updateMcpGridState);

    elements.newInstanceBtn.addEventListener('click', openNewInstanceModal);
    elements.newInstanceClose.addEventListener('click', closeNewInstanceModal);
    elements.newInstanceCancel.addEventListener('click', closeNewInstanceModal);
    elements.newInstanceCreate.addEventListener('click', handleCreateInstance);

    elements.newInstanceModal.addEventListener('click', (e) => {
        if (e.target === elements.newInstanceModal) closeNewInstanceModal();
    });

    elements.newInstanceId.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') handleCreateInstance();
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            if (elements.messageModal.classList.contains('active')) closeMessageModal();
            if (elements.instanceDetailModal.classList.contains('active')) closeDetailModal();
            if (elements.newInstanceModal.classList.contains('active')) closeNewInstanceModal();
        }
    });

    handleRefresh();
    state.refreshInterval = setInterval(handleRefresh, 30000);
}

document.addEventListener('DOMContentLoaded', init);
