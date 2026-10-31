/* 系统运行：Worker / 资源锁 / 队列 / 飞书通知；同时提供跨页共用的恢复与版本历史动作。 */
(function () {
  const { $, esc, api, toast, can, fmt, labels, empty } = window.AutomationUI;

  const state = { extraEvents: [] };

  const workerState = item => item.alive ? (item.status === 'busy' ? 'busy' : 'success') : (item.status === 'failed' ? 'failed' : 'offline');

  async function load() {
    const [data, policy] = await Promise.all([
      api('/api/automation/runtime-resources'),
      can('automation.jobs.view') ? api('/api/automation/notification-policy').catch(() => null) : Promise.resolve(null),
    ]);
    const summary = data.summary || {};
    $('runtimeSummary').innerHTML = `
      <div class="runtime-metric"><b style="color:var(--auto-green)">${Number(summary.alive_workers || 0)}</b><span>Worker 在线</span></div>
      <div class="runtime-metric"><b style="color:var(--auto-blue)">${Number(summary.busy_workers || 0)}</b><span>正在执行</span></div>
      <div class="runtime-metric"><b>${Number(summary.queued_runs || 0)}</b><span>排队中</span></div>
      <div class="runtime-metric"><b style="color:var(--auto-amber)">${Number(summary.resource_locks || 0)}</b><span>资源锁占用</span></div>
      <div class="runtime-metric"><b>${policy?.enabled ? '开启' : '关闭'}</b><span>飞书运行通知</span></div>`;
    const workers = data.workers || [];
    const alive = workers.filter(item => item.alive);
    const recentOffline = workers.filter(item => !item.alive).slice(0, 2);
    const hidden = workers.length - alive.length - recentOffline.length;
    const workerRow = item => {
      const status = workerState(item);
      const note = status === 'busy'
        ? `执行中${item.current_run_id ? ' · #' + esc(String(item.current_run_id).slice(0, 8)) : ''}`
        : status === 'success' ? `空闲 · 心跳 ${fmt(item.last_seen_at)}` : `心跳 ${fmt(item.last_seen_at)}`;
      const tone = status === 'busy' ? 'busy' : status === 'success' ? 'ok' : '';
      const label = status === 'busy' ? 'busy' : status === 'success' ? 'idle' : 'offline';
      return `<div class="runtime-item ${status === 'busy' ? 'is-busy' : ''}"><div><strong>${esc(item.worker_name)} · 进程 ${esc(item.process_id || '—')}</strong><p class="${tone}">${note}</p></div><span class="worker-state ${status}">${label}</span></div>`;
    };
    $('runtimeWorkers').innerHTML = (alive.length + recentOffline.length)
      ? alive.concat(recentOffline).map(workerRow).join('') + (hidden > 0 ? `<p class="runtime-footnote">另有 ${hidden} 个历史 Worker 心跳（离线）已折叠</p>` : '')
      : '<div class="runtime-empty">没有 Worker 心跳记录</div>';
    const lockAge = value => {
      if (!value) return '—';
      const minutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60000));
      return minutes < 60 ? `${minutes} 分钟` : `${(minutes / 60).toFixed(1)} 小时`;
    };
    $('runtimeLocks').innerHTML = (data.locks || []).length
      ? data.locks.map(item => {
        const paused = item.lock_state === 'paused';
        return `<div class="runtime-item"><div><strong>${esc(item.resource_key)}</strong><p class="${paused ? '' : 'busy'}">${paused ? '保留现场' : '被 #' + esc(String(item.automation_run_id).slice(0, 8)) + ' 占用'} · 已 ${lockAge(item.acquired_at)}</p></div><span class="lock-state ${paused ? 'warn' : 'busy'}">${paused ? '保留' : '占用'}</span></div>`;
      }).join('')
      : '<div class="runtime-empty">当前没有资源锁</div>';
    $('runtimeQueueRows').innerHTML = (data.queue || []).map(item => `<tr><td><code>#${esc(String(item.automation_run_id).slice(0, 8))}</code></td><td>${esc(item.job_name)}</td><td><code>${esc(item.resource_key || '—')}</code></td><td>${fmt(item.queued_at)}</td><td>${item.blocked ? '<span class="queue-state warn">资源等待</span>' : '<span class="queue-state busy">排队中</span>'}</td></tr>`).join('') || '<tr><td colspan="5" class="empty-state">队列为空</td></tr>';
    if (policy) renderPolicy(policy);
  }

  const NOTIFICATION_EVENTS = ['failed', 'needs_human', 'success_with_warnings', 'success', 'no_data', 'cancelled', 'stalled'];

  function renderPolicy(policy) {
    $('notificationEnabled').checked = Boolean(policy.enabled);
    const selected = new Set((policy.event_types || []).map(String));
    state.extraEvents = [...selected].filter(event => !NOTIFICATION_EVENTS.includes(event));
    const writable = can('automation.jobs.manage');
    $('notificationEnabled').disabled = !writable;
    document.querySelectorAll('[data-notification-event]').forEach(input => {
      input.checked = selected.has(input.dataset.notificationEvent);
      input.disabled = !writable;
    });
    const submit = $('notificationPolicyForm')?.querySelector('button[type="submit"]');
    if (submit) submit.hidden = !writable;
    const outbox = policy.outbox || {};
    $('notificationOutboxInfo').textContent = `Outbox：待发送 ${Number(outbox.pending || 0)} · 已发送 ${Number(outbox.sent || 0)} · 失败 ${Number(outbox.failed || 0)}`;
  }

  async function savePolicy(event) {
    event.preventDefault();
    const selected = [...document.querySelectorAll('[data-notification-event]:checked')].map(input => input.dataset.notificationEvent);
    // 未在界面上展示的事件类型（成功 / 无数据 / 取消）保持原样，避免保存时被悄悄丢掉。
    const eventTypes = [...new Set([...selected, ...state.extraEvents])];
    if (!eventTypes.length) return toast('至少选择一个通知事件', 'error');
    await api('/api/automation/notification-policy', { method: 'PUT', body: JSON.stringify({ enabled: $('notificationEnabled').checked, event_types: eventTypes }) });
    toast('飞书通知策略已保存');
    await load();
  }

  /* ---- 跨页动作 ---- */
  async function resumeRun(runId, reason = 'manual', previousStatus = 'needs_human') {
    if (previousStatus === 'failed' && !confirm('确认脚本或运行环境已修复，并从该 Run 未完成的步骤继续？已成功的步骤会使用检查点跳过。')) return null;
    const run = await api('/api/automation/runs/' + encodeURIComponent(runId) + '/resume', { method: 'POST', body: JSON.stringify({ reason: previousStatus === 'failed' ? 'manual_repair' : reason }) });
    toast('原 Run 已恢复排队：' + String(run.automation_run_id).slice(0, 8));
    window.dispatchEvent(new CustomEvent('automation:run-resumed', { detail: { runId: String(run.automation_run_id) } }));
    return run;
  }

  async function acknowledgeRun(runId) {
    const reason = prompt('请输入忽略提醒的原因。此操作只隐藏提醒，原失败记录不会删除。');
    if (reason === null) return;
    if (!reason.trim()) return toast('必须填写忽略原因', 'error');
    await api('/api/automation/runs/' + encodeURIComponent(runId) + '/acknowledge', { method: 'POST', body: JSON.stringify({ reason: reason.trim() }) });
    toast('提醒已忽略；执行记录仍保留');
    window.dispatchEvent(new Event('automation:runs-changed'));
  }

  async function copyRepairContext(componentRunId) {
    const context = await api('/api/automation/components/runs/' + encodeURIComponent(componentRunId) + '/repair-context');
    const value = JSON.stringify(context, null, 2) + '\n\n' + context.repair_prompt;
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(value);
    else window.prompt('复制以下 AI Repair Context', value);
    toast('AI Repair Context 已复制');
  }

  function diffText(diff) {
    diff = diff || {};
    const parts = [];
    if (diff.nodes_added) parts.push('节点 +' + diff.nodes_added);
    if (diff.nodes_removed) parts.push('节点 -' + diff.nodes_removed);
    if (diff.nodes_changed) parts.push('节点修改 ' + diff.nodes_changed);
    if (diff.edges_added) parts.push('连线 +' + diff.edges_added);
    if (diff.edges_removed) parts.push('连线 -' + diff.edges_removed);
    return parts.length ? parts.join(' · ') : '与当前定义一致';
  }

  async function showFlowVersions(flowId) {
    const data = await api('/api/automation/flows/' + encodeURIComponent(flowId) + '/versions');
    const dialog = $('detailDialog'), content = $('detailContent');
    if (!dialog || !content) return;
    const rows = (data.items || []).map(item => {
      const rollback = can('automation.flows.manage') && !item.is_current
        ? `<button class="button compact" data-rollback-version="${esc(item.version)}" data-flow-id="${esc(flowId)}">恢复为新版本</button>` : '';
      return `<div class="version-item"><div class="version-main"><div><strong>v${esc(item.version)}</strong> ${item.is_current ? '<span class="status-tag success">当前</span>' : ''}</div><p>${esc(item.execution_lane)} · ${esc(item.node_count)} 节点 · ${esc(item.edge_count)} 连线 · ${fmt(item.published_at)}</p><small>${esc(diffText(item.diff_from_current))} · 发布人 ${esc(item.published_by || '—')}</small></div>${rollback}</div>`;
    }).join('');
    content.innerHTML = `<h2>${esc(data.flow_name)} · 版本历史</h2><p class="muted">当前 v${esc(data.current_version)} · ${esc(data.current_status)}。回滚不会覆盖历史，而是从旧版本生成新的发布版本。</p><div class="version-list">${rows || empty('暂无发布版本')}</div>`;
    if (!dialog.open) dialog.showModal();
  }

  async function rollbackVersion(flowId, version) {
    if (!confirm('确定把该历史版本恢复为新的发布版本吗？旧版本与当前版本都会保留。')) return;
    const result = await api('/api/automation/flows/' + encodeURIComponent(flowId) + '/versions/' + encodeURIComponent(version) + '/rollback', { method: 'POST', body: '{}' });
    toast('已生成新版本 v' + result.version);
    window.dispatchEvent(new CustomEvent('automation:flows-changed'));
    await showFlowVersions(flowId);
  }

  document.addEventListener('click', async event => {
    const button = event.target.closest('main button, .automation-dialog button');
    if (!button) return;
    try {
      if (button.dataset.resume) await resumeRun(button.dataset.resume, 'manual', button.dataset.resumeStatus);
      if (button.dataset.attentionAck) await acknowledgeRun(button.dataset.attentionAck);
      if (button.dataset.faultRepair) await copyRepairContext(button.dataset.faultRepair);
      if (button.dataset.rollbackVersion) await rollbackVersion(button.dataset.flowId, button.dataset.rollbackVersion);
      if (button.dataset.versionTask) {
        const data = await api('/api/automation/jobs');
        const job = (data.items || []).find(item => (item.task_key || String(item.job_id)) === button.dataset.versionTask);
        if (job?.flow_id) await showFlowVersions(job.flow_id);
      }
    } catch (error) { toast(error.message, 'error'); }
  });

  $('notificationPolicyForm')?.addEventListener('submit', event => savePolicy(event).catch(error => toast(error.message, 'error')));

  window.AutomationOpsCenter = { load, showFlowVersions, resumeRun, acknowledgeRun, copyRepairContext, rollbackVersion };
})();
