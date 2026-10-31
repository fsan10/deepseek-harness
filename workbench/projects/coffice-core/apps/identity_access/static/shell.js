(function () {
  const csrf = () => decodeURIComponent((document.cookie.match(/(?:^|; )mocc_csrf=([^;]*)/) || [])[1] || '');
  const nativeFetch = window.fetch.bind(window);
  window.appCsrfToken = csrf;
  window.fetch = async (input, options = {}) => {
    const url = typeof input === 'string' ? input : input.url;
    const method = String(options.method || (typeof input !== 'string' && input.method) || 'GET').toUpperCase();
    const sameOrigin = new URL(url, location.href).origin === location.origin;
    const headers = new Headers(options.headers || (typeof input !== 'string' ? input.headers : undefined));
    if (sameOrigin && !['GET', 'HEAD', 'OPTIONS'].includes(method)) headers.set('X-CSRF-Token', csrf());
    const response = await nativeFetch(input, {...options, headers, credentials: 'same-origin'});
    if (response.status === 401 && !location.pathname.startsWith('/login')) {
      location.assign(`/login/?next=${encodeURIComponent(location.pathname + location.search + location.hash)}`);
    }
    return response;
  };

  let appToastTimer = null;
  window.hasOpenEditor = () => Boolean(document.querySelector('dialog[open], .modal.open, .modal.show, .modal-overlay:not([hidden]), .dialog-overlay:not([hidden])'));
  window.showAppToast = (message, type = 'success', duration = 3200) => {
    let node = document.getElementById('appGlobalToast');
    if (!node) {
      node = document.createElement('div');
      node.id = 'appGlobalToast';
      node.className = 'app-global-toast';
      node.setAttribute('role', 'status');
      node.setAttribute('aria-live', 'polite');
      if ('showPopover' in HTMLElement.prototype) node.setAttribute('popover', 'manual');
      document.body.appendChild(node);
    }
    const normalizedType = type === true ? 'error' : type;
    node.textContent = String(message || '操作失败');
    node.className = `app-global-toast ${normalizedType === 'error' ? 'error' : 'success'}`;
    node.hidden = false;
    const editor = document.querySelector('dialog[open]');
    const host = editor || document.body;
    if (node.hasAttribute('popover')) {
      try { if (node.matches(':popover-open')) node.hidePopover(); } catch (error) {}
    }
    if (node.parentElement !== host) host.appendChild(node);
    if (node.hasAttribute('popover')) {
      try { node.showPopover(); } catch (error) {}
    }
    clearTimeout(appToastTimer);
    appToastTimer = setTimeout(() => {
      if (node.hasAttribute('popover')) { try { node.hidePopover(); } catch (error) {} }
      node.hidden = true;
    }, duration);
  };
  let invalidToastPending = false;
  document.addEventListener('invalid', event => {
    if (!event.target.closest?.('dialog[open], .modal.open, .modal.show, .modal-overlay:not([hidden]), .dialog-overlay:not([hidden])')) return;
    event.preventDefault();
    if (invalidToastPending) return;
    invalidToastPending = true;
    window.showAppToast(event.target.validationMessage || '请完善必填字段后再保存', 'error');
    queueMicrotask(() => { invalidToastPending = false; event.target.focus?.(); });
  }, true);

  const iconPaths = {
    dashboard: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 15l3-3 3 2 4-5"/>',
    wallet: '<path d="M20 7H5a3 3 0 0 1 0-6h13a2 2 0 0 1 2 2v16H5a3 3 0 0 1-3-3V4"/><path d="M16 13h.01"/>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9"/>',
    upload: '<path d="M12 16V4M7 9l5-5 5 5M5 20h14"/>',
    tags: '<path d="M9.5 4H4v5.5L14.5 20 20 14.5 9.5 4Z"/><path d="M6.5 6.5h.01"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1A8 8 0 0 0 15 6l-.3-2.6h-4L10 6a8 8 0 0 0-1.5 1.1l-2.4-1-2 3.4L6.1 11a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.4-1A8 8 0 0 0 10 18l.7 2.6h4L15 18a8 8 0 0 0 1.5-1.1l2.4 1 2-3.4-2-1.5a7 7 0 0 0 .1-1Z"/>',
    ai: '<path d="M12 3a5 5 0 0 0-5 5v1a4 4 0 0 0-2 7.5A4.5 4.5 0 0 0 12 20a4.5 4.5 0 0 0 7-3.5A4 4 0 0 0 17 9V8a5 5 0 0 0-5-5Z"/><path d="M9 10h.01M15 10h.01M9 15c2 1 4 1 6 0"/>',
    target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
    automation: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9h10M7 13h6M7 17h4"/><circle cx="17" cy="16" r="2"/>',
    chevron: '<path d="m6 9 6 6 6-6"/>',
  };
  const svg = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${iconPaths[name] || iconPaths.dashboard}</svg>`;
  const groupIcon = name => svg(name);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const samePage = href => new URL(href, location.href).pathname.replace(/\/$/, '') === location.pathname.replace(/\/$/, '');
  const NAV_STATE_KEY = 'mocc_nav_group_state';
  const readNavState = () => { try { return JSON.parse(localStorage.getItem(NAV_STATE_KEY) || '{}') || {}; } catch (e) { return {}; } };
  const writeNavState = state => { try { localStorage.setItem(NAV_STATE_KEY, JSON.stringify(state)); } catch (e) {} };
  const NAV_CACHE_KEY = 'mocc_navigation_cache_v1';
  const readNavCache = () => { try { return JSON.parse(sessionStorage.getItem(NAV_CACHE_KEY) || 'null') || null; } catch (e) { return null; } };
  const writeNavCache = data => { try { sessionStorage.setItem(NAV_CACHE_KEY, JSON.stringify(data)); } catch (e) {} };
  const NAV_SCROLL_KEY = 'mocc_nav_scroll_top';
  const readNavScroll = () => {
    try {
      const value = Number(sessionStorage.getItem(NAV_SCROLL_KEY));
      return Number.isFinite(value) && value > 0 ? value : null;
    } catch (e) { return null; }
  };
  const writeNavScroll = value => { try { sessionStorage.setItem(NAV_SCROLL_KEY, String(Math.max(0, Math.round(value)))); } catch (e) {} };
  // 菜单滚动位置随滚动持续保存（节流），页面跳转后原样恢复，菜单不再“跳回顶部”。
  function bindScrollPersistence(menu) {
    if (!menu || menu.__scrollPersistBound) return;
    menu.__scrollPersistBound = true;
    let timer = 0;
    const save = () => writeNavScroll(menu.scrollTop);
    menu.addEventListener('scroll', () => { clearTimeout(timer); timer = setTimeout(save, 120); }, {passive: true});
    window.addEventListener('beforeunload', save);
  }

  function itemMarkup(item) {
    const url = new URL(item.href, location.href);
    const hash = url.hash.slice(1);
    if (samePage(item.href) && location.pathname.startsWith('/influencer')) {
      return `<button class="nav-item tab-button" type="button" data-tab="${esc(hash)}" data-title="${esc(item.name)}" data-subtitle="经营配置中心 · ${esc(item.name)}" data-href="${esc(item.href)}" title="${esc(item.name)}"><span>${esc(item.name)}</span></button>`;
    }
    if (samePage(item.href) && (location.pathname === '/' || location.pathname.startsWith('/ingest') || location.pathname.startsWith('/automation'))) {
      return `<button class="nav-item" type="button" data-page="${esc(hash)}" data-href="${esc(item.href)}" title="${esc(item.name)}"><span>${esc(item.name)}</span></button>`;
    }
    return `<a class="nav-item" href="${esc(item.href)}" title="${esc(item.name)}"><span>${esc(item.name)}</span></a>`;
  }

  function normalizeNavigation(data) {
    const source = data && typeof data === 'object' ? data : {};
    const groups = Array.isArray(source.groups) ? source.groups : [];
    return {
      ...source,
      user: {
        ...(source.user || {}),
        display_name: String(source.user?.display_name || '用户'),
        department_name: String(source.user?.department_name || '未分配部门'),
      },
      permissions: Array.isArray(source.permissions) ? source.permissions : [],
      groups: groups.map(group => ({
        ...(group || {}),
        code: String(group?.code || ''),
        name: String(group?.name || '未命名分类'),
        icon: String(group?.icon || 'dashboard'),
        items: Array.isArray(group?.items) ? group.items.filter(item => item && item.href).map(item => ({
          ...item,
          name: String(item.name || '未命名页面'),
          href: String(item.href),
        })) : [],
      })).filter(group => group.items.length),
    };
  }

  function setActive(sidebar) {
    const current = location.pathname.replace(/\/$/, '');
    const hash = location.hash.slice(1);
    sidebar.querySelectorAll('.nav-group').forEach(group => group.classList.remove('active'));
    sidebar.querySelectorAll('.nav-item').forEach(item => {
      const href = item.dataset.href || item.getAttribute('href') || '';
      const url = new URL(href, location.href);
      const queryMatches = !url.search || url.search === location.search;
      const active = url.pathname.replace(/\/$/, '') === current && queryMatches && (!url.hash || url.hash.slice(1) === hash || (!hash && item === item.closest('.nav-group')?.querySelector('.nav-item')));
      item.classList.toggle('active', active);
      item.classList.toggle('is-active', active);
      active ? item.setAttribute('aria-current', 'page') : item.removeAttribute('aria-current');
      if (active) item.closest('.nav-group')?.classList.add('active');
    });
  }

  function ensureActiveGroupOpen(sidebar) {
    const activeGroup = sidebar.querySelector('.nav-item.active')?.closest('.nav-group');
    if (activeGroup && !activeGroup.classList.contains('open')) {
      activeGroup.classList.add('open');
      activeGroup.querySelector('.nav-group-toggle')?.setAttribute('aria-expanded', 'true');
    }
  }

  function bindGroups(sidebar) {
    const navState = readNavState();
    sidebar.querySelectorAll('.nav-group').forEach(group => {
      const toggle = group.querySelector('.nav-group-toggle');
      const title = group.querySelector('.nav-group-link');
      const code = group.dataset.navGroup || '';
      const name = title?.textContent?.trim() || '';
      const setOpen = open => {
        group.classList.toggle('open', open);
        toggle.setAttribute('aria-expanded', String(open));
        toggle.setAttribute('aria-label', `${open ? '收起' : '展开'}${name}菜单`);
        navState[code] = open;
        writeNavState(navState);
      };
      setOpen(navState[code] !== false);
      // 标题与箭头行为一致：纯手风琴展开/收起，不再隐式跳转分组第一个页面，
      // 从根上消除“点一下分组、整页刷新、菜单弹回顶部”的割裂感。
      const toggleOpen = event => { event.preventDefault(); event.stopPropagation(); setOpen(!group.classList.contains('open')); };
      toggle.addEventListener('click', toggleOpen);
      title.addEventListener('click', toggleOpen);
      group.querySelectorAll('.nav-item[data-href]').forEach(item => item.addEventListener('click', () => {
        const target = new URL(item.dataset.href, location.href);
        if (target.hash === location.hash) window.dispatchEvent(new HashChangeEvent('hashchange'));
        else location.hash = target.hash;
      }));
    });
    if (!window.__navHashBound) {
      window.__navHashBound = true;
      window.addEventListener('hashchange', () => setActive(sidebar));
    }
    setActive(sidebar);
    ensureActiveGroupOpen(sidebar);
  }

  let lastMenuSignature = null;
  const menuSignature = groups => JSON.stringify(groups.map(group => [group.code, group.name, group.icon, group.items.map(item => [item.name, item.href])]));

  function scrollActiveIntoView(menu) {
    const item = menu.querySelector('.nav-item.active');
    if (!item) return;
    const menuRect = menu.getBoundingClientRect();
    const itemRect = item.getBoundingClientRect();
    const offsetTop = itemRect.top - menuRect.top;
    const offsetBottom = offsetTop + itemRect.height;
    if (offsetTop >= 0 && offsetBottom <= menu.clientHeight) return;
    menu.scrollTop += offsetTop - (menu.clientHeight - itemRect.height) / 2;
  }

  function renderMenu(menu, groups) {
    const signature = menuSignature(groups);
    // 导航数据未变化时跳过整体重建，只刷新激活态：
    // innerHTML 重排会把 scrollTop 清零，是菜单“无故弹回顶部”的根源之一。
    if (signature === lastMenuSignature && menu.querySelector('.nav-group')) {
      const sidebar = document.querySelector('.sidebar');
      setActive(sidebar);
      ensureActiveGroupOpen(sidebar);
      return;
    }
    const navState = readNavState();
    const savedScroll = readNavScroll();
    const currentScroll = menu.scrollTop;
    menu.innerHTML = groups.map(group => `<section class="nav-group ${navState[group.code] !== false ? 'open' : ''}" data-nav-group="${esc(group.code)}">
        <div class="nav-group-header"><a class="nav-group-link" href="${esc(group.items[0].href)}">${groupIcon(group.icon)}<span title="${esc(group.name)}">${esc(group.name)}</span></a><button class="nav-group-toggle" type="button" aria-expanded="${navState[group.code] !== false}" aria-label="${navState[group.code] !== false ? '收起' : '展开'}${esc(group.name)}菜单">${svg('chevron')}</button></div>
        <div class="nav-group-items"><nav aria-label="${esc(group.name)}">${group.items.map(itemMarkup).join('')}</nav></div>
      </section>`).join('');
    menu.classList.remove('nav-loading');
    lastMenuSignature = signature;
    bindScrollPersistence(menu);
    bindGroups(document.querySelector('.sidebar'));
    // 重建后恢复滚动位置：优先本次会话持续保存的位置，其次重建前的瞬时位置；
    // 两者都没有（首次进入/新开标签页）时把激活项滚动到可视区域中央。
    // 必须等 renderShell 其余部分（侧边栏 footer 等）就位后再恢复——
    // 否则容器尚未被 footer 压缩，scrollTop 会被钳位到偏小的值。
    const targetScroll = savedScroll ?? currentScroll;
    requestAnimationFrame(() => {
      if (targetScroll) menu.scrollTop = targetScroll;
      else scrollActiveIntoView(menu);
    });
  }

  function renderShell(data) {
    data = normalizeNavigation(data);
    window.currentUser = data.user;
    window.currentPermissions = new Set(data.permissions || []);
    const menu = document.querySelector('.sidebar-menu');
    if (menu) renderMenu(menu, data.groups);
    const hasPermission = node => {
      const permission = node.dataset.permission || node.dataset.pagePermission;
      return Boolean(permission) && window.currentPermissions.has(permission)
        && (!node.dataset.pagePermission || window.currentPermissions.has(node.dataset.pagePermission));
    };
    document.querySelectorAll('[data-permission],[data-page-permission]').forEach(node => { node.hidden = !hasPermission(node); });
    const buttonPermissions={openImport:'bank.statement.import',openImport2:'bank.statement.import',submitBatch:'bank.statement.submit',withdrawSubmit:'bank.statement.withdraw',addType:'bank.types.manage',addAccount:'bank.accounts.manage',addInfluencerButton:'influencer.assignments.manage',saveInfluencerEdit:'influencer.assignments.manage',addBusinessButton:'influencer.targets.manage',submitFiles:'ingest.upload.manage',fullRefresh:'ingest.etl.manage',addCategory:'platform_fee.categories.manage'};
    Object.entries(buttonPermissions).forEach(([id,permission])=>{const node=document.getElementById(id);if(node&&!window.currentPermissions.has(permission))node.hidden=true});
    const enforceActionPermissions=()=>{
      document.querySelectorAll('[data-permission],[data-page-permission]').forEach(node=>{node.hidden=!hasPermission(node)});
      const rules=[
        ['bank.types.manage','#typesPage .table-actions,#typesPage td:last-child button'],['bank.accounts.manage','#accountsPage .table-actions,#accountsPage td:last-child button'],
        ['influencer.assignments.manage','#assignmentTableBody button'],['influencer.targets.manage','#targetTableBody button'],
        ['platform_fee.categories.manage','#categoryBody button'],['platform_fee.mappings.manage','#feeBody button'],
      ];
      rules.forEach(([permission,selector])=>{if(!window.currentPermissions.has(permission))document.querySelectorAll(selector).forEach(node=>node.hidden=true)});
    };
    enforceActionPermissions();
    if(!window.permissionUiObserver){window.permissionUiObserver=new MutationObserver(enforceActionPermissions);window.permissionUiObserver.observe(document.querySelector('main')||document.body,{childList:true,subtree:true})}
    const pagePermissions={
      '/':{statement:'bank.statement.view',types:'bank.types.view',accounts:'bank.accounts.view',imports:'bank.imports.view',logs:'bank.logs.view'},
      '/influencer':{assignmentPanel:'influencer.assignments.view',targetPanel:'influencer.targets.view',productCategoryPanel:'influencer.products.view',productMappingPanel:'influencer.products.view'},
      '/ingest':{upload:'ingest.upload.view',runs:'ingest.runs.view',etl:'ingest.etl.view',logs:'ingest.logs.view',feeCategories:'platform_fee.categories.view',feeMappings:'platform_fee.mappings.view',sceneRules:'platform_fee.mappings.view',rawFees:'platform_fee.raw.view',financeBudget:'finance_budget.overview.view',financeOverview:'finance_budget.overview.view',financeGsv:'finance_budget.gsv.view',financePromotion:'finance_budget.promotion.view',financeAdjustments:'finance_budget.adjustment.view',financeRecharges:'finance_budget.recharge.view',financeSpend:'finance_budget.spend.view',financeMarketing:'finance_budget.marketing.view',financeExpenseTypes:'finance_budget.expense_type.view'},
      '/automation':{reports:'automation.results.view',runs:'automation.runs.view',schedules:'automation.jobs.view','flow-studio':'automation.flows.view',runtime:'automation.workbench.view'},
      '/system':{dashboards:'system.dashboard.manage',users:'system.user.manage',departments:'system.department.manage',roles:'system.role.manage',permissions:'system.permission.manage',platformShopCompany:'system.platform_shop_company.view',audit:'system.audit.view'},
      '/ai-admin':{models:'ai.model.manage',sources:'ai.datasource.manage',prompts:'ai.prompt.manage',feishuApps:'ai.feishu_app.manage',verificationRelays:'ai.feishu_app.manage',audit:'ai.audit.view'}
    };
    const base=location.pathname.replace(/\/$/,'')||'/';const defaults={'/':'statement','/influencer':'assignmentPanel','/ingest':'upload','/automation':'reports','/system':'dashboards','/ai-admin':'models'};const wanted=location.hash.slice(1)||defaults[base];const required=pagePermissions[base]?.[wanted];
    if(required&&!window.currentPermissions.has(required)){const first=data.groups.flatMap(group=>group.items).find(item=>new URL(item.href,location.href).pathname.replace(/\/$/,'')===(base==='/'?'':base));if(first)location.replace(first.href)}
    const sidebar = document.querySelector('.sidebar');
    if (sidebar && !sidebar.querySelector('.current-user')) {
      const widget = document.createElement('div');
      widget.className = 'current-user';
      widget.innerHTML = `<button class="current-user-trigger" type="button" title="${esc(data.user.display_name)} · ${esc(data.user.department_name || '未分配部门')}"><span class="user-avatar">${esc(data.user.display_name.slice(0, 1))}</span><span class="user-copy"><b>${esc(data.user.display_name)}</b><small>${esc(data.user.department_name || '未分配部门')}</small></span></button><div class="user-menu" hidden><button type="button" data-user-action="password">修改密码</button><button type="button" data-user-action="logout">退出登录</button></div>`;
      let footer = sidebar.querySelector('.sidebar-footer');
      if (!footer) {
        footer = document.createElement('div');
        footer.className = 'sidebar-footer';
        sidebar.append(footer);
      }
      footer.append(widget);
      const menuNode = widget.querySelector('.user-menu');
      widget.querySelector('.current-user-trigger').onclick = () => { menuNode.hidden = !menuNode.hidden; };
      widget.querySelector('[data-user-action="logout"]').onclick = async () => { await fetch('/api/auth/logout', {method:'POST'}); sessionStorage.removeItem(NAV_CACHE_KEY); location.assign('/login/'); };
      widget.querySelector('[data-user-action="password"]').onclick = changePassword;
      document.addEventListener('click', event => {
        if (!event.target.closest('.current-user')) {
          document.querySelectorAll('.user-menu').forEach(menu => { menu.hidden = true; });
        }
      });
    }
    window.dispatchEvent(new CustomEvent('app:navigation-ready', {detail: data}));
  }

  async function changePassword() {
    const current = prompt('请输入当前密码'); if (current === null) return;
    const next = prompt('请输入新密码（10-128位）'); if (next === null) return;
    const response = await fetch('/api/auth/change-password', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({current_password:current,new_password:next})});
    const result = await response.json();
    alert(response.ok ? '密码已修改，其他会话已失效' : result.message);
  }

  const cachedNav = readNavCache();
  if (cachedNav) renderShell(cachedNav);
  else document.querySelector('.sidebar-menu')?.classList.add('nav-loading');
  window.refreshAppNavigation = () => nativeFetch('/api/navigation', {credentials:'same-origin'}).then(async response => {
    if (response.status === 401) { location.assign(`/login/?next=${encodeURIComponent(location.pathname + location.search + location.hash)}`); return; }
    const result = await response.json();
    if (!response.ok) throw new Error(result.message || '导航加载失败');
    writeNavCache(result.data);
    renderShell(result.data);
  });
  window.refreshAppNavigation().catch(error => {
    const menu = document.querySelector('.sidebar-menu');
    if (menu) menu.classList.remove('nav-loading');
    if (menu && !menu.querySelector('.nav-group')) menu.innerHTML = `<div class="nav-error">${esc(error.message)}<button onclick="location.reload()">重新加载</button></div>`;
  });

  const initHealthBadge = () => {
    const topbar = document.querySelector('.topbar');
    if (!topbar) return;
    let badge = document.querySelector('#healthBadge, .topbar .health-badge');
    if (!badge) {
      badge = document.createElement('div');
      badge.id = 'shellHealthBadge';
      badge.className = 'health-badge is-loading';
      badge.innerHTML = '<span class="health-dot"></span><span>连接中</span>';
      topbar.append(badge);
    }
    const render = (ok, text) => {
      badge.className = `health-badge ${ok ? 'is-ok' : 'is-error'}`;
      badge.innerHTML = `<span class="health-dot"></span><span>${text}</span>`;
    };
    const unwrap = async response => {
      const result = await response.json();
      return result && typeof result === 'object' && 'data' in result ? result.data : result;
    };
    const refresh = async () => {
      try {
        const response = await nativeFetch('/api/health', {credentials: 'same-origin'});
        if (!response.ok) throw new Error('统一健康检查失败');
        const data = await unwrap(response);
        const failed = Array.isArray(data.failed) ? data.failed : [];
        const first = failed[0];
        const workerOk = Number(data.modules?.worker?.active_worker_count || 0) > 0;
        const text = data.ready ? '数据库与 Worker 正常' : (first?.message || '服务状态异常');
        render(Boolean(data.ready), text);
        const detail = {ready:Boolean(data.ready), workerOk, message:text, failed, data};
        window.appHealthState = detail;
        window.dispatchEvent(new CustomEvent('health:change', {detail}));
      } catch (e) {
        render(false, '数据库连接失败');
        const detail = {ready:false, workerOk:false, message:'数据库连接失败', failed:[{kind:'database'}], data:null};
        window.appHealthState = detail;
        window.dispatchEvent(new CustomEvent('health:change', {detail}));
      }
    };
    const interval = Math.max(5000, Number(document.body.dataset.healthInterval || 30000));
    window.appHealth = {refresh, interval};
    refresh();
    setInterval(refresh, interval);
  };
  initHealthBadge();
})();
