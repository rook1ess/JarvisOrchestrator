/**
 * Settings Page JavaScript
 * Agent 配置管理
 */

// ============================================
// State
// ============================================
let agents = [];
let currentAgent = null;
let availableTools = [];
let availableSubagents = [];
let mcpServers = [];

// ============================================
// DOM Elements
// ============================================
const agentSelect = document.getElementById('agentSelect');
const agentForm = document.getElementById('agentForm');
const newAgentBtn = document.getElementById('newAgentBtn');
const deleteAgentBtn = document.getElementById('deleteAgentBtn');
const importAgentBtn = document.getElementById('importAgentBtn');
const exportAgentBtn = document.getElementById('exportAgentBtn');
const importFileInput = document.getElementById('importFileInput');
const saveBtn = document.getElementById('saveBtn');
const applyConfigBtn = document.getElementById('applyConfigBtn');
const restartBtn = document.getElementById('restartBtn');
const createSubagentBtn = document.getElementById('createSubagentBtn');
const colorPicker = document.getElementById('colorPicker');
const agentColorInput = document.getElementById('agentColor');

// Form fields
const agentId = document.getElementById('agentId');
const agentName = document.getElementById('agentName');
const agentDescription = document.getElementById('agentDescription');
const systemPrompt = document.getElementById('systemPrompt');
const mcpServersInput = document.getElementById('mcpServers');
const mcpEnabledInput = document.getElementById('mcpEnabled');
const mcpServersGroup = document.getElementById('mcpServersGroup');
const builtinToolsContainer = document.getElementById('builtinTools');
const mcpToolsContainer = document.getElementById('mcpTools');
const subagentsContainer = document.getElementById('subagentsList');

// Modal
const modal = document.getElementById('newAgentModal');
const closeModalBtn = document.getElementById('closeModalBtn');
const cancelModalBtn = document.getElementById('cancelModalBtn');
const confirmCreateBtn = document.getElementById('confirmCreateBtn');
const newAgentIdInput = document.getElementById('newAgentId');
const newAgentNameInput = document.getElementById('newAgentName');

// Toast
const toast = document.getElementById('toast');

// Delete Agent Modal
const deleteAgentModal = document.getElementById('deleteAgentModal');
const closeDeleteAgentModalBtn = document.getElementById('closeDeleteAgentModalBtn');
const cancelDeleteAgentBtn = document.getElementById('cancelDeleteAgentBtn');
const confirmDeleteAgentBtn = document.getElementById('confirmDeleteAgentBtn');
const deleteAgentConfirmText = document.getElementById('deleteAgentConfirmText');
let agentToDelete = null;

// Theme Toggle
const settingsThemeToggle = document.getElementById('settingsThemeToggle');

// UI Settings Elements
const typewriterSpeedSlider = document.getElementById('typewriterSpeed');
const typewriterSpeedValue = document.getElementById('typewriterSpeedValue');
const fontSizeSlider = document.getElementById('fontSize');
const fontSizeValue = document.getElementById('fontSizeValue');
const themeColorPicker = document.getElementById('themeColorPicker');
const themeColorInput = document.getElementById('themeColor');
const enableTypewriterToggle = document.getElementById('enableTypewriter');
const enableAnimationsToggle = document.getElementById('enableAnimations');
const reducedMotionToggle = document.getElementById('reducedMotion');
const highContrastToggle = document.getElementById('highContrast');

// Avatar Elements
const avatarPreview = document.getElementById('avatarPreview');
const avatarIconGrid = document.getElementById('avatarIconGrid');
const avatarInput = document.getElementById('agentAvatar');
const avatarUploadArea = document.getElementById('avatarUploadArea');
const avatarFileInput = document.getElementById('avatarFileInput');

// UI Settings Storage Key
const UI_SETTINGS_KEY = 'jarvis_ui_settings';

// ============================================
// API Functions
// ============================================
async function fetchAgents() {
    const response = await fetch('/api/agents');
    return await response.json();
}

async function fetchAgent(id) {
    const response = await fetch(`/api/agents/${id}`);
    return await response.json();
}

async function fetchTools() {
    const response = await fetch('/api/tools');
    return await response.json();
}

async function fetchSubagents() {
    const response = await fetch('/api/subagents');
    return await response.json();
}

async function fetchMcpServers(configPath) {
    if (!configPath) return [];
    const response = await fetch(`/api/mcp-servers?config_path=${encodeURIComponent(configPath)}`);
    return await response.json();
}

async function saveAgent(id, data) {
    const method = agents.find(a => a.id === id) ? 'PUT' : 'POST';
    const url = method === 'PUT' ? `/api/agents/${id}` : '/api/agents';

    const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to save');
    }

    return await response.json();
}

async function deleteAgent(id) {
    const response = await fetch(`/api/agents/${id}`, { method: 'DELETE' });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to delete');
    }

    return await response.json();
}

async function applyConfig() {
    // 重启 JARVIS（应用新配置，不重启整个服务器）
    const response = await fetch('/api/restart', { method: 'POST' });
    return await response.json();
}

async function restartServer() {
    // 重启整个服务器
    const response = await fetch('/api/restart-server', { method: 'POST' });
    return await response.json();
}

// ============================================
// UI Functions
// ============================================
function showToast(message, type = 'success') {
    const toastMessage = toast.querySelector('.toast-message');
    toastMessage.textContent = message;
    toast.className = `toast show ${type}`;

    setTimeout(() => {
        toast.className = 'toast';
    }, 3000);
}

function populateAgentSelect() {
    agentSelect.innerHTML = agents.map(a =>
        `<option value="${a.id}">${a.name}</option>`
    ).join('');
}

function renderBuiltinTools() {
    builtinToolsContainer.innerHTML = availableTools.map(tool => `
        <label class="checkbox-item" data-tool="${tool.id}">
            <input type="checkbox" name="tools" value="${tool.id}">
            <div class="checkbox-info">
                <span class="checkbox-name">${tool.name}</span>
                <span class="checkbox-desc">${tool.description}</span>
            </div>
        </label>
    `).join('');

    // Add click handler for visual feedback
    builtinToolsContainer.querySelectorAll('.checkbox-item').forEach(item => {
        const checkbox = item.querySelector('input[type="checkbox"]');
        item.addEventListener('click', (e) => {
            if (e.target !== checkbox) {
                checkbox.checked = !checkbox.checked;
            }
            item.classList.toggle('checked', checkbox.checked);
        });
    });
}

function renderMcpTools() {
    if (mcpServers.length === 0) {
        mcpToolsContainer.innerHTML = '<p style="color: var(--text-muted); font-size: 13px;">No MCP servers configured</p>';
        return;
    }

    mcpToolsContainer.innerHTML = mcpServers.map(server => {
        const toolId = `mcp__${server.id}__*`;
        return `
            <label class="checkbox-item" data-tool="${toolId}">
                <input type="checkbox" name="tools" value="${toolId}">
                <div class="checkbox-info">
                    <span class="checkbox-name">${server.name}</span>
                    <span class="checkbox-desc">${server.url}</span>
                </div>
            </label>
        `;
    }).join('');

    mcpToolsContainer.querySelectorAll('.checkbox-item').forEach(item => {
        const checkbox = item.querySelector('input[type="checkbox"]');
        item.addEventListener('click', (e) => {
            if (e.target !== checkbox) {
                checkbox.checked = !checkbox.checked;
            }
            item.classList.toggle('checked', checkbox.checked);
        });
    });
}

function renderSubagents() {
    if (availableSubagents.length === 0) {
        subagentsContainer.innerHTML = '<p style="color: var(--text-muted); font-size: 13px;">No subagents available</p>';
        return;
    }

    subagentsContainer.innerHTML = availableSubagents.map(sub => `
        <label class="checkbox-item" data-subagent="${sub.id}">
            <input type="checkbox" name="subagents" value="${sub.id}">
            <div class="checkbox-info">
                <span class="checkbox-name">${sub.name}</span>
                <span class="checkbox-desc">${sub.description}</span>
            </div>
        </label>
    `).join('');

    subagentsContainer.querySelectorAll('.checkbox-item').forEach(item => {
        const checkbox = item.querySelector('input[type="checkbox"]');
        item.addEventListener('click', (e) => {
            if (e.target !== checkbox) {
                checkbox.checked = !checkbox.checked;
            }
            item.classList.toggle('checked', checkbox.checked);
        });
    });
}

function populateForm(agent) {
    agentId.value = agent.id;
    agentName.value = agent.name || '';
    agentDescription.value = agent.description || '';
    systemPrompt.value = agent.system_prompt || '';
    mcpServersInput.value = agent.mcp_servers || '';

    // MCP enabled toggle
    const mcpEnabled = agent.mcp_enabled || false;
    if (mcpEnabledInput) {
        mcpEnabledInput.checked = mcpEnabled;
        // Show/hide mcp servers group based on toggle
        if (mcpServersGroup) {
            mcpServersGroup.style.display = mcpEnabled ? 'block' : 'none';
        }
    }

    // Color
    const color = agent.color || '#a67c5b';
    agentColorInput.value = color;
    colorPicker.querySelectorAll('.color-option').forEach(btn => {
        btn.classList.toggle('selected', btn.dataset.color === color);
    });

    // Model
    document.querySelectorAll('input[name="model"]').forEach(radio => {
        radio.checked = radio.value === (agent.model || 'opus');
    });

    // Tools - uncheck all first
    document.querySelectorAll('input[name="tools"]').forEach(cb => {
        cb.checked = false;
        cb.closest('.checkbox-item')?.classList.remove('checked');
    });

    // Check selected tools
    (agent.allowed_tools || []).forEach(tool => {
        const cb = document.querySelector(`input[name="tools"][value="${tool}"]`);
        if (cb) {
            cb.checked = true;
            cb.closest('.checkbox-item')?.classList.add('checked');
        }
    });

    // Subagents - uncheck all first
    document.querySelectorAll('input[name="subagents"]').forEach(cb => {
        cb.checked = false;
        cb.closest('.checkbox-item')?.classList.remove('checked');
    });

    // Check selected subagents
    (agent.subagents || []).forEach(sub => {
        const cb = document.querySelector(`input[name="subagents"][value="${sub}"]`);
        if (cb) {
            cb.checked = true;
            cb.closest('.checkbox-item')?.classList.add('checked');
        }
    });

    // Avatar
    const avatar = agent.avatar || 'layers';
    if (avatarInput) avatarInput.value = avatar;
    updateAvatarPreview(avatar);
    avatarIconGrid?.querySelectorAll('.avatar-icon-option').forEach(btn => {
        btn.classList.toggle('selected', btn.dataset.icon === avatar);
    });

    // Enable/disable ID field
    agentId.readOnly = true;
}

function getFormData() {
    const selectedTools = Array.from(document.querySelectorAll('input[name="tools"]:checked'))
        .map(cb => cb.value);

    const selectedSubagents = Array.from(document.querySelectorAll('input[name="subagents"]:checked'))
        .map(cb => cb.value);

    const selectedModel = document.querySelector('input[name="model"]:checked')?.value || 'opus';

    return {
        id: agentId.value,
        name: agentName.value,
        description: agentDescription.value,
        system_prompt: systemPrompt.value,
        allowed_tools: selectedTools,
        mcp_enabled: mcpEnabledInput?.checked || false,
        mcp_servers: mcpServersInput.value || null,
        model: selectedModel,
        subagents: selectedSubagents,
        color: agentColorInput.value || '#a67c5b',
        avatar: avatarInput?.value || 'layers'
    };
}

function showModal() {
    modal.classList.add('active');
    newAgentIdInput.value = '';
    newAgentNameInput.value = '';
    newAgentIdInput.focus();
}

function hideModal() {
    modal.classList.remove('active');
}

// ============================================
// Event Handlers
// ============================================
async function handleAgentChange() {
    const selectedId = agentSelect.value;
    if (!selectedId) return;

    try {
        currentAgent = await fetchAgent(selectedId);

        // Load MCP servers for this agent's config
        if (currentAgent.mcp_servers) {
            mcpServers = await fetchMcpServers(currentAgent.mcp_servers);
            renderMcpTools();
        }

        populateForm(currentAgent);
    } catch (error) {
        showToast('Failed to load agent: ' + error.message, 'error');
    }
}

async function handleSave(e) {
    e.preventDefault();

    const data = getFormData();

    if (!data.id || !data.name) {
        showToast('ID and Name are required', 'error');
        return;
    }

    try {
        saveBtn.disabled = true;
        await saveAgent(data.id, data);
        showToast('Agent saved successfully');

        // Reload agents list
        agents = await fetchAgents();
        populateAgentSelect();
        agentSelect.value = data.id;
    } catch (error) {
        showToast('Failed to save: ' + error.message, 'error');
    } finally {
        saveBtn.disabled = false;
    }
}

function showDeleteAgentModal() {
    const id = agentId.value;

    if (!id || id === 'default') {
        showToast('Cannot delete the default agent', 'error');
        return;
    }

    agentToDelete = id;
    deleteAgentConfirmText.textContent = `Are you sure you want to delete "${agentName.value}"? This action cannot be undone.`;
    deleteAgentModal.classList.add('active');
}

function hideDeleteAgentModal() {
    deleteAgentModal.classList.remove('active');
    agentToDelete = null;
}

async function handleDelete() {
    if (!agentToDelete) return;

    try {
        confirmDeleteAgentBtn.disabled = true;
        await deleteAgent(agentToDelete);
        hideDeleteAgentModal();
        showToast('Agent deleted successfully');

        // Reload and select default
        agents = await fetchAgents();
        populateAgentSelect();
        agentSelect.value = 'default';
        await handleAgentChange();
    } catch (error) {
        showToast('Failed to delete: ' + error.message, 'error');
    } finally {
        confirmDeleteAgentBtn.disabled = false;
    }
}

async function handleCreate() {
    const id = newAgentIdInput.value.trim().toLowerCase().replace(/[^a-z0-9-]/g, '-');
    const name = newAgentNameInput.value.trim();

    if (!id || !name) {
        showToast('ID and Name are required', 'error');
        return;
    }

    // Check if exists
    if (agents.find(a => a.id === id)) {
        showToast('Agent with this ID already exists', 'error');
        return;
    }

    const newAgent = {
        id,
        name,
        description: '',
        system_prompt: '',
        allowed_tools: ['Read', 'Write', 'Edit'],
        mcp_servers: null,
        model: 'opus',
        subagents: [],
        color: '#a67c5b'
    };

    try {
        confirmCreateBtn.disabled = true;
        await saveAgent(id, newAgent);
        hideModal();
        showToast('Agent created');

        // Reload and select new agent
        agents = await fetchAgents();
        populateAgentSelect();
        agentSelect.value = id;
        await handleAgentChange();
    } catch (error) {
        showToast('Failed to create: ' + error.message, 'error');
    } finally {
        confirmCreateBtn.disabled = false;
    }
}

async function handleApplyConfig() {
    try {
        applyConfigBtn.disabled = true;
        applyConfigBtn.innerHTML = `
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="spin">
                <polyline points="23 4 23 10 17 10"/>
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
            </svg>
            Applying...
        `;

        await applyConfig();
        showToast('Configuration applied! JARVIS restarted.');
    } catch (error) {
        showToast('Failed to apply config: ' + error.message, 'error');
    } finally {
        applyConfigBtn.disabled = false;
        applyConfigBtn.innerHTML = `
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="20 6 9 17 4 12"/>
            </svg>
            Apply Config
        `;
    }
}

async function handleRestart() {
    if (!confirm('Restart the server? Current connections will be lost.')) {
        return;
    }

    try {
        restartBtn.disabled = true;
        restartBtn.innerHTML = `
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="spin">
                <polyline points="23 4 23 10 17 10"/>
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
            </svg>
            Restarting...
        `;

        await restartServer();
        showToast('Server restarting... Please wait.');

        // Wait for server to restart, then try to reload
        const maxAttempts = 10;
        let attempt = 0;

        const tryReload = async () => {
            attempt++;
            try {
                // Try to fetch agents to check if server is back
                const response = await fetch('/api/agents', {
                    signal: AbortSignal.timeout(2000)
                });
                if (response.ok) {
                    showToast('Server restarted successfully!');
                    setTimeout(() => window.location.reload(), 500);
                    return;
                }
            } catch (e) {
                // Server not ready yet
            }

            if (attempt < maxAttempts) {
                showToast(`Waiting for server... (${attempt}/${maxAttempts})`);
                setTimeout(tryReload, 1500);
            } else {
                showToast('Server may have restarted. Please refresh manually.', 'error');
                restartBtn.disabled = false;
                restartBtn.innerHTML = `
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="23 4 23 10 17 10"/>
                        <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
                    </svg>
                    Restart Server
                `;
            }
        };

        // Start trying after 2 seconds
        setTimeout(tryReload, 2000);

    } catch (error) {
        showToast('Failed to restart: ' + error.message, 'error');
        restartBtn.disabled = false;
    }
}

function handleMcpConfigChange() {
    // When MCP config changes, reload MCP servers
    const configPath = mcpServersInput.value;
    if (configPath) {
        fetchMcpServers(configPath).then(servers => {
            mcpServers = servers;
            renderMcpTools();

            // Re-check previously selected MCP tools
            if (currentAgent?.allowed_tools) {
                currentAgent.allowed_tools.forEach(tool => {
                    if (tool.startsWith('mcp__')) {
                        const cb = document.querySelector(`input[name="tools"][value="${tool}"]`);
                        if (cb) {
                            cb.checked = true;
                            cb.closest('.checkbox-item')?.classList.add('checked');
                        }
                    }
                });
            }
        });
    } else {
        mcpServers = [];
        renderMcpTools();
    }
}

function handleCreateSubagent() {
    // For now, just show a message - in the future could open a subagent editor
    showToast('Create subagent files in .claude/agents/ directory', 'info');
}

function handleColorSelect(e) {
    const btn = e.target.closest('.color-option');
    if (!btn) return;

    const color = btn.dataset.color;
    agentColorInput.value = color;

    // Update selection UI
    colorPicker.querySelectorAll('.color-option').forEach(b => {
        b.classList.toggle('selected', b === btn);
    });
}

function handleExport() {
    const data = getFormData();

    // Create a clean export object
    const exportData = {
        id: data.id,
        name: data.name,
        description: data.description,
        system_prompt: data.system_prompt,
        allowed_tools: data.allowed_tools,
        mcp_servers: data.mcp_servers,
        model: data.model,
        subagents: data.subagents,
        color: data.color,
        exported_at: new Date().toISOString()
    };

    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);

    const a = document.createElement('a');
    a.href = url;
    a.download = `agent-${data.id}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    showToast('Agent exported successfully');
}

async function handleImport(e) {
    const file = e.target.files[0];
    if (!file) return;

    try {
        const text = await file.text();
        const importData = JSON.parse(text);

        // Validate required fields
        if (!importData.id || !importData.name) {
            showToast('Invalid agent file: missing id or name', 'error');
            return;
        }

        // Check if agent already exists
        const existingAgent = agents.find(a => a.id === importData.id);
        if (existingAgent) {
            if (!confirm(`Agent "${importData.id}" already exists. Overwrite?`)) {
                return;
            }
        }

        // Clean the imported data
        const agentData = {
            id: importData.id,
            name: importData.name,
            description: importData.description || '',
            system_prompt: importData.system_prompt || '',
            allowed_tools: importData.allowed_tools || [],
            mcp_servers: importData.mcp_servers || null,
            model: importData.model || 'opus',
            subagents: importData.subagents || [],
            color: importData.color || '#a67c5b'
        };

        // Save the imported agent
        await saveAgent(agentData.id, agentData);
        showToast('Agent imported successfully');

        // Reload agents list and select the imported one
        agents = await fetchAgents();
        populateAgentSelect();
        agentSelect.value = agentData.id;
        await handleAgentChange();

    } catch (error) {
        showToast('Failed to import: ' + error.message, 'error');
    } finally {
        // Reset file input
        importFileInput.value = '';
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
// UI Settings Functions
// ============================================
function loadUISettings() {
    const defaults = {
        typewriterSpeed: 50,
        fontSize: 16,
        themeColor: 'terracotta',
        enableTypewriter: true,
        enableAnimations: true,
        reducedMotion: false,
        highContrast: false
    };
    try {
        const saved = localStorage.getItem(UI_SETTINGS_KEY);
        if (saved) {
            const settings = JSON.parse(saved);
            // Migrate old neon colors to Claude style
            const oldColors = ['cyan', 'magenta', 'yellow', 'orange'];
            if (oldColors.includes(settings.themeColor)) {
                settings.themeColor = 'terracotta';
                localStorage.setItem(UI_SETTINGS_KEY, JSON.stringify(settings));
            }
            return { ...defaults, ...settings };
        }
    } catch (e) {
        console.warn('Failed to load UI settings:', e);
    }
    return defaults;
}

function saveUISettings(settings) {
    try {
        localStorage.setItem(UI_SETTINGS_KEY, JSON.stringify(settings));
        // Dispatch event for other pages to pick up
        window.dispatchEvent(new CustomEvent('uiSettingsChanged', { detail: settings }));
    } catch (e) {
        console.warn('Failed to save UI settings:', e);
    }
}

function getUISettings() {
    return {
        typewriterSpeed: parseInt(typewriterSpeedSlider?.value || 50),
        fontSize: parseInt(fontSizeSlider?.value || 16),
        themeColor: themeColorInput?.value || 'terracotta',
        enableTypewriter: enableTypewriterToggle?.checked ?? true,
        enableAnimations: enableAnimationsToggle?.checked ?? true,
        reducedMotion: reducedMotionToggle?.checked ?? false,
        highContrast: highContrastToggle?.checked ?? false
    };
}

function applyUISettings(settings) {
    // Apply to sliders
    if (typewriterSpeedSlider) {
        typewriterSpeedSlider.value = settings.typewriterSpeed;
        if (typewriterSpeedValue) typewriterSpeedValue.textContent = `${settings.typewriterSpeed}ms`;
    }
    if (fontSizeSlider) {
        fontSizeSlider.value = settings.fontSize;
        if (fontSizeValue) fontSizeValue.textContent = `${settings.fontSize}px`;
    }

    // Apply theme color
    if (themeColorInput) themeColorInput.value = settings.themeColor;
    themeColorPicker?.querySelectorAll('.theme-color-option').forEach(btn => {
        btn.classList.toggle('selected', btn.dataset.color === settings.themeColor);
    });
    applyThemeColor(settings.themeColor);

    // Apply toggles
    if (enableTypewriterToggle) enableTypewriterToggle.checked = settings.enableTypewriter;
    if (enableAnimationsToggle) enableAnimationsToggle.checked = settings.enableAnimations;
    if (reducedMotionToggle) reducedMotionToggle.checked = settings.reducedMotion;
    if (highContrastToggle) highContrastToggle.checked = settings.highContrast;

    // Apply to document
    document.documentElement.setAttribute('data-reduced-motion', settings.reducedMotion);
    document.documentElement.setAttribute('data-high-contrast', settings.highContrast);
    document.documentElement.style.setProperty('--base-font-size', `${settings.fontSize}px`);
}

function applyThemeColor(color) {
    const colors = {
        terracotta: { primary: '#a67c5b', secondary: '#8a6a4a', muted: 'rgba(166, 124, 91, 0.12)', glow: 'rgba(166, 124, 91, 0.25)' },
        brown: { primary: '#8a7a5a', secondary: '#7a6a4a', muted: 'rgba(138, 122, 90, 0.12)', glow: 'rgba(138, 122, 90, 0.25)' },
        green: { primary: '#6a8a6a', secondary: '#5a7a5a', muted: 'rgba(106, 138, 106, 0.12)', glow: 'rgba(106, 138, 106, 0.25)' },
        blue: { primary: '#5a7a8a', secondary: '#4a6a7a', muted: 'rgba(90, 122, 138, 0.12)', glow: 'rgba(90, 122, 138, 0.25)' },
        purple: { primary: '#7a6a8a', secondary: '#6a5a7a', muted: 'rgba(122, 106, 138, 0.12)', glow: 'rgba(122, 106, 138, 0.25)' },
        red: { primary: '#9a6a6a', secondary: '#8a5a5a', muted: 'rgba(154, 106, 106, 0.12)', glow: 'rgba(154, 106, 106, 0.25)' }
    };

    const theme = colors[color] || colors.terracotta;
    document.documentElement.style.setProperty('--accent-primary', theme.primary);
    document.documentElement.style.setProperty('--accent-secondary', theme.secondary);
    document.documentElement.style.setProperty('--accent-muted', theme.muted);
    document.documentElement.style.setProperty('--accent-glow', theme.glow);
}

function initUISettingsEvents() {
    // Typewriter speed slider
    typewriterSpeedSlider?.addEventListener('input', () => {
        const value = typewriterSpeedSlider.value;
        if (typewriterSpeedValue) typewriterSpeedValue.textContent = `${value}ms`;
        const settings = getUISettings();
        saveUISettings(settings);
    });

    // Font size slider
    fontSizeSlider?.addEventListener('input', () => {
        const value = fontSizeSlider.value;
        if (fontSizeValue) fontSizeValue.textContent = `${value}px`;
        document.documentElement.style.setProperty('--base-font-size', `${value}px`);
        const settings = getUISettings();
        saveUISettings(settings);
    });

    // Theme color picker
    themeColorPicker?.addEventListener('click', (e) => {
        const btn = e.target.closest('.theme-color-option');
        if (!btn) return;

        const color = btn.dataset.color;
        if (themeColorInput) themeColorInput.value = color;

        themeColorPicker.querySelectorAll('.theme-color-option').forEach(b => {
            b.classList.toggle('selected', b === btn);
        });

        applyThemeColor(color);
        const settings = getUISettings();
        saveUISettings(settings);
    });

    // Toggle switches
    [enableTypewriterToggle, enableAnimationsToggle, reducedMotionToggle, highContrastToggle].forEach(toggle => {
        toggle?.addEventListener('change', () => {
            const settings = getUISettings();
            document.documentElement.setAttribute('data-reduced-motion', settings.reducedMotion);
            document.documentElement.setAttribute('data-high-contrast', settings.highContrast);
            saveUISettings(settings);
        });
    });
}

// ============================================
// Avatar Functions
// ============================================
const AVATAR_ICONS = {
    layers: `<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M12 2L2 7L12 12L22 7L12 2Z"/>
        <path d="M2 17L12 22L22 17"/>
        <path d="M2 12L12 17L22 12"/>
    </svg>`,
    bot: `<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <rect x="3" y="11" width="18" height="10" rx="2"/>
        <circle cx="12" cy="5" r="2"/>
        <path d="M12 7v4"/>
        <circle cx="8" cy="16" r="1" fill="currentColor"/>
        <circle cx="16" cy="16" r="1" fill="currentColor"/>
    </svg>`,
    cpu: `<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <rect x="4" y="4" width="16" height="16" rx="2"/>
        <rect x="9" y="9" width="6" height="6"/>
        <line x1="9" y1="1" x2="9" y2="4"/>
        <line x1="15" y1="1" x2="15" y2="4"/>
        <line x1="9" y1="20" x2="9" y2="23"/>
        <line x1="15" y1="20" x2="15" y2="23"/>
        <line x1="20" y1="9" x2="23" y2="9"/>
        <line x1="20" y1="14" x2="23" y2="14"/>
        <line x1="1" y1="9" x2="4" y2="9"/>
        <line x1="1" y1="14" x2="4" y2="14"/>
    </svg>`,
    brain: `<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M12 4.5a2.5 2.5 0 0 0-4.96-.46 2.5 2.5 0 0 0-1.98 3 2.5 2.5 0 0 0-1.32 4.24 3 3 0 0 0 .34 5.58 2.5 2.5 0 0 0 2.96 3.08A2.5 2.5 0 0 0 12 19.5a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-1.98-3A2.5 2.5 0 0 0 12 4.5"/>
        <path d="M12 4.5v15"/>
    </svg>`,
    terminal: `<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <polyline points="4 17 10 11 4 5"/>
        <line x1="12" y1="19" x2="20" y2="19"/>
    </svg>`,
    zap: `<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
    </svg>`,
    star: `<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
    </svg>`,
    hexagon: `<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>
    </svg>`
};

function updateAvatarPreview(iconOrUrl) {
    if (!avatarPreview) return;

    if (iconOrUrl.startsWith('data:') || iconOrUrl.startsWith('http')) {
        // It's an image URL
        avatarPreview.innerHTML = `<img src="${iconOrUrl}" alt="Agent avatar">`;
    } else {
        // It's an icon name
        avatarPreview.innerHTML = AVATAR_ICONS[iconOrUrl] || AVATAR_ICONS.layers;
    }
}

function initAvatarEvents() {
    // Icon grid selection
    avatarIconGrid?.addEventListener('click', (e) => {
        const btn = e.target.closest('.avatar-icon-option');
        if (!btn) return;

        const icon = btn.dataset.icon;
        if (avatarInput) avatarInput.value = icon;

        avatarIconGrid.querySelectorAll('.avatar-icon-option').forEach(b => {
            b.classList.toggle('selected', b === btn);
        });

        updateAvatarPreview(icon);
    });

    // Avatar upload area
    avatarUploadArea?.addEventListener('click', () => {
        avatarFileInput?.click();
    });

    // Drag and drop
    avatarUploadArea?.addEventListener('dragover', (e) => {
        e.preventDefault();
        avatarUploadArea.classList.add('drag-over');
    });

    avatarUploadArea?.addEventListener('dragleave', () => {
        avatarUploadArea.classList.remove('drag-over');
    });

    avatarUploadArea?.addEventListener('drop', (e) => {
        e.preventDefault();
        avatarUploadArea.classList.remove('drag-over');

        const file = e.dataTransfer.files[0];
        if (file && file.type.startsWith('image/')) {
            handleAvatarFile(file);
        }
    });

    // File input change
    avatarFileInput?.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) {
            handleAvatarFile(file);
        }
    });
}

function handleAvatarFile(file) {
    const reader = new FileReader();
    reader.onload = (e) => {
        const dataUrl = e.target.result;
        if (avatarInput) avatarInput.value = dataUrl;
        updateAvatarPreview(dataUrl);

        // Deselect icon options
        avatarIconGrid?.querySelectorAll('.avatar-icon-option').forEach(btn => {
            btn.classList.remove('selected');
        });

        showToast('Avatar uploaded', 'success');
    };
    reader.readAsDataURL(file);
}

// ============================================
// Keyboard Shortcuts
// ============================================
function initKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        // Escape: Close modals
        if (e.key === 'Escape') {
            if (modal?.classList.contains('active')) {
                hideModal();
                return;
            }
            if (deleteAgentModal?.classList.contains('active')) {
                hideDeleteAgentModal();
                return;
            }
        }

        // Ctrl/Cmd + S: Save
        if ((e.ctrlKey || e.metaKey) && e.key === 's') {
            e.preventDefault();
            agentForm.requestSubmit();
            return;
        }
    });
}

// ============================================
// Initialization
// ============================================
async function init() {
    // Initialize theme
    initTheme();

    // Initialize keyboard shortcuts
    initKeyboardShortcuts();

    // Initialize UI settings
    const uiSettings = loadUISettings();
    applyUISettings(uiSettings);
    initUISettingsEvents();

    // Initialize avatar events
    initAvatarEvents();

    try {
        // Load data
        [agents, availableTools, availableSubagents] = await Promise.all([
            fetchAgents(),
            fetchTools(),
            fetchSubagents()
        ]);

        // Render UI
        populateAgentSelect();
        renderBuiltinTools();
        renderSubagents();

        // Select first agent or default
        const defaultAgent = agents.find(a => a.id === 'default') || agents[0];
        if (defaultAgent) {
            agentSelect.value = defaultAgent.id;
            await handleAgentChange();
        }

        // Event listeners
        agentSelect.addEventListener('change', handleAgentChange);
        agentForm.addEventListener('submit', handleSave);
        deleteAgentBtn.addEventListener('click', showDeleteAgentModal);
        newAgentBtn.addEventListener('click', showModal);
        closeModalBtn.addEventListener('click', hideModal);
        cancelModalBtn.addEventListener('click', hideModal);
        confirmCreateBtn.addEventListener('click', handleCreate);
        applyConfigBtn.addEventListener('click', handleApplyConfig);
        restartBtn.addEventListener('click', handleRestart);
        createSubagentBtn.addEventListener('click', handleCreateSubagent);
        mcpServersInput.addEventListener('blur', handleMcpConfigChange);

        // MCP enabled toggle - show/hide config field
        mcpEnabledInput?.addEventListener('change', () => {
            if (mcpServersGroup) {
                mcpServersGroup.style.display = mcpEnabledInput.checked ? 'block' : 'none';
            }
        });

        // Color picker
        colorPicker.addEventListener('click', handleColorSelect);

        // Import/Export
        exportAgentBtn.addEventListener('click', handleExport);
        importAgentBtn.addEventListener('click', () => importFileInput.click());
        importFileInput.addEventListener('change', handleImport);

        // Close modal on backdrop click
        modal.querySelector('.modal-backdrop').addEventListener('click', hideModal);

        // Delete agent modal
        closeDeleteAgentModalBtn?.addEventListener('click', hideDeleteAgentModal);
        cancelDeleteAgentBtn?.addEventListener('click', hideDeleteAgentModal);
        confirmDeleteAgentBtn?.addEventListener('click', handleDelete);
        deleteAgentModal?.querySelector('.modal-backdrop')?.addEventListener('click', hideDeleteAgentModal);

    } catch (error) {
        console.error('Failed to initialize:', error);
        showToast('Failed to load settings', 'error');
    }
}

// Start
document.addEventListener('DOMContentLoaded', init);
