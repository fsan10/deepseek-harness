/* 报表任务：列表视图（按店铺分组）+ 日历视图（按天看缺口）+ 店铺配置抽屉 + 补跑。 */
(function () {
  const { $, esc, api, toast, can, today, fmt, timeOnly, statusTag, empty } = window.AutomationUI;

  const state = {
    view: 'list', date: today(), month: today().slice(0, 7), dateBasis: 'execution',
    filters: { company: '', platform: '', keyword: '' },
    day: null, calendar: null, reportPage: 1, reportPageSize: 20,
    expanded: new Set(), selection: new Set(), detailDate: today(),
    drawer: null, batchId: null, batchTimer: null, preview: null, request: 0, controller: null,
  };

  const downloadMeta = status => ({
    success: ['ok', '已下载'], no_data: ['ok', '无数据'], failed: ['bad', '失败'],
    missing_file: ['bad', '文件缺失'], missing: ['bad', '未获取'], unverified: ['warn', '待核对'],
    monthly_only: ['warn', '仅月报'], not_ready: ['warn', '待生成'], needs_human: ['warn', '待人工'],
    disabled: ['idle', '已停用'], queued: ['idle', '排队中'], running: ['ok', '执行中'], skipped: ['idle', '已跳过'],
  }[status] || ['idle', status || '—']);

  const uploadMeta = report => {
    const artifact = report.artifact;
    const status = report.upload_status;
    if (status === 'not_required') return ['idle', '无需上传'];
    if (['success', 'duplicate'].includes(status)) return ['ok', `已上传 ${timeOnly(report.artifact?.ingest_finished_at)}`];
    if (['processing', 'uploaded'].includes(status)) return ['warn', '上传中'];
    if (status === 'failed') return ['bad', '上传失败'];
    if (!artifact) return ['idle', '—'];
    return ['warn', '待上传'];
  };

  const mappingClass = shop => shop.mapping_ok ? 'ok' : (shop.mapping_status === 'company_mismatch' ? 'warn' : 'bad');
  const ratioClass = (done, total) => total === 0 ? '' : done === total ? 'ok' : done === 0 ? 'bad' : 'warn';

  function uuid() {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
    const hex = [...bytes].map(byte => byte.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }

  function fillFilters(items) {
    const companies = [...new Set(items.map(item => item.company).filter(Boolean))].sort();
    const platforms = [...new Set(items.map(item => item.platform).filter(Boolean))].sort();
    const keep = (id, values, label, current) => {
      const node = $(id); if (!node) return;
      node.innerHTML = `<option value="">${label}</option>` + values.map(value => `<option value="${esc(value)}">${esc(value)}</option>`).join('');
      node.value = values.includes(current) ? current : '';
      state.filters[id === 'reportCompany' ? 'company' : 'platform'] = node.value;
    };
    keep('reportCompany', companies, '全部公司', state.filters.company);
    keep('reportPlatform', platforms, '全部平台', state.filters.platform);
  }

  function queryString(extra = {}) {
    const params = new URLSearchParams();
    Object.entries({ ...state.filters, date_basis: state.dateBasis, ...extra }).forEach(([key, value]) => { if (value) params.set(key, value); });
    return params.toString();
  }

  function setView(view) {
    state.view = view;
    document.querySelectorAll('[data-report-view]').forEach(node => {
      const active = node.dataset.reportView === view;
      node.classList.toggle('is-active', active);
      node.setAttribute('aria-selected', String(active));
    });
    $('reportListView').hidden = view !== 'list';
    $('reportCalendarView').hidden = view !== 'calendar';
    $('reportDateField').hidden = view !== 'list';
    $('calendarMonthField').hidden = view !== 'calendar';
    state.date = $('reportDate').value || state.date;
    state.month = $('calendarMonth').value || state.month;
    query().catch(error => toast(error.message, 'error'));
  }

  async function load() {
    $('reportDate').value ||= state.date;
    $('calendarMonth').value ||= state.month;
    state.date = $('reportDate').value;
    state.month = $('calendarMonth').value;
    await query();
    if (state.batchId) refreshBatch().catch(() => {});
  }

  async function query() {
    const token = ++state.request;
    state.controller?.abort();
    state.controller = new AbortController();
    const options = { signal: state.controller.signal, cache: 'no-store' };
    $('queryReports').disabled = true;
    const view = $('reportListView').hidden ? $('reportCalendarView') : $('reportListView');
    view.setAttribute('aria-busy', 'true');
    try {
      if (state.view === 'list') {
        const data = await api('/api/automation/report-day?' + queryString({ date: state.date, page: state.reportPage, page_size: state.reportPageSize }), options);
        if (token !== state.request) return;
        fillFilters(data.inventory?.items || []);
        state.day = data;
        renderSummary(data.summary, data.date, data.inventory);
        renderList(data);
      } else {
        const data = await api('/api/automation/report-calendar?' + queryString({ month: state.month, compact: '1' }), options);
        if (token !== state.request) return;
        fillFilters(data.inventory?.items || []);
        state.calendar = data;
        const dates = new Set((data.days || []).map(day => day.date));
        [...state.selection].forEach(date => { if (!dates.has(date)) state.selection.delete(date); });
        renderSummary(monthSummary(data), state.month, data.inventory);
        renderCalendar(data);
      }
    } catch (error) {
      if (token === state.request && error.name !== 'AbortError') throw error;
    } finally {
      if (token === state.request) {
        $('queryReports').disabled = false;
        $('reportListView').removeAttribute('aria-busy');
        $('reportCalendarView').removeAttribute('aria-busy');
      }
    }
  }

  function monthSummary(data) {
    const days = (data.days || []).filter(day => !day.future && day.summary);
    const last = days[days.length - 1]?.summary || {};
    return {
      shops: last.shops || 0, reports: last.reports || 0,
      download_success: days.reduce((sum, day) => sum + (day.summary?.download_success || 0), 0),
      upload_success: days.reduce((sum, day) => sum + (day.summary?.upload_success || 0), 0),
      pending: days.reduce((sum, day) => sum + (day.summary?.pending || 0), 0),
      mapping_issues: last.mapping_issues || 0,
      disabled_shops: last.disabled_shops || 0,
      completion: last.completion || 0, month: true, day_count: days.length,
    };
  }

  function renderSummary(summary = {}, label, inventory = {}) {
    const done = Number(summary.download_success || 0);
    const total = Number(summary.reports || 0);
    const percent = summary.month ? Number(summary.completion || 0) : (total ? Math.round(done / total * 100) : 0);
    const lead = summary.month
      ? `<strong>${esc(label)} · 本月累计</strong><small>${summary.day_count || 0} 个${state.dateBasis === 'execution' ? '执行日' : '业务日'} · 每日目标 ${total} 份</small>`
      : `<strong>${esc(label)} · ${esc(weekday(label))}</strong><small>${summary.shops || 0} 家店铺 · ${total} 份启用报表${inventory?.warning ? ' · 清单为缓存' : ''}</small>`;
    $('reportSummary').innerHTML = `
      <div class="summary-lead">${lead}</div>
      <div class="report-metric ok"><b>${done}</b><span>下载成功</span></div>
      <div class="report-metric ok"><b>${Number(summary.upload_success || 0)}</b><span>上传成功</span></div>
      <div class="report-metric warn"><b>${Number(summary.pending || 0)}</b><span>${summary.month ? '本月缺口' : '待补跑'}</span></div>
      <div class="report-metric bad"><b>${Number(summary.mapping_issues || 0)}</b><span>映射待修复（不阻塞下载）</span></div>
      <div class="report-progress"><span>${summary.month ? '最近一日完成' : '下载完成'} ${percent}%</span><div class="report-progress-bar"><i style="width:${Math.min(100, percent)}%"></i></div></div>`;
  }

  function weekday(value) {
    const date = new Date(value + 'T00:00:00');
    if (Number.isNaN(date.getTime())) return '';
    return '周' + '日一二三四五六'[date.getDay()];
  }

  /* ---------------- 列表视图 ---------------- */
  function pageNumbers(current, total, maxVisible = 5) {
    if (total <= 1) return [1];
    if (total <= maxVisible) return Array.from({ length: total }, (_, index) => index + 1);
    let start = Math.max(1, current - Math.floor(maxVisible / 2));
    let end = start + maxVisible - 1;
    if (end > total) { end = total; start = Math.max(1, end - maxVisible + 1); }
    return Array.from({ length: end - start + 1 }, (_, index) => start + index);
  }

  function renderReportPagination(data) {
    const pages = Number(data.pages || 1);
    const current = Number(data.page || 1);
    $('reportPageInfo').textContent = `第 ${current}/${pages} 页`;
    $('reportPrevPage').disabled = current <= 1;
    $('reportNextPage').disabled = current >= pages;
    $('reportPageNumbers').innerHTML = pageNumbers(current, pages).map(page =>
      `<button class="pagination-page-btn ${page === current ? 'is-active' : ''}" type="button" data-report-page="${page}" aria-label="第 ${page} 页" ${page === current ? 'aria-current="page"' : ''}>${page}</button>`
    ).join('');
  }

  function renderList(data) {
    const shops = data.shops || [];
    state.reportPage = Number(data.page || 1);
    $('reportTableTotal').textContent = `共 ${Number(data.total ?? shops.length)} 家店铺 · ${data.summary?.reports || 0} 份启用报表`;
    renderReportPagination(data);
    $('reportShopRows').innerHTML = shops.length ? shops.map(shopRow).join('') : empty('没有匹配的店铺，请调整筛选条件');
    document.querySelectorAll('[data-shop-toggle]').forEach(button => {
      const key = button.dataset.shopToggle;
      button.setAttribute('aria-expanded', String(state.expanded.has(key)));
      button.closest('.shop-block')?.classList.toggle('is-open', state.expanded.has(key));
      button.closest('.shop-row')?.classList.toggle('is-open', state.expanded.has(key));
    });
    document.querySelectorAll('[data-shop-enable]').forEach(input => {
      input.checked = input.dataset.shopEnable === '1';
      input.disabled = !can('automation.jobs.manage');
    });
  }

  function shopRow(shop) {
    const body = (shop.reports || []).map(report => reportRow(shop, report)).join('');
    const uploads = (shop.reports || []).filter(report => report.enabled && ['success', 'duplicate'].includes(report.upload_status)).length;
    const suffix = shop.duplicate_shop && shop.profile_name.includes(shop.shop)
      ? shop.profile_name.split(shop.shop).pop().replace(/^-/, '') : '';
    const displayName = `${shop.shop || shop.profile_name}${suffix ? ' · ' + suffix : ''}`;
    return `<div class="shop-block ${state.expanded.has(shop.key) ? 'is-open' : ''}" data-shop="${esc(shop.key)}">
      <div class="report-grid shop-row ${state.expanded.has(shop.key) ? 'is-open' : ''}">
        <button class="shop-toggle" type="button" data-shop-toggle="${esc(shop.key)}" aria-expanded="${state.expanded.has(shop.key)}" aria-label="展开报表"><svg><use href="#i-right"/></svg></button>
        <span class="platform-tag">${esc(shortPlatform(shop.platform))}</span>
        <div class="shop-main"><strong title="${esc(shop.profile_name)}">${esc(displayName)}</strong><small>${esc(shop.company || '公司未填写')}</small></div>
        <span class="report-count num">${shop.total} 份</span>
        <span class="report-ratio num ${ratioClass(shop.done, shop.total)}">${shop.done} / ${shop.total}</span>
        <span class="report-ratio num ${ratioClass(uploads, shop.upload_total ?? shop.total)}">${uploads} / ${shop.upload_total ?? shop.total}</span>
        <span class="mapping-tag ${mappingClass(shop)}" title="${esc(shop.mapping_reason || '')}">${esc(shop.mapping_label || '—')}</span>
        <label class="switch center" title="${shop.enabled ? '停用后 Codex 明早不再执行该 Profile' : '启用后纳入目标清单'}"><input type="checkbox" data-shop-enable="${shop.enabled ? '1' : '0'}" data-profile="${esc(shop.profile_name)}" ${shop.enabled ? 'checked' : ''}><span></span></label>
        <button class="link-button" type="button" data-shop-config="${esc(shop.key)}"><svg><use href="#i-sliders"/></svg>配置</button>
      </div>
      <div class="shop-body">${body}</div>
    </div>`;
  }

  function reportRow(shop, report) {
    const [downClass, downText] = downloadMeta(report.status);
    const [upClass, upText] = uploadMeta(report);
    const verified = report.artifact?.coverage_verified ? ['ok', '已核验'] : report.artifact ? ['warn', '期间待核验'] : ['idle', '—'];
    const downloadedAt = report.artifact?.downloaded_at || report.artifact?.created_at;
    const downloadTime = report.status === 'success' && downloadedAt ? ' ' + timeOnly(downloadedAt) : '';
    const period = report.artifact ? ` · 业务期间 ${report.artifact.business_date_start || '待核对'} 至 ${report.artifact.business_date_end || '待核对'}` : '';
    const action = report.run_id
      ? `<button class="link-button" type="button" data-run-detail="${esc(report.run_id)}"><svg><use href="#i-eye"/></svg>详情</button>`
      : (report.enabled ? `<button class="link-button" type="button" data-report-backfill="${esc(shop.key)}|${esc(report.report_type)}"><svg><use href="#i-play"/></svg>补跑</button>` : '');
    return `<div class="report-grid report-row">
      <span></span><span class="report-cell-platform"></span>
      <div class="report-name"><span class="${report.report_enabled ? '' : 'off'}">${esc(report.report_name)}</span><small>${esc(report.report_type)}${report.enabled ? '' : ' · 已停用'}</small></div>
      <span class="report-count num"></span>
      <span class="num"><span class="tag ${downClass}" title="${esc((report.artifact?.file_name || '') + period)}">${esc(downText + downloadTime)}</span></span>
      <span class="num"><span class="tag ${upClass}">${esc(upText)}</span></span>
      <span><span class="mapping-tag ${verified[0]}">${esc(verified[1])}</span></span>
      <span class="center">${report.report_enabled ? '' : '<span class="muted">停用</span>'}</span>
      <span class="center">${action}</span>
    </div>`;
  }

  function shortPlatform(value) {
    const map = { 抖音: '抖音', 京东: '京东', 拼多多: '拼多多', 快手: '快手', 小红书: '小红书', 天猫: '天猫' };
    return map[value] || value || '—';
  }

  function toggleShop(key) {
    if (state.expanded.has(key)) state.expanded.delete(key); else state.expanded.add(key);
    const block = document.querySelector(`[data-shop="${CSS.escape(key)}"]`);
    if (!block) return;
    const open = state.expanded.has(key);
    block.classList.toggle('is-open', open);
    block.querySelector('.shop-row')?.classList.toggle('is-open', open);
    const button = block.querySelector('[data-shop-toggle]');
    if (button) button.setAttribute('aria-expanded', String(open));
  }

  async function toggleShopEnabled(profile, enabled, input) {
    input.disabled = true;
    try {
      await api('/api/automation/report-settings', { method: 'PUT', body: JSON.stringify({ profile_name: profile, enabled }) });
      toast(enabled ? '已启用：Codex 明早会执行该 Profile' : '已停用：Codex 明早会跳过该 Profile');
      await query();
    } catch (error) {
      input.checked = !enabled;
      toast(error.message, 'error');
    } finally {
      input.disabled = false;
    }
  }

  /* ---------------- 日历视图 ---------------- */
  function renderCalendar(data) {
    const [year, month] = data.month.split('-').map(Number);
    const first = new Date(year, month - 1, 1);
    const offset = (first.getDay() + 6) % 7;
    const daysInMonth = new Date(year, month, 0).getDate();
    const map = new Map((data.days || []).map(day => [day.date, day]));
    const cells = [];
    for (let index = 0; index < offset; index += 1) {
      const dayNumber = new Date(year, month - 1, index - offset + 1).getDate();
      cells.push(`<div class="rc-day is-outside"><span class="rc-day-number">${dayNumber}</span><span class="rc-day-state">上月</span></div>`);
    }
    for (let day = 1; day <= daysInMonth; day += 1) {
      const iso = `${data.month}-${String(day).padStart(2, '0')}`;
      cells.push(calendarCell(iso, day, map.get(iso)));
    }
    const tail = (7 - (cells.length % 7)) % 7;
    for (let index = 1; index <= tail; index += 1) {
      cells.push(`<div class="rc-day is-outside"><span class="rc-day-number">${index}</span><span class="rc-day-state">下月</span></div>`);
    }
    $('calendarGrid').innerHTML = cells.join('');
    updateSelection();
    const detail = map.get(state.detailDate) || map.get(today());
    if (detail) renderDayDetail(detail);
  }

  function calendarCell(iso, day, data) {
    if (!data) return `<div class="rc-day is-future"><span class="rc-day-number">${day}</span><span class="rc-day-state">尚未到期</span></div>`;
    const shops = (data.shops || []).filter(shop => shop.enabled);
    const done = shops.filter(shop => shop.state === 'success').length;
    const problems = [];
    shops.forEach(shop => (shop.reports || []).forEach(report => {
      if (!report.enabled || ['success', 'no_data'].includes(report.status)) return;
      problems.push({ shop, report });
    }));
    const chips = problems.slice(0, 2).map(item => {
      const [kind] = downloadMeta(item.report.status);
      return `<span class="rc-chip ${kind === 'bad' ? 'bad' : 'warn'}" title="${esc(item.shop.shop)} · ${esc(item.report.report_name)} ${esc(item.report.status)}">${esc(item.shop.shop)} · ${esc(item.report.report_name)}</span>`;
    }).join('');
    const more = problems.length > 2 ? `<span class="rc-chip more">+${problems.length - 2} 项</span>` : '';
    const selected = state.selection.has(iso);
    const isToday = iso === today();
    const classes = ['rc-day', selected ? 'is-selected' : '', isToday ? 'is-today' : '', data.future ? 'is-future' : ''].filter(Boolean).join(' ');
    const stateClass = data.future ? '' : done === shops.length && shops.length ? 'ok' : done ? 'warn' : 'bad';
    return `<button class="${classes}" type="button" data-calendar-date="${iso}" ${data.future ? 'disabled' : ''} aria-pressed="${selected}">
      <span class="rc-day-number">${day}${isToday ? ' · 今天' : ''}</span>
      <span class="rc-day-state ${data.future ? '' : stateClass}">${data.future ? '尚未到期' : `已齐 ${done}/${shops.length} 家`}</span>
      ${data.future ? '' : `<span class="muted">下载 ${data.summary?.download_success || 0}/${data.summary?.reports || 0} · 上传 ${data.summary?.upload_success || 0}/${data.summary?.upload_total ?? data.summary?.reports ?? 0}</span>`}
      <span class="rc-day-chips">${data.future ? '' : chips + more}</span>
    </button>`;
  }

  function toggleDate(iso) {
    if (state.selection.has(iso)) state.selection.delete(iso); else state.selection.add(iso);
    state.detailDate = iso;
    renderCalendar(state.calendar);
  }

  function updateSelection() {
    const dates = [...state.selection].sort();
    $('calendarSelectionCount').textContent = dates.length ? `已选 ${dates.length} 天` : '未选择';
    $('calendarSelectionText').textContent = dates.length
      ? `${dates[0]} ~ ${dates[dates.length - 1]} · 只补所选日期中仍未成功的报表`
      : '点击日期选择补跑范围';
    $('calendarBackfill').disabled = !dates.length || !can('automation.runs.execute');
  }

  function renderDayDetail(day) {
    state.detailDate = day.date;
    $('calendarDetailTitle').textContent = `${day.date} 缺口明细`;
    const shops = (day.shops || []).filter(shop => shop.enabled);
    const problems = [];
    shops.forEach(shop => (shop.reports || []).forEach(report => {
      if (!report.enabled || ['success', 'no_data'].includes(report.status)) return;
      problems.push({ shop, report });
    }));
    $('calendarDetailMeta').textContent = problems.length
      ? `${problems.length} 项未完成 · 覆盖 ${new Set(problems.map(item => item.shop.key)).size} 家店铺`
      : '该日期没有缺口；可切换其他日期或直接查看列表视图';
    $('calendarDayDetail').innerHTML = problems.length ? `<table class="data-table"><thead><tr><th>店铺</th><th>报表</th><th>下载</th><th>上传</th><th>操作</th></tr></thead><tbody>${problems.map(({ shop, report }) => {
      const [downClass, downText] = downloadMeta(report.status);
      const [upClass, upText] = uploadMeta(report);
      return `<tr><td><strong>${esc(shop.shop)}</strong><br><small class="muted">${esc(shop.platform)} · ${esc(shop.profile_name)}</small></td><td>${esc(report.report_name)}</td><td><span class="tag ${downClass}">${esc(downText)}</span></td><td><span class="tag ${upClass}">${esc(upText)}</span></td><td><button class="link-button" type="button" data-report-backfill="${esc(shop.key)}|${esc(report.report_type)}|${esc(day.date)}">补跑</button> <button class="link-button" type="button" data-locate-shop="${esc(shop.key)}|${esc(day.date)}">定位</button></td></tr>`;
    }).join('')}</tbody></table>` : empty('该日期没有缺口');
  }

  /* ---------------- 补跑 ---------------- */
  function gapPayload(dates) {
    const dayMap = new Map((state.calendar?.days || []).map(day => [day.date, day]));
    const profiles = new Set();
    const types = new Set();
    const wanted = dates.filter(date => dayMap.has(date));
    wanted.forEach(date => {
      const day = dayMap.get(date);
      (day.shops || []).forEach(shop => {
        if (!shop.enabled) return;
        (shop.reports || []).forEach(report => {
          if (!report.enabled || ['success', 'no_data'].includes(report.status)) return;
          profiles.add(shop.profile_name);
          types.add(report.report_type);
        });
      });
    });
    if (!profiles.size) throw new Error('所选日期没有需要补跑的报表');
    return { dates: wanted.sort(), profiles: [...profiles].sort(), report_types: [...types].sort(), date_basis: state.dateBasis, force: $('reportForce').checked };
  }

  async function previewReport(payload) {
    const result = await api('/api/automation/report-batches/preview', { method: 'POST', body: JSON.stringify(payload) });
    state.preview = { payload, result };
    const steps = (result.plans || []).map(plan => `<details open><summary>${esc(plan.profile_name)} · ${plan.steps.length} 个步骤</summary>${plan.steps.map(step => `<p>${esc(step.name)}</p>`).join('')}</details>`).join('');
    $('reportPreviewContent').innerHTML = `<p>${payload.dates[0]} 至 ${payload.dates[payload.dates.length - 1]}，共 ${payload.dates.length} 天（${payload.date_basis === 'execution' ? '执行日期；实际业务期间见下方计划' : '业务日期'}）。计划 ${result.plans.length} 个 Profile、${result.step_count} 个下载步骤，预计 ${result.estimated_files} 份文件；跳过已完成 ${result.skipped} 项。</p><div class="batch-preview-plan">${steps || '<p>所选报表已全部补齐。</p>'}</div>`;
    $('reportSubmit').disabled = !result.step_count;
    if (!$('reportPreviewDialog').open) $('reportPreviewDialog').showModal();
  }

  async function previewSelection() {
    if (!state.selection.size) return toast('请先选择业务日期', 'error');
    await previewReport(gapPayload([...state.selection]));
  }

  async function previewSingle(shopKey, reportType, date) {
    const targetDate = date || state.date;
    const sources = [];
    if (state.day && state.day.date === targetDate) sources.push(state.day.shops || []);
    const calendarDay = (state.calendar?.days || []).find(item => item.date === targetDate);
    if (calendarDay) sources.push(calendarDay.shops || []);
    const shop = sources.flat().find(item => item.key === shopKey);
    if (!shop) return toast('未找到该店铺，请刷新后重试', 'error');
    await previewReport({ dates: [targetDate], profiles: [shop.profile_name], report_types: [reportType], date_basis: state.dateBasis, force: $('reportForce').checked });
  }

  async function submitBatch() {
    $('reportSubmit').disabled = true;
    const payload = { ...state.preview.payload };
    payload.force = $('reportForce').checked;
    payload.request_key ||= uuid();
    try {
      const batch = await api('/api/automation/report-batches', { method: 'POST', body: JSON.stringify(payload) });
      state.batchId = batch.batch_id;
      localStorage.setItem('automation:last-report-batch', state.batchId);
      $('reportPreviewDialog').close();
      state.selection.clear();
      if (state.view === 'calendar' && state.calendar) renderCalendar(state.calendar);
      toast('补跑任务已入队，关闭页面后继续执行');
      renderBatch(batch);
      startBatchPolling();
    } finally {
      $('reportSubmit').disabled = false;
    }
  }

  function renderBatch(batch) {
    $('reportBatchPanel').hidden = false;
    $('reportBatchProgress').textContent = `已完成 ${batch.completed} / ${batch.total} 个 Profile`;
    const rows = (batch.runs || []).map(run => `<tr><td>${esc(run.profile_name)}</td><td>${statusTag(run.status)}</td><td>${esc(run.error_message || run.warning_message || '—')}</td><td>${run.automation_run_id ? `<button class="link-button" type="button" data-run-detail="${esc(run.automation_run_id)}">执行详情</button>` : '—'} ${can('automation.runs.retry') && ['failed', 'needs_human'].includes(run.status) ? `<button class="link-button" type="button" data-batch-resume="${esc(run.automation_run_id)}">修复后继续</button>` : ''}</td></tr>`).join('');
    $('reportBatchRuns').innerHTML = rows ? `<table class="data-table"><thead><tr><th>Profile</th><th>状态</th><th>说明</th><th>操作</th></tr></thead><tbody>${rows}</tbody></table>` : empty('批次还没有运行记录');
    const active = (batch.runs || []).some(run => ['queued', 'running', 'needs_human', 'failed'].includes(run.status));
    if (!active) stopBatchPolling();
  }

  async function refreshBatch() {
    if (!state.batchId) return;
    renderBatch(await api('/api/automation/report-batches/' + state.batchId));
  }

  function startBatchPolling() {
    stopBatchPolling();
    state.batchTimer = setInterval(() => { if (location.hash === '#reports' && !document.hidden) refreshBatch().catch(() => stopBatchPolling()); }, 5000);
  }

  function stopBatchPolling() { if (state.batchTimer) { clearInterval(state.batchTimer); state.batchTimer = null; } }

  /* ---------------- 店铺配置抽屉 ---------------- */
  function openDrawer(key) {
    const shop = (state.day?.shops || []).find(item => item.key === key);
    if (!shop) return toast('店铺数据已刷新，请重试', 'error');
    state.drawer = { shop, enabled: shop.enabled, reports: {} };
    $('reportDrawerPlatform').textContent = shortPlatform(shop.platform);
    $('reportDrawerTitle').textContent = shop.shop;
    $('reportDrawerSubtitle').textContent = `${shop.company || '公司未填写'} · ${shop.profile_name}`;
    $('reportDrawerBody').innerHTML = drawerHtml(shop);
    $('reportDrawer').hidden = false;
    $('reportDrawerBackdrop').hidden = false;
    $('reportDrawerHint').textContent = can('automation.jobs.manage') ? '保存后 Codex 明早读取同一份配置' : '当前账号只读，无法修改';
    $('reportDrawerSave').disabled = !can('automation.jobs.manage');
    bindDrawer(shop);
  }

  function drawerHtml(shop) {
    const card = shop.mapping_ok
      ? `<div class="mapping-card ok"><header><span class="mapping-tag ok">${esc(shop.mapping_label)}</span><span>${esc(shop.mapping_reason || 'DIM 已唯一匹配，可正常上传')}</span></header></div>`
      : `<div class="mapping-card"><header><span class="mapping-tag ${mappingClass(shop)}">${esc(shop.mapping_label || '映射待修复')}</span><span>${esc(shop.mapping_reason || '不影响下载，只影响上传核验')}</span></header>
          <div class="mapping-diff">${shop.mapping_candidates?.length ? shop.mapping_candidates.map(item => `<span>DIM：${esc(item.shop_name)} · ${esc(item.company_name)}（${esc(item.shop_code)}）</span>`).join('') : `<span>Profile：${esc(shop.platform)} · ${esc(shop.shop)} · ${esc(shop.company || '公司未填写')}</span>`}</div>
          <div class="mapping-actions"><button class="link-button" type="button" data-mapping-open="system">去维护 DIM 映射</button></div></div>`;
    const rows = (shop.reports || []).map(report => `
      <div class="report-config-row">
        <div><strong>${esc(report.report_name)}</strong><small>${esc(report.report_type)} · 近 ${report.recent_days || 7} 日 ${report.recent_done ?? '—'}/${report.recent_days || 7} 天</small></div>
        <label class="switch"><input type="checkbox" data-drawer-report="${esc(report.report_type)}" ${report.report_enabled ? 'checked' : ''} ${shop.enabled ? '' : 'disabled'}><span></span></label>
      </div>`).join('');
    return `${card}
      <div class="drawer-section-head"><h3>整店自动下载</h3><label class="switch"><input type="checkbox" id="drawerShopEnabled" ${shop.enabled ? 'checked' : ''}><span></span></label></div>
      <p class="drawer-note">停用后该 Profile 不再进入今日目标，Codex 明早读取 profile_status 后直接跳过；历史文件与手动补跑不受影响。</p>
      <div class="drawer-section-head"><h3>报表清单（${(shop.reports || []).length}）</h3><span class="muted">逐报表启停</span></div>
      <div class="report-config-list">${rows}</div>
      <p class="drawer-note">报表级停用只调整目标口径与后台补跑，不改变 Codex 总控的执行清单。</p>`;
  }

  function bindDrawer(shop) {
    $('drawerShopEnabled').onchange = event => {
      state.drawer.enabled = event.target.checked;
      document.querySelectorAll('[data-drawer-report]').forEach(input => { input.disabled = !state.drawer.enabled; });
    };
    document.querySelectorAll('[data-drawer-report]').forEach(input => {
      input.onchange = () => { state.drawer.reports[input.dataset.drawerReport] = input.checked; };
    });
    $('reportDrawerBody').querySelectorAll('[data-mapping-open]').forEach(button => {
      button.onclick = () => toast('请在「系统管理 → 平台店铺公司映射」中维护该店铺');
    });
  }

  async function saveDrawer() {
    const drawer = state.drawer; if (!drawer) return;
    const payload = { profile_name: drawer.shop.profile_name };
    if (drawer.enabled !== drawer.shop.enabled) payload.enabled = drawer.enabled;
    const changed = {};
    Object.entries(drawer.reports).forEach(([key, value]) => {
      const report = (drawer.shop.reports || []).find(item => item.report_type === key);
      if (report && report.report_enabled !== value) changed[key] = value;
    });
    if (Object.keys(changed).length) payload.reports = changed;
    if (payload.enabled === undefined && !payload.reports) return closeDrawer();
    $('reportDrawerSave').disabled = true;
    try {
      await api('/api/automation/report-settings', { method: 'PUT', body: JSON.stringify(payload) });
      toast('配置已保存，Codex 明早按此执行');
      closeDrawer();
      await query();
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      $('reportDrawerSave').disabled = false;
    }
  }

  function closeDrawer() {
    $('reportDrawer').hidden = true;
    $('reportDrawerBackdrop').hidden = true;
    state.drawer = null;
  }

  /* ---------------- 事件 ---------------- */
  document.addEventListener('click', event => {
    const target = event.target.closest('main button, main [data-shop-enable], .drawer button');
    if (!target) return;
    (async () => {
      try {
        if (target.dataset.reportView) setView(target.dataset.reportView);
        if (target.dataset.shopToggle) toggleShop(target.dataset.shopToggle);
        if (target.dataset.shopConfig) openDrawer(target.dataset.shopConfig);
        if (target.dataset.calendarDate) toggleDate(target.dataset.calendarDate);
        if (target.dataset.runDetail) await window.AutomationRuns?.open(target.dataset.runDetail);
        if (target.dataset.reportBackfill) {
          const [shopKey, reportType, date] = target.dataset.reportBackfill.split('|');
          await previewSingle(shopKey, reportType, date);
        }
        if (target.dataset.locateShop) {
          const [shopKey, date] = target.dataset.locateShop.split('|');
          state.date = date; $('reportDate').value = date; state.expanded.add(shopKey);
          setView('list');
          document.querySelector(`[data-shop="${CSS.escape(shopKey)}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' });
        }
        if (target.dataset.batchResume) {
          await api('/api/automation/runs/' + target.dataset.batchResume + '/resume', { method: 'POST', body: JSON.stringify({ reason: 'calendar' }) });
          toast('任务已恢复到队列');
          await refreshBatch();
          startBatchPolling();
        }
      } catch (error) { toast(error.message, 'error'); }
    })();
  });

  // 行内任意非功能区域展开/折叠该店铺的报表；配置抽屉只由“配置”按钮打开。
  document.addEventListener('click', event => {
    const row = event.target.closest('.shop-row');
    if (!row || event.target.closest('button, input, label, a')) return;
    const block = row.closest('.shop-block');
    if (block?.dataset.shop) toggleShop(block.dataset.shop);
  });

  document.addEventListener('change', event => {
    const input = event.target.closest('[data-shop-enable]');
    if (input) toggleShopEnabled(input.dataset.profile, input.checked, input);
  });

  function bind() {
    $('queryReports').onclick = () => {
      state.filters = { company: $('reportCompany').value, platform: $('reportPlatform').value, keyword: $('reportKeyword').value.trim() };
      state.date = $('reportDate').value || today();
      state.month = $('calendarMonth').value || today().slice(0, 7);
      state.reportPage = 1;
      query().catch(error => toast(error.message, 'error'));
    };
    $('resetReports').onclick = () => {
      $('reportCompany').value = ''; $('reportPlatform').value = ''; $('reportKeyword').value = '';
      $('reportDate').value = today(); $('calendarMonth').value = today().slice(0, 7);
      state.filters = { company: '', platform: '', keyword: '' };
      state.date = today(); state.month = today().slice(0, 7); state.selection.clear();
      state.dateBasis = 'execution'; $('reportDateBasis').value = 'execution'; updateDateLabels();
      state.reportPage = 1;
      query().catch(error => toast(error.message, 'error'));
    };
    $('reportPageSize').onchange = () => {
      state.reportPageSize = Number($('reportPageSize').value) || 20;
      state.reportPage = 1;
      query().catch(error => toast(error.message, 'error'));
    };
    $('reportPrevPage').onclick = () => { if (state.reportPage > 1) { state.reportPage -= 1; query().catch(error => toast(error.message, 'error')); } };
    $('reportNextPage').onclick = () => { state.reportPage += 1; query().catch(error => toast(error.message, 'error')); };
    $('reportPageNumbers').onclick = event => {
      const button = event.target.closest('[data-report-page]');
      if (!button) return;
      state.reportPage = Number(button.dataset.reportPage);
      query().catch(error => toast(error.message, 'error'));
    };
    $('reportToolbar').addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); $('queryReports').click(); } });
    $('calendarSelectMissing').onclick = () => {
      const days = (state.calendar?.days || []).filter(day => !day.future && (day.summary?.pending || 0) > 0);
      state.selection = new Set(days.map(day => day.date));
      updateSelection();
      if (state.calendar) renderCalendar(state.calendar);
      if (!state.selection.size) toast('本月没有缺口日期');
    };
    $('calendarClearSelection').onclick = () => { state.selection.clear(); if (state.calendar) renderCalendar(state.calendar); };
    $('calendarBackfill').onclick = () => previewSelection().catch(error => toast(error.message, 'error'));
    $('calendarOpenShop').hidden = true;
    $('reportPreviewClose').onclick = () => $('reportPreviewDialog').close();
    $('reportPreviewRefresh').onclick = () => {
      if (!state.preview) return;
      const payload = { ...state.preview.payload, force: $('reportForce').checked };
      previewReport(payload).catch(error => toast(error.message, 'error'));
    };
    $('reportForce').onchange = () => { $('reportSubmit').disabled = true; $('reportPreviewContent').insertAdjacentHTML('afterbegin', '<p class="muted">获取策略已改变，请点击“更新预览”后提交。</p>'); };
    $('reportSubmit').onclick = () => submitBatch().catch(error => toast(error.message, 'error'));
    $('reportBatchRefresh').onclick = () => refreshBatch().catch(error => toast(error.message, 'error'));
    $('reportDrawerClose').onclick = closeDrawer;
    $('reportDrawerCancel').onclick = closeDrawer;
    $('reportDrawerBackdrop').onclick = closeDrawer;
    $('reportDrawerSave').onclick = () => saveDrawer().catch(error => toast(error.message, 'error'));
    document.addEventListener('keydown', event => { if (event.key === 'Escape' && !$('reportDrawer').hidden) closeDrawer(); });
    state.batchId = localStorage.getItem('automation:last-report-batch');
    if (state.batchId) refreshBatch().then(startBatchPolling).catch(() => { state.batchId = null; localStorage.removeItem('automation:last-report-batch'); });
  }

  function updateDateLabels() {
    $('reportDateLabel').textContent = state.dateBasis === 'execution' ? '执行日期' : '业务日期';
    $('reportDateHint').textContent = state.dateBasis === 'execution'
      ? '按执行日期统计任务结果；业务日期查看报表覆盖范围'
      : '按报表业务期间统计覆盖范围，月汇总不等同于逐日报表';
  }

  $('reportDateBasis').onchange = () => {
    state.dateBasis = $('reportDateBasis').value;
    state.selection.clear(); state.reportPage = 1; updateDateLabels();
    query().catch(error => toast(error.message, 'error'));
  };
  window.AutomationReports = { load, setView, query };
  bind();
})();
