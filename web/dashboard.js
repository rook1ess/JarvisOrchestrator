/**
 * Jarvis Dashboard - Instance Registry
 * Parchment Scroll Style Dashboard
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

        // Parse SSE response - extract the JSON from the event stream
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
                // No config file, return defaults
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
    if (!timestamp) return '—';
    const date = new Date(timestamp * 1000);
    const now = new Date();
    const diff = Math.floor((now - date) / 1000);

    if (diff < 60) return 'Just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return date.toLocaleDateString();
}

function createInstanceCard(instance) {
    const statusClass = instance.is_processing ? 'processing' : instance.status;
    const statusText = instance.is_processing ? 'Processing' :
                       instance.status.charAt(0).toUpperCase() + instance.status.slice(1);

    const card = document.createElement('div');
    card.className = `instance-card ${statusClass}`;
    card.innerHTML = `
        <div class="instance-header">
            <span class="instance-name">${escapeHtml(instance.instance_id)}</span>
            <span class="instance-status ${statusClass}">
                <span class="status-dot"></span>
                ${statusText}
            </span>
        </div>
        <div class="instance-details">
            <div class="detail-row">
                <span class="detail-label">Queue</span>
                <span class="detail-value">${instance.queue_size} messages</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Session</span>
                <span class="detail-value">${instance.session_id ? instance.session_id.slice(0, 8) + '...' : '—'}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Last Active</span>
                <span class="detail-value">${formatTimestamp(instance.last_active_at)}</span>
            </div>
        </div>
        <div class="instance-actions">
            <button class="instance-btn message" data-id="${escapeHtml(instance.instance_id)}" ${instance.status === 'stopped' ? 'disabled' : ''}>
                ✉ Message
            </button>
            <button class="instance-btn restart" data-id="${escapeHtml(instance.instance_id)}" ${instance.status === 'stopped' ? 'disabled' : ''}>
                ↻ Restart
            </button>
            ${instance.instance_id.startsWith('ws-') ? `
                <a href="/?instance=${encodeURIComponent(instance.instance_id)}" class="instance-btn chat">
                    → Chat
                </a>
            ` : ''}
        </div>
    `;

    // Click on card (not buttons) opens detail modal
    card.addEventListener('click', (e) => {
        // Don't open detail if clicking on action buttons or links
        if (e.target.closest('.instance-btn') || e.target.closest('a')) {
            return;
        }
        openDetailModal(instance);
    });

    // Event listeners for buttons
    const messageBtn = card.querySelector('.instance-btn.message');
    const restartBtn = card.querySelector('.instance-btn.restart');

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
                <div class="empty-icon">☽</div>
                <p>No instances found</p>
                <p style="font-size: 0.9rem; margin-top: 8px;">Click "+ New Instance" to create one</p>
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
                <div class="empty-icon">⚙</div>
                <p>No MCP tools available</p>
            </div>
        `;
        return;
    }

    elements.toolsGrid.innerHTML = '';

    // Group by category
    const categories = {};
    state.tools.forEach(tool => {
        const category = getToolCategory(tool.name);
        if (!categories[category]) categories[category] = [];
        categories[category].push(tool);
    });

    // Render tools
    Object.entries(categories).forEach(([category, tools]) => {
        tools.forEach(tool => {
            const card = document.createElement('div');
            card.className = 'tool-card';
            card.innerHTML = `
                <div class="tool-name">${escapeHtml(tool.name)}</div>
                <div class="tool-category">${category}</div>
            `;
            card.title = tool.description || '';
            elements.toolsGrid.appendChild(card);
        });
    });
}

function renderMCPServersCheckboxes(disabledList = []) {
    if (state.mcpServers.length === 0) {
        elements.mcpServersGrid.innerHTML = '<p class="no-mcp-servers">No MCP servers found</p>';
        return;
    }

    elements.mcpServersGrid.innerHTML = '';
    state.mcpServers.forEach(server => {
        const isEnabled = !disabledList.includes(server.name);
        const sourceLabel = server.source === 'user' ? 'USER' : 'PROJECT';
        const sourceClass = server.source === 'user' ? 'source-user' : 'source-project';
        const item = document.createElement('div');
        item.className = 'mcp-server-item';
        item.innerHTML = `
            <input type="checkbox" id="mcp_${escapeHtml(server.name)}"
                   data-server="${escapeHtml(server.name)}"
                   ${isEnabled ? 'checked' : ''}>
            <label for="mcp_${escapeHtml(server.name)}">${escapeHtml(server.name)}</label>
            <span class="server-source ${sourceClass}">${sourceLabel}</span>
        `;
        elements.mcpServersGrid.appendChild(item);
    });

    // Update disabled state based on MCP enabled checkbox
    updateMcpGridState();
}

function renderToolsCheckboxes(allowedTools = []) {
    elements.toolsCheckboxGrid.innerHTML = '';
    state.availableTools.forEach(tool => {
        const isAllowed = allowedTools.length === 0 || allowedTools.includes(tool.id);
        const item = document.createElement('div');
        item.className = 'tool-checkbox-item';
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
    elements.lastUpdate.textContent = `Last updated: ${now.toLocaleTimeString()}`;
}

// Event Handlers
async function handleRefresh() {
    elements.refreshBtn.disabled = true;
    elements.refreshBtn.innerHTML = '<span class="refresh-icon" style="animation: spin 0.5s linear infinite;">↻</span> Loading...';

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
        elements.refreshBtn.innerHTML = '<span class="refresh-icon">↻</span> Refresh';
    }
}

async function handleRestart(instanceId) {
    if (!confirm(`Restart instance "${instanceId}"?\n\nThis will reload configuration but preserve the conversation.`)) {
        return;
    }

    try {
        await restartInstance(instanceId);
        await handleRefresh();
    } catch (error) {
        alert(`Failed to restart instance: ${error.message}`);
    }
}

async function handleRestartAll() {
    const activeInstances = state.instances.filter(i => i.status !== 'stopped');
    if (activeInstances.length === 0) {
        alert('No active instances to restart.');
        return;
    }

    if (!confirm(`Restart all ${activeInstances.length} active instance(s)?`)) {
        return;
    }

    try {
        await Promise.all(
            activeInstances.map(i => restartInstance(i.instance_id))
        );
        await handleRefresh();
    } catch (error) {
        alert(`Some restarts failed: ${error.message}`);
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
        alert(`Failed to send message: ${error.message}`);
    }
}

// Detail Modal
async function openDetailModal(instance) {
    state.currentDetailInstance = instance;
    elements.detailInstanceId.textContent = instance.instance_id;

    // Fill status section
    const statusText = instance.is_processing ? 'Processing' :
                       instance.status.charAt(0).toUpperCase() + instance.status.slice(1);
    elements.detailStatus.textContent = statusText;
    elements.detailSessionId.textContent = instance.session_id ? instance.session_id.slice(0, 16) + '...' : '—';
    elements.detailQueueSize.textContent = `${instance.queue_size} messages`;
    elements.detailLastActive.textContent = formatTimestamp(instance.last_active_at);

    // Fetch and fill config
    const { merged_config, instance_overrides } = await fetchInstanceConfig(instance.instance_id);

    // Model
    elements.configModel.value = merged_config.model || 'sonnet';

    // Permission mode
    elements.configPermissionMode.value = merged_config.permission_mode || 'bypassPermissions';

    // MCP enabled
    elements.configMcpEnabled.checked = merged_config.mcp_enabled !== false;

    // MCP servers (show checkboxes with disabled ones unchecked)
    const disabledMcp = merged_config.mcp_servers_disabled || [];
    renderMCPServersCheckboxes(disabledMcp);

    // Tools
    const allowedTools = merged_config.allowed_tools || [];
    renderToolsCheckboxes(allowedTools);

    // System prompt (only show override, not merged)
    elements.configSystemPrompt.value = instance_overrides.system_prompt || '';

    // Show modal
    elements.instanceDetailModal.classList.add('active');
}

function closeDetailModal() {
    state.currentDetailInstance = null;
    elements.instanceDetailModal.classList.remove('active');
}

async function handleSaveConfig() {
    if (!state.currentDetailInstance) return;

    const instanceId = state.currentDetailInstance.instance_id;

    // Collect config values
    const config = {
        model: elements.configModel.value,
        permission_mode: elements.configPermissionMode.value,
        mcp_enabled: elements.configMcpEnabled.checked
    };

    // Collect disabled MCP servers (unchecked ones)
    const disabledMcp = [];
    elements.mcpServersGrid.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        if (!cb.checked) {
            disabledMcp.push(cb.dataset.server);
        }
    });
    config.mcp_servers_disabled = disabledMcp;

    // Collect allowed tools (checked ones)
    const allowedTools = [];
    elements.toolsCheckboxGrid.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        if (cb.checked) {
            allowedTools.push(cb.dataset.tool);
        }
    });
    config.allowed_tools = allowedTools;

    // System prompt (only if not empty)
    const systemPrompt = elements.configSystemPrompt.value.trim();
    if (systemPrompt) {
        config.system_prompt = systemPrompt;
    }

    try {
        elements.detailSaveBtn.disabled = true;
        elements.detailSaveBtn.textContent = 'Saving...';

        const result = await saveInstanceConfig(instanceId, config);

        if (result.restarted) {
            alert(`Configuration saved and instance restarted successfully.`);
        } else {
            alert(`Configuration saved. Instance will use new config on next start.`);
        }

        closeDetailModal();
        await handleRefresh();
    } catch (error) {
        alert(`Failed to save configuration: ${error.message}`);
    } finally {
        elements.detailSaveBtn.disabled = false;
        elements.detailSaveBtn.textContent = 'Save & Restart';
    }
}

async function handleDeleteInstance() {
    if (!state.currentDetailInstance) return;

    const instanceId = state.currentDetailInstance.instance_id;

    if (!confirm(`Delete instance "${instanceId}"?\n\nThis will remove the configuration file. This action cannot be undone.`)) {
        return;
    }

    try {
        await deleteInstance(instanceId);
        alert(`Instance "${instanceId}" deleted.`);
        closeDetailModal();
        await handleRefresh();
    } catch (error) {
        alert(`Failed to delete instance: ${error.message}`);
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
        alert('Please enter an instance ID');
        return;
    }

    // Validate instance ID format
    if (!/^[a-zA-Z0-9_-]+$/.test(instanceId)) {
        alert('Instance ID can only contain letters, numbers, hyphens, and underscores');
        return;
    }

    const data = {
        instance_id: instanceId,
        model: elements.newConfigModel.value,
        permission_mode: elements.newConfigPermissionMode.value,
        mcp_enabled: elements.newConfigMcpEnabled.checked,
        mcp_servers_disabled: [],
        allowed_tools: state.availableTools.map(t => t.id) // Enable all tools by default
    };

    try {
        elements.newInstanceCreate.disabled = true;
        elements.newInstanceCreate.textContent = 'Creating...';

        await createInstance(data);
        alert(`Instance "${instanceId}" created successfully.`);
        closeNewInstanceModal();
        await handleRefresh();
    } catch (error) {
        alert(`Failed to create instance: ${error.message}`);
    } finally {
        elements.newInstanceCreate.disabled = false;
        elements.newInstanceCreate.textContent = 'Create';
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
    // Message Modal listeners
    elements.refreshBtn.addEventListener('click', handleRefresh);
    elements.restartAllBtn.addEventListener('click', handleRestartAll);
    elements.modalClose.addEventListener('click', closeMessageModal);
    elements.modalCancel.addEventListener('click', closeMessageModal);
    elements.modalSend.addEventListener('click', handleSendMessage);

    elements.messageModal.addEventListener('click', (e) => {
        if (e.target === elements.messageModal) closeMessageModal();
    });

    elements.messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            handleSendMessage();
        }
    });

    // Detail Modal listeners
    elements.detailModalClose.addEventListener('click', closeDetailModal);
    elements.detailCancelBtn.addEventListener('click', closeDetailModal);
    elements.detailSaveBtn.addEventListener('click', handleSaveConfig);
    elements.detailDeleteBtn.addEventListener('click', handleDeleteInstance);

    elements.instanceDetailModal.addEventListener('click', (e) => {
        if (e.target === elements.instanceDetailModal) closeDetailModal();
    });

    // MCP enabled toggle
    elements.configMcpEnabled.addEventListener('change', updateMcpGridState);

    // New Instance Modal listeners
    elements.newInstanceBtn.addEventListener('click', openNewInstanceModal);
    elements.newInstanceClose.addEventListener('click', closeNewInstanceModal);
    elements.newInstanceCancel.addEventListener('click', closeNewInstanceModal);
    elements.newInstanceCreate.addEventListener('click', handleCreateInstance);

    elements.newInstanceModal.addEventListener('click', (e) => {
        if (e.target === elements.newInstanceModal) closeNewInstanceModal();
    });

    elements.newInstanceId.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            handleCreateInstance();
        }
    });

    // Close modals on Escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            if (elements.messageModal.classList.contains('active')) closeMessageModal();
            if (elements.instanceDetailModal.classList.contains('active')) closeDetailModal();
            if (elements.newInstanceModal.classList.contains('active')) closeNewInstanceModal();
        }
    });

    // Initial load
    handleRefresh();

    // Auto refresh every 30 seconds
    state.refreshInterval = setInterval(handleRefresh, 30000);
}

// Start
document.addEventListener('DOMContentLoaded', init);
