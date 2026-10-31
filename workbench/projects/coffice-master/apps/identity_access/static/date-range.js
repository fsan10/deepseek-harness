/* 共享日期范围组件：直接复用银行资金主编辑表的日期选择框（DOM、基础层样式、交互一致）。
   页面用法（占位 span 与两个 hidden input 的 id 由 data-date-range 指定）：
     <label class="inline-field"><span>操作时间</span>
       <div class="date-range" data-date-range="fromId,toId">
         <button type="button" class="date-range-trigger">
           <svg><use href="#i-calendar"></use></svg>
           <span class="date-start date-placeholder">开始日期</span><b>→</b>
           <span class="date-end date-placeholder">结束日期</span>
           <svg class="date-chevron"><use href="#i-down"></use></svg>
         </button>
         <input type="hidden" id="fromId"><input type="hidden" id="toId">
       </div>
     </label>
   脚本自初始化全部 [data-date-range]，弹层复用或创建 #dateRangeDropdown，样式全部来自 /styles.css。
   外部点击用 mousedown 判定：首次点选日期会重渲染弹层内容，被点的按钮随即脱离 DOM，
   若用 click 判定就会被误判为外部点击而关闭弹层，导致同一弹层里无法连续选起止两天。 */
(function () {
  const DROPDOWN_ID = 'dateRangeDropdown';
  const PLACEHOLDER_CLASS = 'date-placeholder';
  const PREFERRED_WIDTH = 640;
  const WEEK_LABELS = ['日', '一', '二', '三', '四', '五', '六'];
  let context = null;

  const pad2 = value => String(value).padStart(2, '0');
  const dateKey = date => `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
  const localDate = value => {
    if (!value) return null;
    const [year, month, day] = value.split('-').map(Number);
    return new Date(year, month - 1, day);
  };
  const monthShift = (date, offset) => new Date(date.getFullYear(), date.getMonth() + offset, 1);

  function dropdown() {
    let drop = document.getElementById(DROPDOWN_ID);
    if (!drop) {
      drop = document.createElement('div');
      drop.id = DROPDOWN_ID;
      drop.className = 'date-range-dropdown';
      drop.setAttribute('role', 'dialog');
      drop.setAttribute('aria-label', '选择日期范围');
      drop.hidden = true;
      document.body.append(drop);
    }
    return drop;
  }

  function parts(control) {
    const [startId, endId] = String(control?.dataset?.dateRange || '').split(',');
    return { startId, endId, startInput: document.getElementById(startId), endInput: document.getElementById(endId) };
  }

  function sync(control) {
    const { startInput, endInput } = parts(control);
    const startText = control?.querySelector('.date-start');
    const endText = control?.querySelector('.date-end');
    if (!startInput || !endInput || !startText || !endText) return;
    startText.textContent = startInput.value || '开始日期';
    endText.textContent = endInput.value || '结束日期';
    startText.classList.toggle(PLACEHOLDER_CLASS, !startInput.value);
    endText.classList.toggle(PLACEHOLDER_CLASS, !endInput.value);
  }

  function refresh(target, endId) {
    if (typeof target === 'string') {
      const control = document.querySelector(`[data-date-range="${target},${endId}"]`);
      if (control) sync(control);
      return;
    }
    if (target?.dataset?.dateRange) sync(target);
    else document.querySelectorAll('[data-date-range]').forEach(sync);
  }

  function clear(startId, endId) {
    const startInput = document.getElementById(startId);
    const endInput = document.getElementById(endId);
    if (startInput) startInput.value = '';
    if (endInput) endInput.value = '';
    refresh(startId, endId);
  }

  function calendarPanel(month, index) {
    const year = month.getFullYear();
    const monthIndex = month.getMonth();
    const first = new Date(year, monthIndex, 1);
    const gridStart = new Date(year, monthIndex, 1 - first.getDay());
    const start = context.startInput.value;
    const end = context.endInput.value;
    const days = [];
    for (let offset = 0; offset < 42; offset += 1) {
      const date = new Date(gridStart);
      date.setDate(gridStart.getDate() + offset);
      const key = dateKey(date);
      const classes = ['calendar-day'];
      if (date.getMonth() !== monthIndex) classes.push('outside');
      if (start && end && key > start && key < end) classes.push('in-range');
      if (key === start) classes.push('range-start');
      if (key === end) classes.push('range-end');
      days.push(`<button type="button" class="${classes.join(' ')}" data-calendar-date="${key}"><span>${date.getDate()}</span></button>`);
    }
    return `<section class="calendar-panel"><div class="calendar-head"><button type="button" class="calendar-nav" data-month-step="-1" ${index ? 'style="visibility:hidden"' : ''}>‹</button><strong>${year}年 ${monthIndex + 1}月</strong><button type="button" class="calendar-nav next" data-month-step="1" ${!index ? 'style="visibility:hidden"' : ''}>›</button></div><div class="calendar-week">${WEEK_LABELS.map(label => `<span>${label}</span>`).join('')}</div><div class="calendar-days">${days.join('')}</div></section>`;
  }

  function render() {
    if (!context) return;
    const drop = dropdown();
    const right = monthShift(context.viewMonth, 1);
    drop.innerHTML = `<div class="date-picker-shortcuts"><button type="button" class="date-shortcut" data-date-days="7">近7天</button><button type="button" class="date-shortcut" data-date-days="30">近30天</button><button type="button" class="date-shortcut" data-date-days="90">近90天</button></div><div class="date-picker-main">${calendarPanel(context.viewMonth, 0)}${calendarPanel(right, 1)}</div><div class="date-picker-tip">${context.pickingEnd ? '请选择结束日期' : '请选择开始日期'}</div>`;
    drop.querySelectorAll('[data-month-step]').forEach(button => {
      button.onclick = () => {
        context.viewMonth = monthShift(context.viewMonth, Number(button.dataset.monthStep));
        render();
        place();
      };
    });
    drop.querySelectorAll('[data-calendar-date]').forEach(button => { button.onclick = () => select(button.dataset.calendarDate); });
    drop.querySelectorAll('[data-date-days]').forEach(button => { button.onclick = () => shortcut(Number(button.dataset.dateDays)); });
  }

  function place() {
    if (!context) return;
    const drop = dropdown();
    const rect = context.trigger.getBoundingClientRect();
    const width = Math.min(PREFERRED_WIDTH, window.innerWidth - 16);
    drop.style.width = `${width}px`;
    const height = drop.offsetHeight || 360;
    drop.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - width - 8))}px`;
    drop.style.top = `${rect.bottom + 6 + height <= window.innerHeight - 8 ? rect.bottom + 6 : Math.max(8, rect.top - height - 6)}px`;
  }

  function select(value) {
    if (!context) return;
    if (!context.pickingEnd) {
      context.startInput.value = value;
      context.endInput.value = '';
      context.pickingEnd = true;
      sync(context.control);
      render();
      place();
      return;
    }
    if (value < context.startInput.value) {
      context.endInput.value = context.startInput.value;
      context.startInput.value = value;
    } else {
      context.endInput.value = value;
    }
    sync(context.control);
    close();
  }

  function shortcut(days) {
    if (!context) return;
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - days);
    context.startInput.value = dateKey(start);
    context.endInput.value = dateKey(end);
    sync(context.control);
    close();
  }

  function close() {
    if (!context) return;
    context.control.classList.remove('open');
    context.trigger.setAttribute('aria-expanded', 'false');
    dropdown().hidden = true;
    context = null;
  }

  function open(control) {
    if (!control) return;
    if (context?.control === control) { close(); return; }
    if (typeof window.DateRangeHooks?.beforeOpen === 'function') window.DateRangeHooks.beforeOpen();
    close();
    const { startInput, endInput } = parts(control);
    const trigger = control.querySelector('.date-range-trigger');
    if (!startInput || !endInput || !trigger) return;
    const base = localDate(startInput.value) || new Date();
    context = { control, trigger, startInput, endInput, viewMonth: new Date(base.getFullYear(), base.getMonth(), 1), pickingEnd: false };
    trigger.setAttribute('aria-expanded', 'true');
    control.classList.add('open');
    const drop = dropdown();
    drop.hidden = false;
    render();
    place();
  }

  document.querySelectorAll('[data-date-range]').forEach(control => {
    refresh(control);
    const trigger = control.querySelector('.date-range-trigger');
    if (!trigger) return;
    trigger.onmousedown = event => event.stopPropagation();
    trigger.onclick = event => { event.stopPropagation(); open(control); };
  });
  document.addEventListener('mousedown', event => {
    if (!context) return;
    if (dropdown().contains(event.target) || context.trigger.contains(event.target)) return;
    close();
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') close(); });
  window.addEventListener('resize', () => { if (context) place(); });

  window.DateRange = { refresh, clear, close, open, isOpen: () => Boolean(context), dropdownId: DROPDOWN_ID };
})();
