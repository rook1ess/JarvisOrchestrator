/**
 * Jarvis Dashboard - Instance Registry
 * Parchment Scroll Style Dashboard
 */

// State
const state = {
    instances: [],
    tools: [],
    selectedInstance: null,
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
    messageModal: document.getElementById('messageModal'),
    modalInstanceId: document.getElementById('modalInstanceId'),
    messageInput: document.getElementById('messageInput'),
    modalClose: document.getElementById('modalClose'),
    modalCancel: document.getElementById('modalCancel'),
    modalSend: document.getElementById('modalSend')
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

    // Event listeners
    const messageBtn = card.querySelector('.instance-btn.message');
    const restartBtn = card.querySelector('.instance-btn.restart');

    messageBtn?.addEventListener('click', () => openMessageModal(instance.instance_id));
    restartBtn?.addEventListener('click', () => handleRestart(instance.instance_id));

    return card;
}

function renderInstances() {
    if (state.instances.length === 0) {
        elements.instancesGrid.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">☽</div>
                <p>No instances found</p>
                <p style="font-size: 0.9rem; margin-top: 8px;">Send a message to create one</p>
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

function updateTimestamp() {
    const now = new Date();
    elements.lastUpdate.textContent = `Last updated: ${now.toLocaleTimeString()}`;
}

// Event Handlers
async function handleRefresh() {
    elements.refreshBtn.disabled = true;
    elements.refreshBtn.innerHTML = '<span class="refresh-icon" style="animation: spin 0.5s linear infinite;">↻</span> Loading...';

    try {
        const [instances, tools] = await Promise.all([
            fetchInstances(),
            fetchMCPTools()
        ]);

        state.instances = instances;
        state.tools = tools;

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

// Utilities
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Initialize
function init() {
    // Event listeners
    elements.refreshBtn.addEventListener('click', handleRefresh);
    elements.restartAllBtn.addEventListener('click', handleRestartAll);
    elements.modalClose.addEventListener('click', closeMessageModal);
    elements.modalCancel.addEventListener('click', closeMessageModal);
    elements.modalSend.addEventListener('click', handleSendMessage);

    // Close modal on overlay click
    elements.messageModal.addEventListener('click', (e) => {
        if (e.target === elements.messageModal) closeMessageModal();
    });

    // Send on Enter (with Ctrl/Cmd)
    elements.messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            handleSendMessage();
        }
    });

    // Close modal on Escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && elements.messageModal.classList.contains('active')) {
            closeMessageModal();
        }
    });

    // Initial load
    handleRefresh();

    // Auto refresh every 30 seconds
    state.refreshInterval = setInterval(handleRefresh, 30000);
}

// Start
document.addEventListener('DOMContentLoaded', init);
