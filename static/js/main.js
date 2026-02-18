document.addEventListener('DOMContentLoaded', function() {
    const mainContent = document.getElementById('main-content');
    const navLinks = document.querySelectorAll('.nav-link');

    // --- Templates for each section ---
    const templates = {
        tasks: () => `
            <section id="tasks-section" class="content-section">
                <div class="section-header">
                    <h2>任务管理</h2>
                    <button id="add-task-btn" class="control-button primary-btn">➕ 创建新任务</button>
                </div>
                <div id="tasks-table-container">
                    <p>正在加载任务列表...</p>
                </div>
            </section>`,
        results: () => `
            <section id="results-section" class="content-section">
                <div class="section-header">
                    <h2>结果查看</h2>
                </div>
                <div class="results-filter-bar">
                    <select id="result-file-selector"><option>加载中...</option></select>
                    <button id="refresh-results-btn" class="control-button">🔄 刷新</button>
                </div>
                <div id="results-grid-container">
                    <p>请先选择一个结果文件。</p>
                </div>
            </section>`,
        logs: () => `
            <section id="logs-section" class="content-section">
                <div class="section-header">
                    <h2>运行日志</h2>
                    <button id="refresh-logs-btn" class="control-button">🔄 刷新</button>
                </div>
                <pre id="log-content-container">正在加载日志...</pre>
            </section>`,
        settings: () => `
            <section id="settings-section" class="content-section">
                <h2>系统设置</h2>
                <div class="settings-card">
                    <h3>系统状态检查</h3>
                    <div id="system-status-container"><p>正在加载状态...</p></div>
                </div>
            </section>`
    };

    async function createTask(data) {
        try {
            const response = await fetch(`/api/tasks`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(data),
            });
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || '创建任务失败');
            }
            console.log(`任务创建成功!`);
            return await response.json();
        } catch (error) {
            console.error(`无法创建任务:`, error);
            alert(`错误: ${error.message}`);
            return null;
        }
    }

    async function deleteTask(taskId) {
        try {
            const response = await fetch(`/api/tasks/${taskId}`, {
                method: 'DELETE',
            });
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || '删除任务失败');
            }
            console.log(`任务 ${taskId} 删除成功!`);
            return await response.json();
        } catch (error) {
            console.error(`无法删除任务 ${taskId}:`, error);
            alert(`错误: ${error.message}`);
            return null;
        }
    }

    async function updateTask(taskId, data) {
        try {
            const response = await fetch(`/api/tasks/${taskId}`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(data),
            });
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || '更新任务失败');
            }
            console.log(`任务 ${taskId} 更新成功!`);
            return await response.json();
        } catch (error) {
            console.error(`无法更新任务 ${taskId}:`, error);
            // TODO: Use a more elegant notification system
            alert(`错误: ${error.message}`);
            return null;
        }
    }

    async function fetchTasks() {
        try {
            const response = await fetch('/api/tasks');
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error("无法获取任务列表:", error);
            return null;
        }
    }

    async function fetchResultFiles() {
        try {
            const response = await fetch('/api/results/files');
            if (!response.ok) throw new Error('无法获取结果文件列表');
            return await response.json();
        } catch (error) {
            console.error(error);
            return null;
        }
    }

    async function fetchResultContent(filename) {
        try {
            const params = new URLSearchParams({
                page: 1,
                limit: 100, // Fetch a decent number of items
            });
            const response = await fetch(`/api/results/${filename}?${params}`);
            if (!response.ok) throw new Error(`无法获取文件 ${filename} 的内容`);
            return await response.json();
        } catch (error) {
            console.error(error);
            return null;
        }
    }

    async function fetchSystemStatus() {
        try {
            const response = await fetch('/api/settings/status');
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error("无法获取系统状态:", error);
            return null;
        }
    }

    async function fetchLogs() {
        try {
            const response = await fetch('/api/logs');
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error("无法获取日志:", error);
            return { content: `加载日志失败: ${error.message}` };
        }
    }

    // --- Render Functions ---
    function renderSystemStatus(status) {
        if (!status) return '<p>无法加载系统状态。</p>';

        const renderStatusTag = (isOk) => isOk
            ? `<span class="tag status-ok">正常</span>`
            : `<span class="tag status-error">异常</span>`;

        const env = status.env_file || {};

        return `
            <ul class="status-list">
                <li class="status-item">
                    <span class="label">登录状态文件 (xianyu_state.json)</span>
                    <span class="value">${renderStatusTag(status.login_state_file && status.login_state_file.exists)}</span>
                </li>
                <li class="status-item">
                    <span class="label">环境变量文件 (.env)</span>
                    <span class="value">${renderStatusTag(env.exists)}</span>
                </li>
            </ul>
        `;
    }

    function renderResultsGrid(data) {
        if (!data || !data.items || data.items.length === 0) {
            return '<p>没有找到符合条件的商品记录。</p>';
        }

        const cards = data.items.map(item => {
            const info = item.商品信息 || {};
            const seller = item.卖家信息 || {};
            
            const imageUrl = (info.商品图片列表 && info.商品图片列表[0]) ? info.商品图片列表[0] : 'data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=';

            return `
            <div class="result-card" data-item='${JSON.stringify(item)}'>
                <div class="card-image">
                    <a href="${info.商品链接 || '#'}" target="_blank"><img src="${imageUrl}" alt="${info.商品标题 || '商品图片'}" loading="lazy"></a>
                </div>
                <div class="card-content">
                    <h3 class="card-title"><a href="${info.商品链接 || '#'}" target="_blank" title="${info.商品标题 || ''}">${info.商品标题 || '无标题'}</a></h3>
                    <p class="card-price">${info.当前售价 || '价格未知'}</p>
                    <div class="card-footer">
                        <span class="seller-info">卖家: ${info.卖家昵称 || seller.卖家昵称 || '未知'}</span>
                        <span>
                            <a href="${info.商品链接 || '#'}" target="_blank" class="action-btn">查看详情</a>
                        </span>
                    </div>
                </div>
            </div>
            `;
        }).join('');

        return `<div id="results-grid">${cards}</div>`;
    }

    function renderTasksTable(tasks) {
        if (!tasks || tasks.length === 0) {
            return '<p>没有找到任何任务。请点击右上角“创建新任务”来添加一个。</p>';
        }

        const tableHeader = `
            <thead>
                <tr>
                    <th>启用</th>
                    <th>任务名称</th>
                    <th>关键词</th>
                    <th>价格范围</th>
                    <th>筛选条件</th>
                    <th>操作</th>
                </tr>
            </thead>`;

        const tableBody = tasks.map(task => `
            <tr data-task-id="${task.id}" data-task='${JSON.stringify(task)}'>
                <td>
                    <label class="switch">
                        <input type="checkbox" ${task.enabled ? 'checked' : ''}>
                        <span class="slider round"></span>
                    </label>
                </td>
                <td>${task.task_name}</td>
                <td><span class="tag">${task.keyword}</span></td>
                <td>${task.min_price || '不限'} - ${task.max_price || '不限'}</td>
                <td>${task.personal_only ? '<span class="tag personal">个人闲置</span>' : ''}</td>
                <td>
                    <button class="action-btn edit-btn">编辑</button>
                    <button class="action-btn delete-btn">删除</button>
                </td>
            </tr>`).join('');

        return `<table class="tasks-table">${tableHeader}<tbody>${tableBody}</tbody></table>`;
    }


    async function navigateTo(hash) {
        const sectionId = hash.substring(1) || 'tasks';

        // Update nav links active state
        navLinks.forEach(link => {
            link.classList.toggle('active', link.getAttribute('href') === `#${sectionId}`);
        });

        // Update main content
        if (templates[sectionId]) {
            mainContent.innerHTML = templates[sectionId]();
            // Make the new content visible
            const newSection = mainContent.querySelector('.content-section');
            if (newSection) {
                requestAnimationFrame(() => {
                    newSection.classList.add('active');
                });
            }

            // --- Load data for the current section ---
            if (sectionId === 'tasks') {
                const container = document.getElementById('tasks-table-container');
                const tasks = await fetchTasks();
                container.innerHTML = renderTasksTable(tasks);
            } else if (sectionId === 'results') {
                await initializeResultsView();
            } else if (sectionId === 'logs') {
                const logContainer = document.getElementById('log-content-container');
                const logs = await fetchLogs();
                logContainer.textContent = logs.content;
                // 自动滚动到底部
                logContainer.scrollTop = logContainer.scrollHeight;
            } else if (sectionId === 'settings') {
                await initializeSettingsView();
            }

        } else {
            mainContent.innerHTML = '<section class="content-section active"><h2>页面未找到</h2></section>';
        }
    }

    async function fetchAndRenderResults() {
        const selector = document.getElementById('result-file-selector');
        const container = document.getElementById('results-grid-container');

        if (!selector || !container) return;

        const selectedFile = selector.value;

        if (!selectedFile) {
            container.innerHTML = '<p>请先选择一个结果文件。</p>';
            return;
        }

        container.innerHTML = '<p>正在加载结果...</p>';
        const data = await fetchResultContent(selectedFile);
        container.innerHTML = renderResultsGrid(data);
    }

    async function initializeResultsView() {
        const selector = document.getElementById('result-file-selector');
        const refreshBtn = document.getElementById('refresh-results-btn');

        const fileData = await fetchResultFiles();
        if (fileData && fileData.files && fileData.files.length > 0) {
            selector.innerHTML = fileData.files.map(f => `<option value="${f}">${f}</option>`).join('');
            selector.addEventListener('change', fetchAndRenderResults);
            refreshBtn.addEventListener('click', fetchAndRenderResults);
            // Initial load
            await fetchAndRenderResults();
        } else {
            selector.innerHTML = '<option value="">没有可用的结果文件</option>';
            document.getElementById('results-grid-container').innerHTML = '<p>没有找到任何结果文件。请先运行监控任务。</p>';
        }
    }

    async function initializeSettingsView() {
        // 1. Render System Status
        const statusContainer = document.getElementById('system-status-container');
        const status = await fetchSystemStatus();
        statusContainer.innerHTML = renderSystemStatus(status);
    }

    // Handle navigation clicks
    navLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            const hash = this.getAttribute('href');
            if (window.location.hash !== hash) {
                window.location.hash = hash;
            }
        });
    });

    // Handle hash changes (e.g., back/forward buttons, direct URL)
    window.addEventListener('hashchange', () => {
        navigateTo(window.location.hash);
    });

    // --- Event Delegation for dynamic content ---
    mainContent.addEventListener('click', async (event) => {
        const target = event.target;
        const button = target.closest('button'); // Find the closest button element
        if (!button) return;

        const row = button.closest('tr');
        const taskId = row ? row.dataset.taskId : null;

        if (button.matches('.view-json-btn')) {
            const card = button.closest('.result-card');
            const itemData = JSON.parse(card.dataset.item);
            const jsonContent = document.getElementById('json-viewer-content');
            jsonContent.textContent = JSON.stringify(itemData, null, 2);
            
            const modal = document.getElementById('json-viewer-modal');
            modal.style.display = 'flex';
            setTimeout(() => modal.classList.add('visible'), 10);
        } else if (button.matches('.edit-btn')) {
            const taskData = JSON.parse(row.dataset.task);
            
            row.classList.add('editing');
            row.innerHTML = `
                <td>
                    <label class="switch">
                        <input type="checkbox" ${taskData.enabled ? 'checked' : ''} data-field="enabled">
                        <span class="slider round"></span>
                    </label>
                </td>
                <td><input type="text" value="${taskData.task_name}" data-field="task_name"></td>
                <td><input type="text" value="${taskData.keyword}" data-field="keyword"></td>
                <td>
                    <input type="text" value="${taskData.min_price || ''}" placeholder="不限" data-field="min_price" style="width: 60px;"> -
                    <input type="text" value="${taskData.max_price || ''}" placeholder="不限" data-field="max_price" style="width: 60px;">
                </td>
                <td>
                    <label>
                        <input type="checkbox" ${taskData.personal_only ? 'checked' : ''} data-field="personal_only"> 个人闲置
                    </label>
                </td>
                <td>
                    <button class="action-btn save-btn">保存</button>
                    <button class="action-btn cancel-btn">取消</button>
                </td>
            `;

        } else if (button.matches('.delete-btn')) {
            const taskName = row.querySelector('td:nth-child(2)').textContent;
            if (confirm(`你确定要删除任务 "${taskName}" 吗?`)) {
                const result = await deleteTask(taskId);
                if (result) {
                    row.remove();
                }
            }
        } else if (button.matches('#add-task-btn')) {
            const modal = document.getElementById('add-task-modal');
            modal.style.display = 'flex';
            // Use a short timeout to allow the display property to apply before adding the transition class
            setTimeout(() => modal.classList.add('visible'), 10);
        } else if (button.matches('.save-btn')) {
            const taskNameInput = row.querySelector('input[data-field="task_name"]');
            const keywordInput = row.querySelector('input[data-field="keyword"]');
            if (!taskNameInput.value.trim() || !keywordInput.value.trim()) {
                alert('任务名称和关键词不能为空。');
                return;
            }

            const inputs = row.querySelectorAll('input[data-field]');
            const updatedData = {};
            inputs.forEach(input => {
                const field = input.dataset.field;
                if (input.type === 'checkbox') {
                    updatedData[field] = input.checked;
                } else {
                    updatedData[field] = input.value.trim() === '' ? null : input.value.trim();
                }
            });

            const result = await updateTask(taskId, updatedData);
            if (result && result.task) {
                const container = document.getElementById('tasks-table-container');
                const tasks = await fetchTasks();
                container.innerHTML = renderTasksTable(tasks);
            }
        } else if (button.matches('.cancel-btn')) {
            const container = document.getElementById('tasks-table-container');
            const tasks = await fetchTasks();
            container.innerHTML = renderTasksTable(tasks);
        } else if (button.matches('#refresh-logs-btn')) {
            const logContainer = document.getElementById('log-content-container');
            logContainer.textContent = '正在刷新...';
            const logs = await fetchLogs();
            logContainer.textContent = logs.content;
            logContainer.scrollTop = logContainer.scrollHeight;
        }
    });

    mainContent.addEventListener('change', async (event) => {
        const target = event.target;
        // Check if the changed element is a toggle switch in the main table (not in an editing row)
        if (target.matches('.tasks-table input[type="checkbox"]') && !target.closest('tr.editing')) {
            const row = target.closest('tr');
            const taskId = row.dataset.taskId;
            const isEnabled = target.checked;

            if (taskId) {
                await updateTask(taskId, { enabled: isEnabled });
                // The visual state is already updated by the checkbox itself.
            }
        }
    });

    // --- Modal Logic ---
    const modal = document.getElementById('add-task-modal');
    if (modal) {
        const closeModalBtn = document.getElementById('close-modal-btn');
        const cancelBtn = document.getElementById('cancel-add-task-btn');
        const saveBtn = document.getElementById('save-new-task-btn');
        const form = document.getElementById('add-task-form');

        const closeModal = () => {
            modal.classList.remove('visible');
            setTimeout(() => {
                modal.style.display = 'none';
                form.reset(); // Reset form on close
            }, 300);
        };

        closeModalBtn.addEventListener('click', closeModal);
        cancelBtn.addEventListener('click', closeModal);
        modal.addEventListener('click', (event) => {
            // Close if clicked on the overlay background
            if (event.target === modal) {
                closeModal();
            }
        });

        saveBtn.addEventListener('click', async () => {
            if (form.checkValidity() === false) {
                form.reportValidity();
                return;
            }

            const formData = new FormData(form);
            const data = {
                task_name: formData.get('task_name'),
                keyword: formData.get('keyword'),
                min_price: formData.get('min_price') || null,
                max_price: formData.get('max_price') || null,
                personal_only: formData.get('personal_only') === 'on',
                max_pages: 3,
                enabled: true,
            };

            // Show loading state
            const btnText = saveBtn.querySelector('.btn-text');
            const spinner = saveBtn.querySelector('.spinner');
            btnText.style.display = 'none';
            spinner.style.display = 'inline-block';
            saveBtn.disabled = true;

            const result = await createTask(data);

            // Hide loading state
            btnText.style.display = 'inline-block';
            spinner.style.display = 'none';
            saveBtn.disabled = false;

            if (result && result.task) {
                closeModal();
                // Refresh task list
                const container = document.getElementById('tasks-table-container');
                if (container) {
                    const tasks = await fetchTasks();
                    container.innerHTML = renderTasksTable(tasks);
                }
            }
        });
    }


    // --- Header Controls & Status ---
    function updateHeaderControls(status) {
        const statusIndicator = document.getElementById('status-indicator');
        const statusText = document.getElementById('status-text');
        const startBtn = document.getElementById('start-all-tasks');
        const stopBtn = document.getElementById('stop-all-tasks');

        // Reset buttons state
        startBtn.disabled = false;
        startBtn.innerHTML = `🚀 全部启动`;
        stopBtn.disabled = false;
        stopBtn.innerHTML = `🛑 全部停止`;

        if (status && status.scraper_running) {
            statusIndicator.className = 'status-running';
            statusText.textContent = '运行中';
            startBtn.style.display = 'none';
            stopBtn.style.display = 'inline-block';
        } else {
            statusIndicator.className = 'status-stopped';
            statusText.textContent = '已停止';
            startBtn.style.display = 'inline-block';
            stopBtn.style.display = 'none';
        }
    }

    async function refreshSystemStatus() {
        const status = await fetchSystemStatus();
        updateHeaderControls(status);
    }

    document.getElementById('start-all-tasks').addEventListener('click', async () => {
        const btn = document.getElementById('start-all-tasks');
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner" style="vertical-align: middle;"></span> 启动中...`;

        try {
            const response = await fetch('/api/tasks/start-all', { method: 'POST' });
            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || '启动失败');
            }
            await response.json();
            // Give backend a moment to update state before refreshing
            setTimeout(refreshSystemStatus, 1000);
        } catch (error) {
            alert(`启动任务失败: ${error.message}`);
            await refreshSystemStatus(); // Refresh status to reset button state
        }
    });

    document.getElementById('stop-all-tasks').addEventListener('click', async () => {
        const btn = document.getElementById('stop-all-tasks');
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner" style="vertical-align: middle;"></span> 停止中...`;

        try {
            const response = await fetch('/api/tasks/stop-all', { method: 'POST' });
            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || '停止失败');
            }
            await response.json();
            setTimeout(refreshSystemStatus, 1000);
        } catch (error) {
            alert(`停止任务失败: ${error.message}`);
            await refreshSystemStatus(); // Refresh status to reset button state
        }
    });

    // Initial load
    navigateTo(window.location.hash || '#tasks');
    refreshSystemStatus();

    // --- JSON Viewer Modal Logic ---
    const jsonViewerModal = document.getElementById('json-viewer-modal');
    if (jsonViewerModal) {
        const closeBtn = document.getElementById('close-json-viewer-btn');
        
        const closeModal = () => {
            jsonViewerModal.classList.remove('visible');
            setTimeout(() => {
                jsonViewerModal.style.display = 'none';
            }, 300);
        };

        closeBtn.addEventListener('click', closeModal);
        jsonViewerModal.addEventListener('click', (event) => {
            if (event.target === jsonViewerModal) {
                closeModal();
            }
        });
    }
});
