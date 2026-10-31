/* 自动化工作台公共工具：三个页面脚本共用同一套请求/状态标签口径。 */
(function () {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const permissions = () => window.currentPermissions || new Set();
  const can = code => permissions().has(code);
  const today = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Shanghai' });
  const fmt = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—';
  const timeOnly = value => value ? new Date(value).toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit' }) : '';
  const labels = {
    queued: '排队中', running: '执行中', success: '成功', success_with_warnings: '成功（有提醒）', no_data: '无数据',
    needs_human: '等待人工', failed: '失败', cancelled: '已取消', skipped: '已跳过', draft: '待提交', ready: '待处理',
    processing: '处理中', no_change: '无变化', partial_failed: '部分失败', deferred: '待数据就绪', uploaded: '已上传',
    duplicate: '重复', unverified: '待核对', missing: '未获取', missing_file: '文件缺失', monthly_only: '仅月报',
    disabled: '已停用', not_ready: '待账单生成', paused: '保留现场', busy: '执行中', offline: '离线', stalled: '长时间运行',
  };
  const statusTag = value => `<span class="status-tag ${esc(value)}">${esc(labels[value] || value || '—')}</span>`;
  const toast = (message, type = 'success') => window.showAppToast ? window.showAppToast(message, type) : (type === 'error' ? console.error(message) : console.log(message));
  async function api(path, options = {}) {
    const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } });
    const payload = await response.json().catch(error => { if (error.name === 'AbortError') throw error; return {}; });
    if (!response.ok) throw new Error(payload.message || `请求失败（${response.status}）`);
    return payload.data;
  }
  const empty = text => `<div class="empty-state">${esc(text)}</div>`;
  const debounce = (fn, wait = 250) => { let timer; return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), wait); }; };
  window.AutomationUI = { $, esc, api, toast, can, today, fmt, timeOnly, labels, statusTag, empty, debounce };
})();
