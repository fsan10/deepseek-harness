const state = {
  month: "",
  businesses: [],
  influencers: [],
  targets: [],
  editingInfluencer: null,
  page: 1,
  pageSize: 10,
  totalPages: 1,
};

const el = (id) => document.getElementById(id);
const scriptUrl = new URL(document.currentScript?.src || "app.js", window.location.href);
const moduleBaseUrl = new URL(".", scriptUrl);
const integratedMount = moduleBaseUrl.pathname.replace(/\/$/, "").endsWith("/influencer");
const apiPrefix = integratedMount
  ? new URL("../api/influencer", moduleBaseUrl).pathname.replace(/\/$/, "")
  : new URL("api", moduleBaseUrl).pathname.replace(/\/$/, "");
const currency = new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", minimumFractionDigits: 0, maximumFractionDigits: 2 });
const number = new Intl.NumberFormat("zh-CN");
const percent = new Intl.NumberFormat("zh-CN", { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 });

function currentMonth() {
  const today = new Date();
  return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
}

function bindNativePicker(input) {
  if (!input) return;
  const open = () => {
    if (input.disabled) return;
    input.focus();
    if (typeof input.showPicker !== "function") return;
    try { input.showPicker(); } catch (_error) { input.focus(); }
  };
  input.addEventListener("click", open);
  input.closest("label")?.addEventListener("click", (event) => {
    if (event.target === input) return;
    event.preventDefault();
    open();
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function syncSelectTitle(select) {
  if (!(select instanceof HTMLSelectElement)) return;
  [...select.options].forEach((option) => {
    option.title = (option.textContent || "").trim();
  });
  const selected = select.options[select.selectedIndex];
  select.title = selected ? (selected.textContent || "").trim() : "";
}

function enhanceNativeSelects() {
  const syncWithin = (root) => {
    if (root instanceof HTMLSelectElement) syncSelectTitle(root);
    else if (root?.querySelectorAll) root.querySelectorAll("select").forEach(syncSelectTitle);
  };
  syncWithin(document);
  document.addEventListener("change", (event) => syncSelectTitle(event.target));
  document.addEventListener("mouseover", (event) => syncSelectTitle(event.target));
  document.addEventListener("focusin", (event) => syncSelectTitle(event.target));
  new MutationObserver((mutations) => mutations.forEach((mutation) => {
    syncWithin(mutation.target);
    mutation.addedNodes.forEach(syncWithin);
  })).observe(document.body, { childList: true, subtree: true });
}

async function api(path, options = {}) {
  const requestPath = path.startsWith("/api/") ? `${apiPrefix}${path.slice(4)}` : path;
  const response = await fetch(requestPath, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({ ok: false, error: "服务返回了无效JSON" }));
  const succeeded = Object.hasOwn(payload, "ok") ? payload.ok : payload.code === 0;
  if (!response.ok || !succeeded) {
    const error = new Error(payload.error || payload.message || `HTTP ${response.status}`);
    error.details = payload.details || payload.data?.details;
    error.status = response.status;
    throw error;
  }
  if (options.method && options.method !== "GET" && path.startsWith("/api/product") && payload.data?.dashboard_refresh) {
    window.productMappingModule?.onSaved?.();
  }
  return payload.data;
}

function toast(message, type = "success") {
  const t = type === true ? "error" : type;
  if (window.showAppToast && window.hasOpenEditor?.()) return window.showAppToast(message, t);
  const node = el("toast");
  node.textContent = message;
  node.className = `toast show ${t}`;
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => { node.className = "toast"; }, 3200);
}

function metricCard(label, value, meta, accent = false) {
  return `<article class="metric-card ${accent ? "accent" : ""}">
    <div class="metric-label">${escapeHtml(label)}</div>
    <div class="metric-value">${escapeHtml(value)}</div>
    <div class="metric-meta">${escapeHtml(meta)}</div>
  </article>`;
}

async function loadBusinesses() {
  state.businesses = await api("/api/businesses");
  const filter = el("businessFilter");
  const current = filter.value;
  filter.innerHTML = `<option value="">全部商务</option>` + state.businesses
    .filter((item) => item.is_active)
    .map((item) => `<option value="${item.business_owner_id}">${escapeHtml(item.business_owner_name)}</option>`)
    .join("");
  filter.value = current;
}

function ownerOptions(selectedId) {
  return `<option value="">未分配商务</option>` + state.businesses
    .filter((item) => item.is_active)
    .map((item) => `<option value="${item.business_owner_id}" ${Number(selectedId) === Number(item.business_owner_id) ? "selected" : ""}>${escapeHtml(item.business_owner_name)}</option>`)
    .join("");
}

function renderAssignmentCards(summary) {
  el("assignmentCards").innerHTML = [
    metricCard("配置库达人", number.format(summary.total), "所选月份已生效配置"),
    metricCard("已分配 / 未分配", `${number.format(summary.assigned)} / ${number.format(summary.unassigned)}`, "按最新有效版本"),
    metricCard("覆盖平台", number.format(summary.platforms), "受当前筛选条件影响"),
    metricCard("Excel / 网页版本", `${number.format(summary.excel_seed)} / ${number.format(summary.web)}`, "当前生效版本来源"),
  ].join("");
}

function getPageNumbers(current, total, maxVisible = 5) {
  if (total <= 1) return [1];
  if (total <= maxVisible) return Array.from({ length: total }, (_, i) => i + 1);
  let start = Math.max(1, current - Math.floor(maxVisible / 2));
  let end = start + maxVisible - 1;
  if (end > total) {
    end = total;
    start = Math.max(1, end - maxVisible + 1);
  }
  return Array.from({ length: end - start + 1 }, (_, i) => start + i);
}

function renderPagination(pagination) {
  state.page = Number(pagination.page);
  state.pageSize = Number(pagination.page_size);
  state.totalPages = Number(pagination.total_pages);
  const total = Number(pagination.total);
  el("paginationRange").textContent = `共 ${number.format(total)} 条`;
  el("paginationPage").textContent = `第 ${number.format(state.page)}/${number.format(state.totalPages)} 页`;
  el("pageSizeSelect").value = String(state.pageSize);
  el("previousPage").disabled = state.page <= 1;
  el("nextPage").disabled = state.page >= state.totalPages;

  const pages = getPageNumbers(state.page, state.totalPages);
  el("pageNumbers").innerHTML = pages
    .map((page) => `<button class="pagination-page-btn ${page === state.page ? "is-active" : ""}" type="button" data-page="${page}" aria-label="第 ${page} 页" ${page === state.page ? "aria-current='page'" : ""}>${number.format(page)}</button>`)
    .join("");
  el("pageNumbers").querySelectorAll(".pagination-page-btn").forEach((button) => {
    button.addEventListener("click", () => {
      state.page = Number(button.dataset.page);
      loadAssignments();
    });
  });
}

function renderAssignments(data) {
  state.influencers = data.rows;
  renderAssignmentCards(data.summary);
  renderPagination(data.pagination);
  const body = el("assignmentTableBody");
  const empty = el("assignmentEmpty");
  empty.hidden = data.rows.length > 0;
  body.innerHTML = data.rows.map((row, index) => {
    const source = row.assignment_source === "web" ? "网页版本" : row.assignment_source === "excel_seed" ? "Excel初始" : "暂无版本";
    const shops = (row.source_shop_names || []).join("、");
    const isActive = row.is_active !== false;
    const statusBadge = isActive
      ? '<span class="status-badge status-active">启用</span>'
      : '<span class="status-badge status-disabled">停用</span>';
    const toggleButton = isActive
      ? '<button class="table-action action-disable toggle-influencer" type="button"><svg><use href="#i-power"/></svg>停用</button>'
      : '<button class="table-action action-enable toggle-influencer" type="button"><svg><use href="#i-power"/></svg>启用</button>';
    return `<tr data-index="${index}" class="${isActive ? "" : "row-disabled"}">
      <td><span class="platform-chip">${escapeHtml(row.platform_name)}</span></td>
      <td><span class="influencer-name">${escapeHtml(row.influencer_name)}</span></td>
      <td><span class="money">${escapeHtml(row.influencer_id)}</span></td>
      <td><span>${shops ? escapeHtml(shops) : "—"}</span></td>
      <td><span>${escapeHtml(row.business_owner_name || "未分配商务")}</span></td>
      <td><span class="source-chip">${escapeHtml(source)}</span><span class="subtext">${row.effective_month ? escapeHtml(row.effective_month.slice(0, 7)) : "未生效"}</span></td>
      <td>${statusBadge}<span class="subtext">${escapeHtml(row.note || "—")}</span></td>
      <td><div class="row-actions"><button class="table-action action-edit edit-influencer" type="button"><svg><use href="#i-edit"/></svg>编辑</button><span class="action-divider">|</span>${toggleButton}<span class="action-divider">|</span><button class="table-action action-delete delete-influencer" type="button"><svg><use href="#i-trash"/></svg>删除</button></div></td>
    </tr>`;
  }).join("");

  body.querySelectorAll(".edit-influencer").forEach((button) => {
    button.addEventListener("click", () => openInfluencerEditor(state.influencers[Number(button.closest("tr").dataset.index)]));
  });
  body.querySelectorAll(".toggle-influencer").forEach((button) => {
    button.addEventListener("click", () => toggleInfluencerStatus(state.influencers[Number(button.closest("tr").dataset.index)], button));
  });
  body.querySelectorAll(".delete-influencer").forEach((button) => {
    button.addEventListener("click", () => deleteInfluencer(state.influencers[Number(button.closest("tr").dataset.index)], button));
  });
}

async function loadAssignments() {
  const params = new URLSearchParams({
    month: state.month,
    page: String(state.page),
    page_size: String(state.pageSize),
  });
  const platform = el("platformFilter").value;
  const business = el("businessFilter").value;
  const status = el("statusFilter").value;
  const activeStatus = el("activeStatusFilter").value;
  const search = el("searchInput").value.trim();
  if (platform) params.set("platform", platform);
  if (business) params.set("business_owner_id", business);
  if (status) params.set("status", status);
  if (activeStatus) params.set("active_status", activeStatus);
  if (search) params.set("search", search);
  el("assignmentTableBody").innerHTML = `<tr><td colspan="8">正在读取达人配置库…</td></tr>`;
  try {
    renderAssignments(await api(`/api/influencers?${params}`));
  } catch (error) {
    el("assignmentTableBody").innerHTML = "";
    toast(error.message, true);
  }
}

function resetAndLoadAssignments() {
  state.page = 1;
  return loadAssignments();
}

function openInfluencerEditor(row = null) {
  state.editingInfluencer = row;
  el("influencerDialogTitle").textContent = row ? "编辑达人配置" : "新增达人";
  el("editorPlatform").value = row?.platform_code || "douyin";
  el("editorInfluencerId").value = row?.influencer_id || "";
  el("editorInfluencerName").value = row?.influencer_name || "";
  el("editorBusinessOwner").innerHTML = ownerOptions(row?.business_owner_id);
  el("editorShopNames").value = (row?.source_shop_names || []).join("\n");
  el("editorNote").value = row?.note || "";
  el("influencerDialog").showModal();
}

function closeInfluencerEditor() {
  el("influencerDialog").close();
  state.editingInfluencer = null;
}

async function saveInfluencer(event) {
  event.preventDefault();
  const button = el("saveInfluencerEdit");
  const original = state.editingInfluencer;
  button.disabled = true;
  button.textContent = "保存中";
  try {
    await api("/api/assignments", {
      method: "POST",
      body: JSON.stringify({
        platform_code: el("editorPlatform").value,
        influencer_id: el("editorInfluencerId").value.trim(),
        influencer_name: el("editorInfluencerName").value.trim(),
        effective_month: `${state.month}-01`,
        business_owner_id: el("editorBusinessOwner").value || null,
        source_shop_names: el("editorShopNames").value,
        note: el("editorNote").value,
        original_platform_code: original?.platform_code,
        original_influencer_id: original?.influencer_id,
      }),
    });
    closeInfluencerEditor();
    toast(`已保存${state.month}达人配置`);
    await Promise.all([loadAssignments(), loadTargets()]);
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "保存配置";
  }
}

async function toggleInfluencerStatus(row, button) {
  const isActive = row.is_active !== false;
  const action = isActive ? "停用" : "启用";
  if (!window.confirm(`确认${action}达人“${row.influencer_name}”吗？`)) return;
  button.disabled = true;
  try {
    await api("/api/influencers/toggle-status", {
      method: "POST",
      body: JSON.stringify({
        platform_code: row.platform_code,
        influencer_id: row.influencer_id,
        effective_month: state.month,
        is_active: !isActive,
      }),
    });
    toast(`已${action} ${row.influencer_name}`);
    await Promise.all([loadAssignments(), loadTargets()]);
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function deleteInfluencer(row, button) {
  if (!window.confirm(`确认从${state.month}起删除“${row.influencer_name}”吗？\n删除后商务归属将被清空，之前月份的历史配置仍会保留。`)) return;
  button.disabled = true;
  try {
    const params = new URLSearchParams({
      platform: row.platform_code,
      influencer_id: row.influencer_id,
      month: state.month,
    });
    await api(`/api/influencers?${params}`, { method: "DELETE" });
    toast(`已删除 ${row.influencer_name}`);
    await Promise.all([loadAssignments(), loadTargets()]);
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

function renderTargetCards(rows) {
  const totalTarget = rows.reduce((sum, item) => sum + Number(item.gmv_target || 0), 0);
  const totalActual = rows.reduce((sum, item) => sum + Number(item.actual_gmv_amount || 0), 0);
  const managed = rows.reduce((sum, item) => sum + Number(item.assigned_influencer_count || 0), 0);
  const plus100k = rows.reduce((sum, item) => sum + Number(item.influencer_100k_plus_count || 0), 0);
  const completion = totalTarget ? totalActual / totalTarget : 0;
  el("targetCards").innerHTML = [
    metricCard("月度总目标", currency.format(totalTarget), `${rows.length}位在职商务`, true),
    metricCard("实际达成", currency.format(totalActual), `总完成率 ${percent.format(completion)}`),
    metricCard("归属达人", number.format(managed), "包含当月无GMV的已归属达人"),
    metricCard("月10万+达人", number.format(plus100k), "按商务名下跨平台GMV统计"),
  ].join("");
}

function renderTargets(data) {
  state.targets = data.rows;
  renderTargetCards(data.rows);
  el("targetTableBody").innerHTML = data.rows.map((row, index) => {
    const width = Math.max(0, Math.min(100, Number(row.completion_rate) * 100));
    return `<tr data-index="${index}">
      <td><input class="business-name-input" type="text" maxlength="128" value="${escapeHtml(row.business_owner_name)}" aria-label="商务姓名" title="直接修改后点击本行保存"></td>
      <td><input class="target-input" type="number" min="0" step="1000" value="${Number(row.gmv_target).toFixed(2)}" aria-label="${escapeHtml(row.business_owner_name)}GMV目标"></td>
      <td><span class="money">${currency.format(row.actual_gmv_amount)}</span></td>
      <td><span class="money">${percent.format(row.completion_rate)}</span><div class="progress"><span style="width:${width}%"></span></div></td>
      <td><span class="money">${number.format(row.assigned_influencer_count)}</span></td>
      <td><span class="money">${number.format(row.influencer_100k_plus_count)}</span></td>
      <td><input class="note-input" type="text" maxlength="500" value="${escapeHtml(row.note || "")}" placeholder="可选备注"></td>
      <td><div class="target-row-actions"><button class="icon-action action-save save-target" type="button"><svg><use href="#i-check"/></svg><span>保存</span></button><button class="icon-action action-delete delete-business" type="button"><svg><use href="#i-trash"/></svg><span>删除</span></button></div></td>
    </tr>`;
  }).join("");
  el("targetTableBody").querySelectorAll(".save-target").forEach((button) => {
    button.addEventListener("click", () => saveTarget(button));
  });
  el("targetTableBody").querySelectorAll(".delete-business").forEach((button) => {
    button.addEventListener("click", () => deleteBusiness(button));
  });
}

async function loadTargets() {
  try {
    renderTargets(await api(`/api/targets?month=${encodeURIComponent(state.month)}`));
  } catch (error) {
    el("targetTableBody").innerHTML = `<tr><td colspan="8">读取失败：${escapeHtml(error.message)}</td></tr>`;
    toast(error.message, true);
  }
}

async function saveTarget(button) {
  const rowNode = button.closest("tr");
  const row = state.targets[Number(rowNode.dataset.index)];
  const businessName = rowNode.querySelector(".business-name-input").value.trim();
  const target = rowNode.querySelector(".target-input").value;
  const note = rowNode.querySelector(".note-input").value;
  if (!businessName) return toast("商务姓名不能为空", true);
  button.disabled = true;
  const label = button.querySelector("span");
  if (label) label.textContent = "保存中";
  else button.textContent = "保存中";
  try {
    await api("/api/targets", {
      method: "POST",
      body: JSON.stringify({
        target_month: `${state.month}-01`,
        business_owner_id: row.business_owner_id,
        business_owner_name: businessName,
        gmv_target: target,
        note,
      }),
    });
    toast(`已保存 ${businessName} 的${state.month}GMV目标`);
    await Promise.all([loadBusinesses(), loadAssignments(), loadTargets()]);
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    if (label) label.textContent = "保存";
    else button.textContent = "保存";
  }
}

async function deleteBusiness(button) {
  const rowNode = button.closest("tr");
  const row = state.targets[Number(rowNode.dataset.index)];
  const displayName = rowNode.querySelector(".business-name-input").value.trim() || row.business_owner_name;
  if (!window.confirm(`确认删除商务“${displayName}”？\n删除后将不再出现在商务配置中，历史归属和目标仍会保留。`)) return;
  button.disabled = true;
  const label = button.querySelector("span");
  if (label) label.textContent = "删除中";
  else button.textContent = "删除中";
  try {
    await api(`/api/businesses/${encodeURIComponent(row.business_owner_id)}`, { method: "DELETE" });
    toast(`已删除商务 ${row.business_owner_name}`);
    await Promise.all([loadBusinesses(), loadAssignments(), loadTargets()]);
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    if (label) label.textContent = "删除";
    else button.textContent = "删除";
  }
}

async function addBusiness() {
  const input = el("newBusinessName");
  const name = input.value.trim();
  if (!name) return toast("请输入商务姓名", true);
  const button = el("addBusinessButton");
  button.disabled = true;
  try {
    await api("/api/businesses", { method: "POST", body: JSON.stringify({ business_owner_name: name }) });
    input.value = "";
    toast(`已新增商务 ${name}`);
    await Promise.all([loadBusinesses(), loadAssignments(), loadTargets()]);
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

function bindEvents() {
  const activateTab = (button, updateHash = true) => {
    if (!button) return;
    document.querySelectorAll(".tab-button").forEach((item) => {
      const active = item === button;
      item.classList.toggle("is-active", active);
      item.classList.toggle("active", active);
      active ? item.setAttribute("aria-current", "page") : item.removeAttribute("aria-current");
    });
    document.querySelectorAll(".tab-panel").forEach((item) => item.classList.toggle("is-active", item.id === button.dataset.tab));
    el("pageTitle").textContent = button.dataset.title;
    el("pageSubtitle").textContent = button.dataset.subtitle;
    document.querySelector(".month-control").hidden = [
      "productCategoryPanel", "productMappingPanel",
    ].includes(button.dataset.tab);
    if (button.dataset.tab === "assignmentPanel") window.influencerMasterModule?.activate();
    if (button.dataset.tab === "productCategoryPanel") window.productCategoryModule?.activate();
    if (button.dataset.tab === "productMappingPanel") window.productMappingModule?.activate();
    if (updateHash) history.replaceState(null, "", `#${button.dataset.tab}`);
  };

  document.querySelectorAll(".tab-button").forEach((button) => {
    button.addEventListener("click", () => activateTab(button));
  });
  window.addEventListener("hashchange", () => activateTab(document.querySelector(`.tab-button[data-tab="${location.hash.slice(1)}"]`), false));
  activateTab(document.querySelector(`.tab-button[data-tab="${location.hash.slice(1)}"]`) || document.querySelector(".tab-button"), false);
  el("globalMonth").addEventListener("change", async (event) => {
    state.month = event.target.value;
    state.page = 1;
    await Promise.all([loadAssignments(), loadTargets()]);
    await window.influencerMasterModule?.activate(true);
  });
  el("reloadAssignments").addEventListener("click", resetAndLoadAssignments);
  el("pageSizeSelect").addEventListener("change", (event) => {
    state.pageSize = Number(event.target.value);
    state.page = 1;
    loadAssignments();
  });
  el("previousPage").addEventListener("click", () => {
    if (state.page <= 1) return;
    state.page -= 1;
    loadAssignments();
  });
  el("nextPage").addEventListener("click", () => {
    if (state.page >= state.totalPages) return;
    state.page += 1;
    loadAssignments();
  });
  el("addInfluencerButton").addEventListener("click", () => openInfluencerEditor());
  el("influencerForm").addEventListener("submit", saveInfluencer);
  el("closeInfluencerDialog").addEventListener("click", closeInfluencerEditor);
  el("cancelInfluencerEdit").addEventListener("click", closeInfluencerEditor);
  el("addBusinessButton").addEventListener("click", addBusiness);
  el("newBusinessName").addEventListener("keydown", (event) => {
    if (event.key === "Enter") addBusiness();
  });
}

async function initialize() {
  state.month = currentMonth();
  el("globalMonth").value = state.month;
  bindNativePicker(el("globalMonth"));
  enhanceNativeSelects();
  bindEvents();
  try {
    await Promise.allSettled([loadBusinesses(), loadAssignments(), loadTargets()]);
    if (document.querySelector('.tab-button.is-active')?.dataset.tab === 'productCategoryPanel') {
      await window.productCategoryModule?.activate();
    }
    if (document.querySelector('.tab-button.is-active')?.dataset.tab === 'productMappingPanel') {
      await window.productMappingModule?.activate();
    }
  } catch (error) {
    toast(error.message, true);
  }
}

window.influencerApp = { api, toast, escapeHtml, el };
initialize();
