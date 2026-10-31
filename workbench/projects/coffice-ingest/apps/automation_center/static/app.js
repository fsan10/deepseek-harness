/* 路由 + 运行中心 + 任务调度 + 执行详情。 */
(function () {
  const { $, esc, api, toast, can, today, fmt, timeOnly, labels, statusTag } = window.AutomationUI;

  const triggerLabels = { manual: '手工', schedule: '计划', retry: '重试' };
  const triggerText = value => triggerLabels[value] || value || '—';
  const pageMeta = {
    reports: ['报表任务', '按执行日期查看任务进度，按业务日期核对报表覆盖范围'],
    runs: ['运行中心', '单次执行的追溯与人工干预；每日完成情况请看报表任务'],
    schedules: ['任务调度', '只定义触发时间、lane、超时与重试；结果与异常去运行中心'],
    'flow-studio': ['流程编排', '从组件库拖拽组合 Flow；发布后形成不可变版本快照'],
    runtime: ['系统运行', 'Worker 心跳、资源锁、运行队列与飞书通知'],
  };
  const LIVE_RUN_STATUSES = new Set(['queued', 'running', 'needs_human']);
  const TERMINAL_RUN_STATUSES = new Set(['success', 'success_with_warnings', 'no_data', 'failed', 'cancelled', 'skipped']);
  const state = { jobs: [], jobPage: 1, jobPageSize: 10, jobFilters: {}, runPage: 1, runPageSize: 20, detailPollTimer: null, detailRunId: null, detailCache: new Map(), detailRequest: null };
  const DETAIL_CACHE_MS = 10000;

  function showPage() {
    const key = (location.hash.slice(1) || 'reports');
    const known = pageMeta[key] ? key : 'reports';
    document.querySelectorAll('.page').forEach(node => node.classList.toggle('active', node.id === `${known}Page`));
    const meta = pageMeta[known];
    $('pageTitle').textContent = meta[0];
    $('pageSubtitle').textContent = meta[1];
    loadPage(known).catch(error => toast(error.message, 'error'));
  }

  function loadPage(key) {
    if (key === 'reports') return window.AutomationReports?.load();
    if (key === 'runs') { if (!state.jobs.length) return loadJobs().then(loadRuns); return loadRuns(); }
    if (key === 'schedules') return loadJobs();
    if (key === 'flow-studio') return window.AutomationFlowStudio?.load();
    if (key === 'runtime') return window.AutomationOpsCenter?.load();
  }

  /* ---------------- 运行中心 ---------------- */
  function runPageSize() { const value = Number($('runPageSize')?.value || state.runPageSize); return Number.isFinite(value) && value > 0 ? value : state.runPageSize; }
  function safeRunPage() { return Number.isFinite(state.runPage) && state.runPage > 0 ? Math.floor(state.runPage) : 1; }

  function runQuery() {
    const query = new URLSearchParams({ page: String(safeRunPage()), page_size: String(runPageSize()) });
    if ($('runStatus').value) query.set('status', $('runStatus').value);
    [['date_from', 'runDateFrom'], ['date_to', 'runDateTo'], ['keyword', 'runKeyword']].forEach(([key, id]) => {
      const value = String($(id)?.value || '').trim(); if (value) query.set(key, value);
    });
    const task = String($('runJob')?.value || '').trim();
    if (task.startsWith('flow:')) query.set('flow_id', task.slice(5));
    else if (task) query.set('job_id', task);
    return query;
  }

  function getPageNumbers(current, total, maxVisible = 5) {
    if (total <= 1) return [1];
    if (total <= maxVisible) return Array.from({ length: total }, (_, i) => i + 1);
    let start = Math.max(1, current - Math.floor(maxVisible / 2));
    let end = start + maxVisible - 1;
    if (end > total) { end = total; start = Math.max(1, end - maxVisible + 1); }
    return Array.from({ length: end - start + 1 }, (_, i) => start + i);
  }

  function goToRunPage(page) { if (!Number.isFinite(page) || page < 1) return; state.runPage = Math.floor(page); loadRuns().catch(error => toast(error.message, 'error')); }

  function renderRunPagination(current, pages) {
    $('runPageInfo').textContent = `第 ${current}/${pages} 页`;
    $('runPrevPage').disabled = current <= 1;
    $('runNextPage').disabled = current >= pages;
    $('runPrevPage').onclick = () => { if (current > 1) goToRunPage(current - 1); };
    $('runNextPage').onclick = () => { if (current < pages) goToRunPage(current + 1); };
    const node = $('runPageNumbers');
    node.innerHTML = getPageNumbers(current, pages).map(page => `<button class="pagination-page-btn ${page === current ? 'is-active' : ''}" type="button" data-run-page="${page}" aria-label="第 ${page} 页" ${page === current ? 'aria-current="page"' : ''}>${page}</button>`).join('');
    node.querySelectorAll('.pagination-page-btn').forEach(button => { button.onclick = () => goToRunPage(Number(button.dataset.runPage)); });
  }

  async function loadRuns() {
    const data = await api('/api/automation/runs?' + runQuery());
    state.runPage = data.page;
    const counts = data.counts || {};
    $('runToolbarStats').innerHTML = `<span>全部 <b>${Number(counts.total ?? data.total ?? 0)}</b></span><span>失败 <b>${Number(counts.failed || 0)}</b></span>`;
    $('runRows').innerHTML = (data.items || []).map(item => {
      const id = esc(item.automation_run_id);
      const retry = can('automation.runs.retry') && ['cancelled', 'success_with_warnings'].includes(item.status) ? `<button class="link-button" type="button" data-retry="${id}"><svg><use href="#i-refresh"/></svg>重试</button>` : '';
      const cancel = can('automation.runs.execute') && ['queued', 'running', 'needs_human'].includes(item.status) ? `<button class="link-button" type="button" data-cancel="${id}"><svg><use href="#i-close"/></svg>取消</button>` : '';
      const subtitle = item.resource_key && item.resource_key !== item.execution_lane ? item.resource_key : '';
      const sameDay = item.started_at && item.finished_at && new Date(item.started_at).toDateString() === new Date(item.finished_at).toDateString();
      const timeCell = sameDay ? `${timeOnly(item.started_at)} → ${timeOnly(item.finished_at)}` : `${fmt(item.started_at)}<br><small class="muted">${fmt(item.finished_at)}</small>`;
      return `<tr class="${item.status === 'running' ? 'is-running' : ''}"><td><code>${esc(String(item.automation_run_id).slice(0, 8))}</code></td>
        <td><strong>${esc(item.job_name)}</strong>${item.flow_version ? ` <span class="status-tag ready">v${esc(item.flow_version)}</span>` : ''}${subtitle ? `<br><small class="muted">${esc(subtitle)}</small>` : ''}</td>
        <td>${esc(triggerText(item.trigger_type))} · ${esc(item.execution_lane || '—')}</td>
        <td>${statusTag(item.status)}</td><td>${esc(item.business_date)}</td>
        <td>${timeCell}</td>
        <td>${Number(item.step_count || 0)} / ${Number(item.artifact_count || 0)}</td>
        <td><div class="row-actions"><button class="link-button" type="button" data-detail="${id}"><svg><use href="#i-eye"/></svg>详情</button>${retry}${cancel}</div></td></tr>`;
    }).join('') || '<tr><td colspan="8" class="empty-state">暂无执行记录</td></tr>';
    $('runTotal').textContent = '共 ' + data.total + ' 条';
    renderRunPagination(data.page, data.pages);
  }

  /* ---------------- 任务调度 ---------------- */
  function scheduleText(job) { return job.schedule_type === 'manual' ? '仅手工' : `${(job.schedule_config?.times || []).join('、')} · ${job.timezone}`; }
  function durationText(seconds) { const value = Number(seconds); if (!Number.isFinite(value) || value <= 0) return '—'; if (value < 60) return value.toFixed(0) + ' 秒'; if (value < 3600) return (value / 60).toFixed(1) + ' 分钟'; return (value / 3600).toFixed(1) + ' 小时'; }
  function taskHealth(job) {
    const total = Number(job.runs_7d || 0), success = Number(job.success_7d || 0), failed = Number(job.failed_7d || 0);
    const rate = total ? Math.round(success / total * 100) : null;
    return `<div class="task-health ${failed ? 'has-failure' : ''}"><strong>${rate == null ? '暂无运行' : rate + '%'}</strong><small>7 日 ${success}/${total} · 失败 ${failed}</small><small>均耗时 ${durationText(job.avg_duration_seconds)}</small></div>`;
  }

  async function loadJobs() {
    const data = await api('/api/automation/jobs');
    state.jobs = data.items || [];
    $('runJob').innerHTML = '<option value="">全部任务</option>' + state.jobs.map(job => `<option value="${esc(job.source_kind === 'flow' ? 'flow:' + job.flow_id : String(job.job_id))}">${esc(job.job_name)}</option>`).join('');
    [['jobPlatform', 'platforms', '全部平台'], ['jobReport', 'report_names', '全部报表']].forEach(([id, key, label]) => {
      const node = $(id); if (!node) return;
      const value = node.value;
      const options = [...new Set(state.jobs.flatMap(job => job[key] || []))].sort();
      node.innerHTML = `<option value="">${label}</option>` + options.map(option => `<option>${esc(option)}</option>`).join('');
      if (options.includes(value)) node.value = value;
    });
    renderJobs();
  }

  function renderJobs() {
    const filters = state.jobFilters;
    const jobs = state.jobs.filter(job =>
      (!filters.status || Boolean(job.enabled) === (filters.status === 'enabled')) &&
      (!filters.platform || (job.platforms || []).includes(filters.platform)) &&
      (!filters.report || (job.report_names || []).includes(filters.report)) &&
      (!filters.schedule || job.schedule_type === filters.schedule) &&
      (!filters.keyword || [job.job_name, ...(job.platforms || []), ...(job.report_names || [])].join(' ').toLocaleLowerCase().includes(filters.keyword.toLocaleLowerCase())));
    const size = Number($('jobPageSize').value) || 10;
    const pages = Math.max(1, Math.ceil(jobs.length / size));
    state.jobPage = Math.min(Math.max(1, state.jobPage), pages);
    $('jobTotal').textContent = `共 ${jobs.length} 条`;
    $('jobPageInfo').textContent = `第 ${state.jobPage}/${pages} 页`;
    $('jobPrevPage').disabled = state.jobPage <= 1;
    $('jobNextPage').disabled = state.jobPage >= pages;
    $('jobPageNumbers').innerHTML = getPageNumbers(state.jobPage, pages).map(page => `<button type="button" class="pagination-page-btn ${page === state.jobPage ? 'is-active' : ''}" data-job-page="${page}" ${page === state.jobPage ? 'aria-current="page"' : ''}>${page}</button>`).join('');
    $('jobRows').innerHTML = jobs.slice((state.jobPage - 1) * size, state.jobPage * size).map(job => {
      const isFlow = job.source_kind === 'flow';
      const version = isFlow ? ` <span class="status-tag ready">v${esc(job.flow_version)}</span>` : '';
      const runAllowed = (isFlow ? can('automation.flows.execute') : can('automation.runs.execute')) && job.enabled;
      const manageAllowed = isFlow ? can('automation.flows.manage') : can('automation.jobs.manage');
      const key = esc(job.task_key || String(job.job_id));
      const retryText = `${Number(job.retry_policy?.max_attempts || 1)} 次`;
      return `<tr><td><strong>${esc(job.job_name)}</strong>${version}<br><small class="muted">${esc(job.job_code)}</small></td>
        <td>${esc(job.job_type)} · ${esc(job.execution_lane)}${isFlow && job.default_profile_name ? `<br><small class="muted">${esc(job.default_profile_name)}</small>` : ''}</td>
        <td>${esc(scheduleText(job))}</td>
        <td>${Number(job.timeout_seconds || 0)}s · ${retryText}</td>
        <td>${job.enabled ? '<span class="status-tag success">启用</span>' : '<span class="status-tag disabled">停用</span>'}</td>
        <td>${job.recent_status ? statusTag(job.recent_status) : '<span class="muted">—</span>'}<br><small class="muted">${fmt(job.recent_finished_at)}</small></td>
        <td>${taskHealth(job)}</td>
        <td><div class="row-actions">
          ${can('automation.runs.view') ? `<button class="link-button" type="button" data-view-task="${key}"><svg><use href="#i-list"/></svg>步骤</button>` : ''}
          ${runAllowed ? `<button class="link-button" type="button" data-run-task="${key}"><svg><use href="#i-play"/></svg>立即运行</button>` : ''}
          ${manageAllowed ? `<button class="link-button" type="button" data-config-task="${key}"><svg><use href="#i-calendar"/></svg>调度</button>` : ''}
          ${manageAllowed ? `<button class="link-button ${job.enabled ? 'status-disable' : 'status-enable'}" type="button" data-toggle-task="${key}"><svg><use href="#i-power"/></svg>${job.enabled ? '停用' : '启用'}</button>` : ''}
        </div></td></tr>`;
    }).join('') || '<tr><td colspan="8" class="empty-state">暂无符合条件的任务</td></tr>';
  }

  /* ---------------- 执行详情 ---------------- */
  function timelineState(status) {
    if (status === 'running') return 'is-running';
    if (['success', 'no_data'].includes(status)) return 'is-success';
    if (['failed', 'cancelled'].includes(status)) return 'is-failed';
    if (['success_with_warnings', 'needs_human', 'partial_failed', 'deferred'].includes(status)) return 'is-warning';
    if (status === 'skipped') return 'is-muted';
    return 'is-pending';
  }
  function elapsedText(item) {
    if (item?.duration_seconds != null && Number.isFinite(Number(item.duration_seconds))) return Number(item.duration_seconds).toFixed(2) + ' 秒';
    if (item?.started_at && ['running', 'needs_human'].includes(item.status)) return Math.max(0, (Date.now() - new Date(item.started_at).getTime()) / 1000).toFixed(1) + ' 秒（进行中）';
    return '—';
  }
  function timelineHtml(items) {
    const normalized = (items || []).map(item => ({ ...item, status: item.status || 'ready' }));
    return '<div class="timeline">' + normalized.map((item, index) => {
      const status = item.status;
      const statusHtml = item.status_label ? `<span class="status-tag ${esc(status)}">${esc(item.status_label)}</span>` : statusTag(status);
      const timeHtml = item.time ? `<small> · ${fmt(item.time)}</small>` : '';
      const metaHtml = item.meta ? `<small> · ${esc(item.meta)}</small>` : '';
      const next = normalized[index + 1];
      const nextState = next ? timelineState(next.status).replace(/^is-/, '') : '';
      const nextAttr = nextState ? ` data-next-state="${esc(nextState)}"` : '';
      return `<div class="timeline-step ${timelineState(status)}" data-status="${esc(status)}"${nextAttr}><div class="timeline-rail" aria-hidden="true"><span class="timeline-dot"></span></div><div class="timeline-card"><div class="timeline-title-row"><div><strong>${esc(item.title)}</strong> ${statusHtml}${timeHtml}${metaHtml}</div></div>${item.detail ? `<p>${esc(item.detail)}</p>` : ''}</div></div>`;
    }).join('') + '</div>';
  }
  function stopDetailPolling() { if (state.detailPollTimer) { clearTimeout(state.detailPollTimer); state.detailPollTimer = null; } }
  function scheduleDetailPolling(callback) {
    stopDetailPolling();
    state.detailPollTimer = setTimeout(() => { state.detailPollTimer = null; if (!$('detailDialog')?.open) return; Promise.resolve(callback()).catch(error => toast(error.message, 'error')); }, 1000);
  }
  function openDetailDialog() { if (!$('detailDialog').open) $('detailDialog').showModal(); }
  function runNeedsPolling(run) { return Boolean(run && LIVE_RUN_STATUSES.has(run.status)); }

  function runTimeline(item, stepDetail) {
    const runStatus = item.status || 'queued';
    const createdAt = item.queued_at || item.created_at || null;
    const resumed = Number(item.resume_count || 0) > 0;
    const workerTime = item.attempt_started_at || (!resumed ? item.started_at : null);
    const wasClaimed = resumed ? Boolean(item.attempt_started_at) : Boolean(item.started_at || item.worker_id || Number(item.attempt_count || 0) > 0 || (TERMINAL_RUN_STATUSES.has(runStatus) && runStatus !== 'cancelled'));
    const workerStatus = wasClaimed ? 'success' : (runStatus === 'running' ? 'running' : (runStatus === 'queued' ? 'queued' : 'ready'));
    const workerLabel = wasClaimed ? '已领取' : (runStatus === 'running' ? '领取中' : (runStatus === 'queued' ? (resumed ? '等待重新领取' : '等待领取') : '未领取'));
    const isFinished = Boolean(item.finished_at || TERMINAL_RUN_STATUSES.has(runStatus));
    const steps = (item.steps || []).map(step => ({
      title: `${step.platform_name || '系统'} / ${step.shop_name || '全局'} · ${step.step_name}`,
      time: step.started_at, status: step.status || 'ready', meta: elapsedText(step), detail: stepDetail(step),
    }));
    return [
      { title: '计划创建', time: createdAt, status: 'success', status_label: '已创建' },
      { title: 'Worker 领取', time: workerTime, status: workerStatus, status_label: workerLabel },
      ...steps,
      { title: '完成', time: item.finished_at, status: isFinished ? runStatus : 'ready', detail: item.error_message || item.warning_message || '' },
    ];
  }

  function renderRunDetail(item) {
    const stepDetail = step => {
      const files = (step.artifacts || []).map(file => `文件：${file.file_name} · ${file.file_size_bytes} bytes · ${file.report_type || '待识别'} · ingest_file_task=${file.ingest_file_task_id || '—'}`);
      const etls = (step.etl_tasks || []).map(task => `ETL：${task.etl_label} · ${labels[task.status] || task.status}`);
      const components = (step.components || []).map(component => {
        const events = (component.events || []).map(event => `${event.event_type}${event.message ? '：' + event.message : ''}`).join(' / ');
        return `${component.parent_component_run_id ? '↳ 子组件' : '流程组件'} #${component.sequence_no}：${component.component_name} [${component.component_code}] · ${labels[component.status] || component.status} · ${component.duration_seconds ?? '—'} 秒${component.error_type ? ' · ' + component.error_type : ''}${component.error_message ? ' · ' + component.error_message : ''}${events ? ' · 事件 ' + events : ''}`;
      });
      return [step.profile_name ? `Profile：${step.profile_name}` : '', step.error_message, step.exit_code != null ? `exit code: ${step.exit_code}` : '', `业务日期：${step.business_date_start || '—'} → ${step.business_date_end || '—'}`, `耗时：${elapsedText(step)}`, ...components, ...files, ...etls].filter(Boolean).join('\n');
    };
    const steps = item.steps || [];
    const latestSequence = Math.max(0, ...steps.map(step => Number(step.sequence_no || 0)));
    const hasUnansweredHandoff = component => {
      const events = component.events || [];
      return events.some(event => event.event_type === 'waiting_human') && !events.some(event => event.event_type === 'human_answered');
    };
    const activeHuman = ['running', 'needs_human'].includes(item.status)
      ? steps.filter(step => Number(step.sequence_no || 0) === latestSequence).flatMap(step => (step.components || []).filter(component => component.status === 'needs_human' || hasUnansweredHandoff(component)))
      : [];
    const activeHumanIds = new Set(activeHuman.map(component => component.component_run_id));
    const currentAttemptIds = new Set(steps.filter(step => !item.resumed_at || (step.started_at && new Date(step.started_at) >= new Date(item.resumed_at))).flatMap(step => step.components || []).map(component => component.component_run_id));
    const allHistorical = steps.flatMap(step => (step.components || []).filter(component => ['failed', 'needs_human'].includes(component.status))).filter(component => !activeHumanIds.has(component.component_run_id));
    const actualFailures = item.status === 'failed' ? allHistorical.filter(component => component.status === 'failed' && currentAttemptIds.has(component.component_run_id)) : [];
    const history = allHistorical.filter(component => !actualFailures.includes(component));
    const canAct = can('automation.runs.retry');
    const recoveryHtml = canAct && ['needs_human', 'failed'].includes(item.status)
      ? `<div class="detail-actions"><button class="button primary" data-resume="${esc(item.automation_run_id)}" data-resume-status="${esc(item.status)}">${item.status === 'failed' ? '脚本修复后继续' : '继续任务'}</button></div>` : '';
    const humanHtml = activeHuman.length
      ? `<section class="panel human-detail-panel"><div class="panel-heading"><div><h2>等待人工处理</h2><p>先去平台完成验证；超时后可通过“继续任务”接回原 Run。</p></div></div><div class="compact-list">${activeHuman.map(component => `<div class="compact-item"><div><strong>${esc(component.component_name)}</strong><p>${esc(component.component_code)}${component.verification_challenge_id ? ' · Challenge：' + esc(component.verification_challenge_id) : ' · 无关联 Challenge'}${component.error_message ? ' · ' + esc(component.error_message) : ''}</p></div>${statusTag('needs_human')}</div>`).join('')}</div></section>` : '';
    const panelList = components => components.map(component => `<div class="compact-item"><div><strong>${esc(component.component_name)}</strong><p>${esc(component.component_code)} · ${esc(component.error_type || component.status)}${component.screenshot_path ? ' · screenshot ' + esc(component.screenshot_path) : ''}</p></div><button class="button compact" type="button" data-fault-repair="${esc(component.component_run_id)}">复制 AI 修复上下文</button></div>`).join('');
    const repairHtml = actualFailures.length
      ? `<section class="panel repair-detail-panel"><div class="panel-heading"><div><h2>失败原子组件 / AI Repair Context</h2><p>当前 Run 失败。修复后使用“脚本修复后继续”。</p></div></div><div class="compact-list">${panelList(actualFailures)}</div></section>` : '';
    const historyHtml = history.length
      ? `<section class="panel history-detail-panel"><div class="panel-heading"><div><h2>历史异常记录</h2><p>较早尝试留下的记录，不代表当前运行仍在失败。</p></div></div><div class="compact-list">${panelList(history)}</div></section>` : '';
    $('detailContent').innerHTML = `<h2>${esc(item.job_name)}${item.flow_version ? ' · v' + esc(item.flow_version) : ''}</h2>
      <div class="detail-grid">
        <div class="detail-field"><small>Automation Run</small>${esc(item.automation_run_id)}</div>
        <div class="detail-field"><small>状态</small>${statusTag(item.status)}</div>
        <div class="detail-field"><small>业务基准日</small>${esc(item.business_date)}</div>
        <div class="detail-field"><small>资源锁</small>${esc(item.resource_key || '—')}</div>
        <div class="detail-field"><small>执行 lane</small>${esc(item.execution_lane || '—')}</div>
        <div class="detail-field"><small>Worker</small>${esc(item.worker_id || '—')}</div>
        <div class="detail-field"><small>本次尝试开始</small>${fmt(item.attempt_started_at || item.started_at)}</div>
        <div class="detail-field"><small>恢复次数</small>${Number(item.resume_count || 0)}</div>
      </div>${recoveryHtml}${humanHtml}${repairHtml}${historyHtml}${timelineHtml(runTimeline(item, stepDetail))}`;
    openDetailDialog();
  }

  async function openRunDetail(runId, quiet = false, force = false) {
    stopDetailPolling();
    const cached = state.detailCache.get(runId);
    const fresh = !force && cached && Date.now() - cached.at < DETAIL_CACHE_MS;
    if (fresh) {
      state.detailRunId = runId;
      renderRunDetail(cached.item);
      if (runNeedsPolling(cached.item)) scheduleDetailPolling(() => openRunDetail(runId, true, true));
      return;
    }
    if (!quiet) {
      // 先给出弹窗与骨架，避免大 Payload 返回前“点了没反应”。
      state.detailRunId = runId;
      $('detailContent').innerHTML = '<div class="detail-loading"><span class="spinner"></span>正在加载执行详情…</div>';
      openDetailDialog();
    }
    if (state.detailRequest?.runId === runId) return;
    if (state.detailRequest) state.detailRequest.controller.abort();
    const controller = new AbortController();
    state.detailRequest = { runId, controller };
    try {
      const item = await api(`/api/automation/runs/${runId}`, { signal: controller.signal });
      state.detailCache.set(runId, { at: Date.now(), item });
      while (state.detailCache.size > 10) state.detailCache.delete(state.detailCache.keys().next().value);
      if (quiet && !$('detailDialog')?.open) return;
      renderRunDetail(item);
      if (runNeedsPolling(item)) scheduleDetailPolling(() => openRunDetail(runId, true, true));
    } catch (error) {
      if (error?.name === 'AbortError') return;
      throw error;
    } finally {
      if (state.detailRequest?.controller === controller) state.detailRequest = null;
    }
  }

  /* ---------------- 任务步骤 ---------------- */
  async function viewJob(job, quiet = false) {
    stopDetailPolling();
    const recent = job?.recent_run_id ? await api('/api/automation/runs/' + job.recent_run_id).catch(() => null) : null;
    if (quiet && !$('detailDialog')?.open) return;
    if (job?.source_kind === 'flow') {
      const flow = await api('/api/automation/flows/' + job.flow_id);
      const nodes = flow.definition?.nodes || [];
      if (quiet && !$('detailDialog')?.open) return;
      const runtimeMap = new Map();
      const unmatched = (recent?.steps || []).flatMap(step => (step.components || []).filter(component => !component.parent_component_run_id));
      nodes.forEach(node => {
        let index = unmatched.findIndex(component => component.input_snapshot?.node_id === node.id);
        if (index < 0) index = unmatched.findIndex(component => component.component_code === node.component_code);
        if (index >= 0) { runtimeMap.set(node.id, unmatched[index]); unmatched.splice(index, 1); }
      });
      const items = nodes.map((node, index) => {
        const runtime = runtimeMap.get(node.id);
        const status = runtime?.status || (node.enabled === false ? 'skipped' : 'ready');
        return { title: '#' + (index + 1) + ' ' + (node.name || node.component_code), status, status_label: !runtime && node.enabled !== false ? '未运行' : '', meta: runtime ? elapsedText(runtime) : '—', detail: node.component_code + (runtime?.error_message ? ' · ' + runtime.error_message : '') };
      });
      $('detailContent').innerHTML = `<h2>${esc(flow.flow_name)} · v${esc(flow.version)} · 步骤</h2><p class="muted">${esc(flow.description || '')}</p>${timelineHtml(items)}`;
      openDetailDialog();
      if (runNeedsPolling(recent)) scheduleDetailPolling(() => viewJob(job, true));
      return;
    }
    const item = await api('/api/automation/jobs/' + job.job_id);
    const rows = recent?.steps?.length ? recent.steps : item.steps;
    const items = rows.map((step, index) => {
      const executed = step.step_run_id != null;
      return { title: '#' + (index + 1) + ' ' + (step.platform_name || step.platform || '系统') + ' · ' + (step.step_name || step.name), status: executed ? (step.status || 'ready') : 'ready', status_label: executed ? '' : '未运行', meta: executed ? elapsedText(step) : '—', detail: (step.module_name || step.module || '') + ' · ' + (step.execution_lane || step.lane || '') + (step.error_message ? ' · ' + step.error_message : '') };
    });
    $('detailContent').innerHTML = `<h2>${esc(item.job_name)} · 任务步骤</h2><p class="muted">${esc(item.description || '')}</p>${timelineHtml(items)}`;
    openDetailDialog();
    if (runNeedsPolling(recent)) scheduleDetailPolling(() => viewJob(job, true));
  }

  function editJob(job) {
    const isFlow = job.source_kind === 'flow';
    $('jobSourceKind').value = isFlow ? 'flow' : 'job';
    $('jobId').value = isFlow ? '' : job.job_id;
    $('jobFlowId').value = isFlow ? job.flow_id : '';
    $('jobDialogTitle').textContent = isFlow ? '配置 Flow 自动化任务' : '编辑调度';
    $('jobProfileField').hidden = !isFlow;
    $('jobProfile').value = isFlow ? (job.default_profile_name || '') : '';
    $('jobScheduleType').value = job.schedule_type;
    $('jobTimes').value = (job.schedule_config?.times || []).join(', ');
    $('jobTimezone').value = job.timezone;
    $('jobTimeout').value = job.timeout_seconds;
    $('jobAttempts').value = job.retry_policy?.max_attempts || 1;
    $('jobDescription').value = job.description || '';
    const deletable = can(isFlow ? 'automation.flows.manage' : 'automation.jobs.manage');
    $('deleteJobBtn').hidden = !deletable;
    $('deleteJobBtn').dataset.deleteTarget = isFlow ? 'flow:' + job.flow_id : 'job:' + job.job_id;
    $('deleteJobBtn').dataset.deleteName = job.job_name;
    $('jobDialog').showModal();
  }

  /* ---------------- 事件 ---------------- */
  document.addEventListener('click', async event => {
    const button = event.target.closest('main button');
    if (!button) return;
    try {
      if (button.dataset.runPage) { state.runPage = Number(button.dataset.runPage); await loadRuns(); }
      if (button.dataset.jobPage) { state.jobPage = Number(button.dataset.jobPage); renderJobs(); }
      if (button.dataset.detail) await openRunDetail(button.dataset.detail);
      const findTask = key => state.jobs.find(item => (item.task_key || String(item.job_id)) === key);
      if (button.dataset.viewTask) { const job = findTask(button.dataset.viewTask); if (job) await viewJob(job); }
      if (button.dataset.configTask) { const job = findTask(button.dataset.configTask); if (job) editJob(job); }
      if (button.dataset.toggleTask) {
        const job = findTask(button.dataset.toggleTask); if (!job) return;
        const enabled = !job.enabled;
        if (job.source_kind === 'flow') await api('/api/automation/flows/' + job.flow_id + '/enabled', { method: 'POST', body: JSON.stringify({ enabled }) });
        else await api('/api/automation/jobs/' + job.job_id + '/enabled', { method: 'POST', body: JSON.stringify({ enabled }) });
        toast(enabled ? '任务已启用' : '任务已停用');
        await loadJobs();
      }
      if (button.dataset.runTask) {
        const job = findTask(button.dataset.runTask); if (!job) return;
        if (!job.enabled) return toast('任务已停用', 'error');
        if (job.source_kind === 'flow') {
          if (job.default_profile_name || job.execution_lane === 'etl') {
            const payload = { business_date: today() };
            if (job.default_profile_name) payload.profile_name = job.default_profile_name;
            const run = await api('/api/automation/flows/' + job.flow_id + '/run', { method: 'POST', body: JSON.stringify(payload) });
            toast('Flow 已入队：' + run.automation_run_id);
            await loadRuns();
          } else await window.AutomationFlowStudio?.run(job.flow_id);
        } else {
          const run = await api('/api/automation/jobs/' + job.job_id + '/run', { method: 'POST', body: JSON.stringify({ business_date: today() }) });
          toast('任务已入队：' + run.automation_run_id);
          await loadRuns();
        }
      }
      if (button.dataset.retry) {
        const run = await api('/api/automation/runs/' + button.dataset.retry + '/retry', { method: 'POST', body: '{}' });
        toast('重试已入队：' + run.automation_run_id);
        await loadRuns();
      }
      if (button.dataset.cancel) {
        await api('/api/automation/runs/' + button.dataset.cancel + '/cancel', { method: 'POST', body: '{}' });
        toast('已请求取消');
        await loadRuns();
      }
    } catch (error) { toast(error.message, 'error'); }
  });

  $('queryRuns').onclick = () => { state.runPage = 1; loadRuns().catch(error => toast(error.message, 'error')); };
  $('resetRuns').onclick = () => {
    ['runStatus', 'runJob', 'runKeyword'].forEach(id => { if ($(id)) $(id).value = ''; });
    window.DateRange?.clear('runDateFrom', 'runDateTo');
    state.runPage = 1;
    loadRuns().catch(error => toast(error.message, 'error'));
  };
  $('runStatus').onchange = () => loadRuns().catch(error => toast(error.message, 'error'));
  $('runPageSize').onchange = () => { state.runPageSize = runPageSize(); state.runPage = 1; loadRuns().catch(error => toast(error.message, 'error')); };
  $('runsToolbar').addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); $('queryRuns').click(); } });
  $('refreshPage').onclick = () => loadPage(location.hash.slice(1) || 'reports').catch(error => toast(error.message, 'error'));

  $('searchJobs').onclick = () => {
    state.jobFilters = { status: $('jobStatus').value, platform: $('jobPlatform').value, report: $('jobReport').value, schedule: $('jobSchedule').value, keyword: $('jobKeyword').value.trim() };
    state.jobPage = 1; renderJobs();
  };
  $('resetJobs').onclick = () => { ['jobStatus', 'jobPlatform', 'jobReport', 'jobSchedule', 'jobKeyword'].forEach(id => $(id).value = ''); state.jobFilters = {}; state.jobPage = 1; renderJobs(); };
  $('jobKeyword').onkeydown = event => { if (event.key === 'Enter') $('searchJobs').click(); };
  $('jobPageSize').onchange = () => { state.jobPage = 1; renderJobs(); };
  $('jobPrevPage').onclick = () => { state.jobPage -= 1; renderJobs(); };
  $('jobNextPage').onclick = () => { state.jobPage += 1; renderJobs(); };
  $('jobForm').onsubmit = async event => {
    event.preventDefault();
    try {
      const scheduleType = $('jobScheduleType').value;
      const times = $('jobTimes').value.split(',').map(item => item.trim()).filter(Boolean);
      const isFlow = $('jobSourceKind').value === 'flow';
      const payload = { schedule_type: scheduleType, schedule_config: scheduleType === 'daily' ? { times } : {}, timezone: $('jobTimezone').value, timeout_seconds: Number($('jobTimeout').value), retry_policy: { max_attempts: Number($('jobAttempts').value) }, description: $('jobDescription').value };
      if (isFlow) payload.default_profile_name = $('jobProfile').value.trim();
      const endpoint = isFlow ? '/api/automation/flows/' + $('jobFlowId').value : '/api/automation/jobs/' + $('jobId').value;
      await api(endpoint, { method: 'PUT', body: JSON.stringify(payload) });
      $('jobDialog').close();
      toast('调度配置已更新');
      await loadJobs();
    } catch (error) { toast(error.message, 'error'); }
  };
  $('closeJobDialog').onclick = $('cancelJobDialog').onclick = () => $('jobDialog').close();
  $('deleteJobBtn').onclick = async () => {
    const target = $('deleteJobBtn').dataset.deleteTarget || '';
    const name = $('deleteJobBtn').dataset.deleteName || '';
    if (!confirm(`确定删除任务「${name}」吗？历史运行记录会保留。`)) return;
    try {
      const [kind, id] = target.split(':');
      await api(kind === 'flow' ? '/api/automation/flows/' + id : '/api/automation/jobs/' + id, { method: 'DELETE' });
      $('jobDialog').close();
      toast('任务已删除');
      window.dispatchEvent(new CustomEvent('automation:flows-changed'));
      await loadJobs();
    } catch (error) { toast(error.message, 'error'); }
  };
  $('detailDialog').addEventListener('close', stopDetailPolling);
  $('detailDialog').addEventListener('cancel', stopDetailPolling);

  $('runStatus').innerHTML += [...Object.keys(labels)].filter(key => !['draft', 'ready', 'processing', 'no_change', 'partial_failed', 'deferred', 'uploaded', 'duplicate', 'unverified', 'missing', 'missing_file', 'monthly_only', 'not_ready'].includes(key)).map(key => `<option value="${key}">${labels[key]}</option>`).join('');

  window.addEventListener('automation:run-resumed', event => {
    if ($('detailDialog')?.open && state.detailRunId === event.detail?.runId) openRunDetail(event.detail.runId, false, true).catch(error => toast(error.message, 'error'));
    if (location.hash === '#runs') loadRuns().catch(() => {});
  });
  window.addEventListener('automation:runs-changed', () => { if (location.hash === '#runs') loadRuns().catch(() => {}); });
  window.addEventListener('hashchange', showPage);
  window.addEventListener('app:navigation-ready', showPage);
  window.AutomationRuns = { open: openRunDetail, reload: loadRuns };
  showPage();
})();
