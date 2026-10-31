(() => {
  const platformNames = {
    douyin: "抖音", tmall: "天猫", wechat_channels: "视频号",
    ks: "快手", xhs: "小红书", jd: "京东", pdd: "拼多多", "*": "历史全平台",
  };
  const app = () => window.influencerApp;
  const esc = (value) => app().escapeHtml(value ?? "");
  const money = new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const dateText = (value) => value ? String(value).slice(0, 10) : "-";
  const state = {
    product: { initialized: false, view: "products", page: 1, pageSize: 10, totalPages: 1, total: 0, unmappedTotal: 0, search: "", status: "all", platform: "", rows: [], categories: [], products: [], selected: new Map(), batchMode: false, loading: false, requestVersion: 0, categoriesLoaded: false, productsLoaded: false, basePromise: null },
    influencer: { initialized: false, view: "company", page: 1, pageSize: 10, totalPages: 1, total: 0, unmappedTotal: 0, search: "", status: "all", platform: "", business: "", gmvMin: "", rows: [], companies: [], businesses: [], selected: new Map(), batchMode: false, loading: false },
  };
  let assignContext = null;
  let productRefreshTimer = null;
  let productRefreshPending = false;

  function showProductRefresh(snapshot) {
    const node = document.getElementById("productRefreshNotice");
    if (!node) return;
    node.hidden = !snapshot?.pending && !!snapshot?.snapshot_id;
    node.innerHTML = snapshot?.error
      ? `${esc(snapshot.error)} <button class="button" type="button" id="retryProductRefresh">重试更新</button>`
      : snapshot?.pending ? "商品统计更新中，当前展示上次成功结果。" : "商品统计尚未生成，请完成首次刷新。";
    node.querySelector("#retryProductRefresh")?.addEventListener("click", async () => {
      try {
        await app().api("/api/product-mappings/refresh", { method: "POST", body: "{}" });
        showProductRefresh({ pending: true });
        watchProductRefresh();
      } catch (error) { app().toast(error.message, true); }
    });
  }

  function watchProductRefresh() {
    productRefreshPending = true;
    if (productRefreshTimer) return;
    productRefreshTimer = window.setTimeout(async () => {
      productRefreshTimer = null;
      if (!["productMappingPanel", "productCategoryPanel"].includes(document.querySelector('.tab-button.is-active')?.dataset.tab)) return;
      try {
        const result = await app().api("/api/refresh-status");
        const status = result.product_dashboard;
        if (status?.pending && status.status !== "failed") return watchProductRefresh();
        if (status?.status === "failed") {
          showProductRefresh({ pending: true, error: status.last_error || "商品统计更新失败，请重试。" });
          return;
        }
        productRefreshPending = false;
        state.product.categoriesLoaded = false;
        state.product.productsLoaded = false;
        await loadProduct(true);
      } catch (error) {
        showProductRefresh({ pending: true, error: error.message });
      }
    }, 1500);
  }

  function hideTablePopover() {
    const popover = document.getElementById("tablePopover");
    if (!popover) return;
    popover.hidden = true;
    popover.className = "table-popover";
    popover.innerHTML = "";
  }

  function showTablePopover(kind, html, onConfirm) {
    const popover = document.getElementById("tablePopover");
    if (!popover) return onConfirm();
    popover.className = `table-popover ${kind}`;
    popover.innerHTML = html;
    popover.hidden = false;
    popover.querySelector("[data-popover-cancel]")?.addEventListener("click", hideTablePopover);
    popover.querySelector("[data-popover-confirm]")?.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      try {
        button.disabled = true;
        button.textContent = "处理中…";
        await onConfirm();
        hideTablePopover();
      } catch (error) {
        app().toast(error.message, true);
        button.disabled = false;
        button.textContent = "确定修改";
      }
    });
  }

  function platformOptions(includeAll = true) {
    return `${includeAll ? '<option value="">全部平台</option>' : ""}${Object.entries(platformNames)
      .filter(([code]) => code !== "*")
      .map(([code, name]) => `<option value="${code}">${name}</option>`).join("")}`;
  }

  function platformText(value) {
    return String(value || "")
      .split(/[、,，]+/)
      .map((code) => platformNames[code.trim()] || code.trim())
      .filter(Boolean)
      .join("、") || "-";
  }

  function pageNumbers(current, total, maxVisible = 5) {
    if (total <= maxVisible) return Array.from({ length: total }, (_, index) => index + 1);
    let start = Math.max(1, current - Math.floor(maxVisible / 2));
    let end = start + maxVisible - 1;
    if (end > total) { end = total; start = Math.max(1, end - maxVisible + 1); }
    return Array.from({ length: end - start + 1 }, (_, index) => start + index);
  }

  function paginationSummary(scope) {
    const s = state[scope];
    return scope !== "product" && scope !== "influencer" || !["source", "mappings"].includes(s.view)
      ? `共 ${s.total || 0} 条`
      : `共 ${s.total || 0} 条 · 未映射 ${s.unmappedTotal || 0} 条`;
  }

  function pager(scope) {
    const s = state[scope];
    const totalPages = Math.max(1, s.totalPages || 1);
    return `<div class="master-pagination pagination-bar"><span class="pagination-summary">${paginationSummary(scope)}</span><div class="pagination-controls">
      <select class="select-chevron pagination-size" data-action="page-size" aria-label="每页条数"><option value="10" ${s.pageSize === 10 ? "selected" : ""}>10 条/页</option><option value="20" ${s.pageSize === 20 ? "selected" : ""}>20 条/页</option><option value="50" ${s.pageSize === 50 ? "selected" : ""}>50 条/页</option><option value="100" ${s.pageSize === 100 ? "selected" : ""}>100 条/页</option></select>
      <button class="pagination-nav" type="button" data-action="prev" aria-label="上一页" ${s.page <= 1 ? "disabled" : ""}><svg><use href="#i-left"/></svg></button>
      <div class="pagination-pages" aria-label="页码">${pageNumbers(s.page, totalPages).map((page) => `<button class="pagination-page-btn ${page === s.page ? "is-active" : ""}" type="button" data-page="${page}" ${page === s.page ? 'aria-current="page"' : ""}>${page}</button>`).join("")}</div>
      <button class="pagination-nav" type="button" data-action="next" aria-label="下一页" ${s.page >= totalPages ? "disabled" : ""}><svg><use href="#i-right"/></svg></button>
      <span class="pagination-page">第 ${s.page}/${totalPages} 页</span></div></div>`;
  }

  function tableShell(id) {
    return document.getElementById(id);
  }

  function beginTableLoad(id) {
    const shell = tableShell(id);
    if (!shell) return false;
    const hasTable = Boolean(shell.querySelector("table"));
    shell.classList.toggle("is-loading", hasTable);
    shell.setAttribute("aria-busy", "true");
    if (!hasTable) shell.innerHTML = '<div class="product-empty">正在读取配置…</div>';
    return hasTable;
  }

  function endTableLoad(id) {
    const shell = tableShell(id);
    if (!shell) return;
    shell.classList.remove("is-loading");
    shell.removeAttribute("aria-busy");
  }

  function actions(buttons) {
    const iconFor = (action) => {
      if (action.startsWith("edit-")) return "i-edit";
      if (action.startsWith("delete-")) return "i-trash";
      if (action.startsWith("enable-") || action.startsWith("disable-")) return "i-power";
      if (action.startsWith("save-")) return "i-check";
      return "i-check";
    };
    return `<div class="product-row-actions">${buttons.map(([action, label, kind = ""]) =>
      `<button type="button" class="icon-action table-action ${kind}" data-action="${action}"><svg><use href="#${iconFor(action)}"/></svg><span>${esc(label)}</span></button>`).join("")}</div>`;
  }

  function statusBadge(active, mappedLabel = false) {
    if (mappedLabel) return `<span class="status-chip ${active ? "" : "disabled"}">${active ? "已映射" : "未配置"}</span>`;
    return `<span class="status-chip ${active ? "" : "disabled"}">${active ? "启用" : "停用"}</span>`;
  }

  function ensureDialog() {
    let dialog = document.getElementById("masterEditorDialog");
    if (!dialog) {
      dialog = document.createElement("dialog");
      dialog.id = "masterEditorDialog";
      dialog.className = "product-dialog master-dialog";
      document.body.append(dialog);
    }
    return dialog;
  }

  function formDialog(title, fields, submitLabel = "保存") {
    const dialog = ensureDialog();
    return new Promise((resolve) => {
      dialog.innerHTML = `<form method="dialog"><div class="dialog-heading"><div><p>配置库维护</p><h3>${esc(title)}</h3></div><button type="submit" formnovalidate class="dialog-close" value="cancel" aria-label="关闭">×</button></div>
        <div class="product-form">${fields.map((field) => {
          const isRequired = field.required !== false;
          const required = isRequired ? "required" : "";
          const label = `${esc(field.label)}${isRequired ? ' <em>*</em>' : ""}`;
          const options = field.options ? field.options.map((option) => `<option value="${esc(option.value)}" ${String(option.value) === String(field.value ?? "") ? "selected" : ""}>${esc(option.label)}</option>`).join("") : "";
          if (field.type === "select") return `<label><span>${label}</span><select name="${esc(field.name)}" ${required}>${options}</select></label>`;
          if (field.type === "textarea") return `<label><span>${label}</span><textarea name="${esc(field.name)}" rows="3" ${required}>${esc(field.value ?? "")}</textarea></label>`;
          return `<label><span>${label}</span><input name="${esc(field.name)}" value="${esc(field.value ?? "")}" maxlength="${field.maxlength || 255}" ${required}></label>`;
        }).join("")}</div><div class="dialog-actions"><span class="dialog-spacer"></span><button type="submit" formnovalidate class="button" value="cancel">取消</button><button type="submit" class="button button-primary" value="submit">${esc(submitLabel)}</button></div></form>`;
      const form = dialog.querySelector("form");
      dialog.addEventListener("close", function onClose() {
        dialog.removeEventListener("close", onClose);
        if (dialog.returnValue !== "submit") return resolve(null);
        const payload = Object.fromEntries(new FormData(form).entries());
        resolve(payload);
      });
      dialog.showModal();
    });
  }

  async function fetchBaseProductData(needProducts) {
    const s = state.product;
    if (s.categoriesLoaded && (!needProducts || s.productsLoaded)) return;
    if (s.basePromise) {
      await s.basePromise;
      if (s.categoriesLoaded && (!needProducts || s.productsLoaded)) return;
    }
    s.basePromise = Promise.all([
      s.categoriesLoaded ? null : app().api("/api/product-categories"),
      !needProducts || s.productsLoaded ? null : app().api("/api/products?page=1&page_size=100&status=all"),
    ]).then(([categories, products]) => {
      if (categories) { s.categories = categories.categories || []; s.categoriesLoaded = true; }
      if (products) { s.products = products.rows || []; s.productsLoaded = true; }
    }).finally(() => { s.basePromise = null; });
    await s.basePromise;
  }

  function productLayout(view) {
    state.product.view = view;
    const rootId = ["mappings", "normalizations"].includes(view) ? "productMappingApp" : "productCategoryApp";
    ["productCategoryApp", "productMappingApp"].forEach((id) => {
      if (id !== rootId) document.getElementById(id).innerHTML = "";
    });
    const root = document.getElementById(rootId);
    const categoryTabs = ["products", "l1", "l2"].includes(view) ? `<nav class="catalog-subnav" aria-label="商品品类配置子页">
      <button class="catalog-subtab" data-product-view="products">公司商品</button>
      <button class="catalog-subtab" data-product-view="l1">一级分类</button>
      <button class="catalog-subtab" data-product-view="l2">二级分类</button>
    </nav>` : `<nav class="catalog-subnav" aria-label="商品编码映射子页">
      <button class="catalog-subtab" data-product-view="mappings">商品归属规则</button>
      <button class="catalog-subtab" data-product-view="normalizations">编码修正规则</button>
    </nav>`;
    root.innerHTML = `${categoryTabs}<div class="catalog-toolbar"><div class="catalog-filters">
      <label class="inline-field"><span>状态</span><select id="productStatus" class="select-chevron"><option value="all">全部状态</option><option value="active">启用</option><option value="inactive">停用</option><option value="mapped">已映射</option><option value="unmapped">未映射</option></select></label>
      <label class="inline-field" id="productPlatformField"><span>平台</span><select id="productPlatform" class="select-chevron">${platformOptions()}</select></label>
      <label class="product-search"><svg><use href="#i-search"/></svg><input id="productSearch" type="search" placeholder="搜索商品、分类或原始编码"></label>
      <button id="productQueryAction" class="button button-primary query-button" type="button"><svg><use href="#i-search"/></svg>查询</button><button id="productResetAction" class="button reset-button" type="button"><svg><use href="#i-refresh"/></svg>重置</button>
    </div><div class="catalog-actions"><button id="productPrimaryAction" class="button button-primary batch-toggle-button" type="button"><svg><use id="productPrimaryIcon" href="#i-plus"/></svg><span>新增公司商品</span></button></div></div>
    <div id="productRefreshNotice" class="product-refresh-notice" role="status" hidden></div>
    <section class="catalog-card"><div id="productMasterTable" class="product-table-shell"></div><div id="productMasterPager"></div></section>`;
    root.querySelectorAll("[data-product-view]").forEach((button) => button.addEventListener("click", () => {
      state.product.view = button.dataset.productView; state.product.page = 1; state.product.selected.clear(); state.product.batchMode = false; loadProduct();
    }));
    root.querySelector("#productQueryAction").addEventListener("click", () => {
      state.product.search = root.querySelector("#productSearch").value.trim();
      state.product.status = root.querySelector("#productStatus").value;
      state.product.platform = root.querySelector("#productPlatform").value;
      state.product.page = 1;
      loadProduct();
    });
    root.querySelector("#productResetAction").addEventListener("click", () => { state.product.search = ""; state.product.status = "all"; state.product.platform = ""; state.product.page = 1; root.querySelector("#productSearch").value = ""; loadProduct(); });
    root.querySelector("#productPrimaryAction").addEventListener("click", productPrimaryAction);
  }

  function setProductToolbar() {
    const s = state.product;
    document.querySelectorAll("[data-product-view]").forEach((button) => button.classList.toggle("is-active", button.dataset.productView === s.view));
    const action = document.getElementById("productPrimaryAction");
    const batchActive = false;
    const label = { products: "新增公司商品", mappings: "新增编码规则", normalizations: "新增修正规则", l1: "新增一级分类", l2: "新增二级分类" }[s.view];
    action.querySelector("span").textContent = label;
    action.classList.toggle("batch-mode-active", batchActive);
    document.getElementById("productPrimaryIcon")?.setAttribute("href", "#i-plus");
    document.getElementById("productPlatformField").hidden = s.view !== "mappings";
    [...document.getElementById("productStatus").options].forEach((option) => {
      option.hidden = s.view === "mappings"
        ? !["all", "mapped", "unmapped", "inactive"].includes(option.value)
        : s.view === "normalizations"
          ? !["all", "active", "inactive"].includes(option.value)
          : ["mapped", "unmapped"].includes(option.value);
    });
    if (!["mappings"].includes(s.view) && ["mapped", "unmapped"].includes(s.status)) s.status = "all";
    if (s.view === "mappings" && s.status === "active") s.status = "mapped";
    document.getElementById("productStatus").value = s.status;
    document.getElementById("productPlatform").value = s.platform;
    document.getElementById("productSearch").value = s.search;
  }

  async function loadProduct(preserveDraft = false) {
    const s = state.product;
    const requestedView = s.view;
    const requestVersion = ++s.requestVersion;
    s.selected.clear();
    closeAssignDropdown();
    if (preserveDraft !== true) setProductToolbar();
    const hadTable = beginTableLoad("productMasterTable");
    s.loading = true;
    try {
      const common = `search=${encodeURIComponent(s.search)}&page=${s.page}&page_size=${s.pageSize}`;
      let dataPromise;
      if (requestedView === "products") dataPromise = app().api(`/api/products?${common}&status=${s.status}`);
      else if (requestedView === "mappings") dataPromise = app().api(`/api/product-mappings?${common}&status=${s.status}&platform=${s.platform}`);
      else if (requestedView === "normalizations") dataPromise = app().api(`/api/product-code-normalizations?${common}&status=${s.status}`);
      else dataPromise = app().api(`/api/product-category-list?${common}&status=${s.status}&level=${requestedView === "l1" ? 1 : 2}`);
      // Mapping rows already contain their display fields. Load editor choices
      // on demand so DIM/other ADS refresh locks cannot delay the list itself.
      const data = ["mappings", "normalizations"].includes(requestedView)
        ? await dataPromise
        : (await Promise.all([fetchBaseProductData(false), dataPromise]))[1];
      if (requestVersion !== s.requestVersion || requestedView !== s.view) return;
      s.rows = data.rows || []; s.total = data.pagination?.total || 0; s.unmappedTotal = requestedView === "mappings" ? (data.pagination?.unmapped_total || 0) : 0; s.totalPages = data.pagination?.total_pages || 1;
      renderProductTable(requestedView, preserveDraft);
      if (requestedView === "mappings") {
        showProductRefresh(data.snapshot);
        if (data.snapshot?.pending && !data.snapshot.error) watchProductRefresh();
      } else if (productRefreshPending) {
        showProductRefresh({ pending: true });
        watchProductRefresh();
      }
    } catch (error) {
      if (!hadTable) document.getElementById("productMasterTable").innerHTML = `<div class="product-empty">${esc(error.message)}</div>`;
      app().toast(error.message, true);
    } finally {
      if (requestVersion === s.requestVersion) {
        s.loading = false;
        endTableLoad("productMasterTable");
      }
    }
  }

  function renderProductTable(renderedView = state.product.view, preserveDraft = false) {
    const s = state.product;
    const shell = document.getElementById("productMasterTable");
    if (!shell || renderedView !== s.view) return;
    if (!s.rows.length) shell.innerHTML = '<div class="product-empty">没有匹配的配置</div>';
    else if (renderedView === "products") shell.innerHTML = `<table class="product-config-table master-table"><thead><tr><th>公司商品编码</th><th>商品名称</th><th>分类</th><th>类型</th><th>规则</th><th>观察平台 / 店铺</th><th>付费数量</th><th>GMV</th><th>状态</th><th>操作</th></tr></thead><tbody>${s.rows.map((r, i) => `<tr data-index="${i}"><td><code>${esc(r.company_product_code)}</code></td><td><strong>${esc(r.product_name)}</strong></td><td>${esc(r.category_l1_name)}<span class="subtext">${esc(r.category_l2_name)}</span></td><td>${esc(({merchandise:"普通商品",non_product:"非商品",promotion:"营销特殊项"})[r.product_type] || r.product_type)}</td><td>${r.active_mapping_count}/${r.mapping_count}</td><td>${esc(r.observed_platform_names || "-")}<span class="subtext">${r.observed_shop_count || 0} 家店铺</span></td><td>${money.format(Number(r.paid_unit_count || 0))}</td><td class="money">¥${money.format(Number(r.gmv_amount || 0))}</td><td>${statusBadge(r.is_active)}</td><td>${actions([["edit-product", "编辑"], [r.is_active ? "disable-product" : "enable-product", r.is_active ? "停用" : "启用", r.is_active ? "warning" : "action-enable"], ["delete-product", "删除", "danger"]])}</td></tr>`).join("")}</tbody></table>`;
    else if (renderedView === "mappings") shell.innerHTML = `<table class="product-config-table master-table product-mapping-table"><thead><tr><th>编码表达 / 规则</th><th>实际观察编码</th><th>来源平台</th><th>店铺</th><th>付费 / 赠品数量</th><th>GMV</th><th>公司商品</th><th>状态</th><th>操作</th></tr></thead><tbody>${s.rows.map((r, i) => { const editable = r.mapping_id && r.mapping_kind !== "company_code"; const ruleActions = editable ? [["edit-mapping", "编辑"], [r.mapping_status === "inactive" ? "enable-mapping" : "disable-mapping", r.mapping_status === "inactive" ? "启用" : "停用", r.mapping_status === "inactive" ? "action-enable" : "warning"], ["delete-mapping", "删除", "danger"]] : r.mapping_kind === "company_code" ? [["edit-company-product", "维护商品"]] : []; return `<tr data-index="${i}"><td><code>${esc(r.source_product_code)}</code><span class="subtext">${esc(r.code_pattern)} · ${{suffix:"数量后缀",prefix:"数量前缀",none:"精确"}[r.quantity_position] || r.quantity_position}</span></td><td class="wrap-cell">${esc((r.observed_source_codes || []).join("、") || "尚未观察")}</td><td>${esc((r.observed_platform_names || []).join("、") || "-")}</td><td>${r.shop_count || 0}</td><td>${money.format(Number(r.paid_quantity || 0))} / ${money.format(Number(r.gift_quantity || 0))}</td><td class="money">¥${money.format(Number(r.gmv_amount || 0))}</td><td class="product-company-cell">${productCompanyPicker(r)}</td><td class="product-status-cell"><span class="status-chip ${r.mapping_status === "mapped" ? "" : "disabled"}">${({mapped:"已映射",unmapped:"未映射",inactive:"已停用"})[r.mapping_status] || r.mapping_status}</span></td><td>${ruleActions.length ? actions(ruleActions) : "-"}</td></tr>`; }).join("")}</tbody></table>`;
    else if (renderedView === "normalizations") shell.innerHTML = `<table class="product-config-table master-table"><thead><tr><th>原始异常组件</th><th>修正后组件</th><th>说明</th><th>状态</th><th>更新时间</th><th>操作</th></tr></thead><tbody>${s.rows.map((r, i) => `<tr data-index="${i}"><td><code>${esc(r.source_code_component)}</code></td><td class="wrap-cell"><code>${esc(r.normalized_code_expression)}</code></td><td class="wrap-cell">${esc(r.note || "-")}</td><td>${statusBadge(r.is_active)}</td><td>${dateText(r.updated_at)}</td><td>${actions([["edit-normalization", "编辑"], [r.is_active ? "disable-normalization" : "enable-normalization", r.is_active ? "停用" : "启用", r.is_active ? "warning" : "action-enable"], ["delete-normalization", "删除", "danger"]])}</td></tr>`).join("")}</tbody></table>`;
    else shell.innerHTML = `<table class="product-config-table master-table"><thead><tr>${s.view === "l2" ? "<th>一级分类</th>" : ""}<th>${s.view === "l1" ? "一" : "二"}级分类</th><th>关联数</th><th>状态</th><th>更新时间</th><th>操作</th></tr></thead><tbody>${s.rows.map((r, i) => `<tr data-index="${i}">${s.view === "l2" ? `<td>${esc(r.parent_category_name)}</td>` : ""}<td>${esc(r.category_name)}</td><td>${r.related_count}</td><td>${statusBadge(r.is_active)}</td><td>${dateText(r.updated_at)}</td><td>${actions([["edit-category", "编辑"], [r.is_active ? "disable-category" : "enable-category", r.is_active ? "停用" : "启用", r.is_active ? "warning" : "action-enable"], ["delete-category", "删除", "danger"]])}</td></tr>`).join("")}</tbody></table>`;
    shell.querySelectorAll("[data-action]").forEach((element) => element.addEventListener("click", productTableAction));
    shell.querySelectorAll("[data-product-assign-trigger]").forEach((button) => {
      button.addEventListener("mousedown", (event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        event.stopPropagation();
        openProductAssignDropdown(button);
      });
      button.addEventListener("click", (event) => {
        if (event.detail !== 0) return;
        event.stopPropagation();
        openProductAssignDropdown(button);
      });
    });
    ensurePager("product", loadProduct);
    if (preserveDraft !== true) setProductToolbar();
  }

  function pagerRoot(scope) {
    return document.getElementById(scope === "product" ? "productMasterPager" : "influencerMasterPager");
  }

  function bindPagerPages(scope, loader) {
    const root = pagerRoot(scope);
    if (!root) return;
    root.querySelectorAll("[data-page]").forEach((button) => {
      button.onclick = () => {
        const s = state[scope];
        if (s.loading) return;
        const page = Number(button.dataset.page);
        if (page === s.page) return;
        s.page = page;
        loader();
      };
    });
  }

  function bindPager(scope, loader) {
    const root = pagerRoot(scope); if (!root) return;
    if (root.dataset.bound === "true") {
      bindPagerPages(scope, loader);
      return;
    }
    root.dataset.bound = "true";
    root.querySelector('[data-action="page-size"]')?.addEventListener("change", (e) => {
      if (state[scope].loading) return;
      state[scope].pageSize = Number(e.target.value); state[scope].page = 1; loader();
    });
    root.querySelector('[data-action="prev"]')?.addEventListener("click", () => {
      if (state[scope].loading || state[scope].page <= 1) return;
      state[scope].page -= 1; loader();
    });
    root.querySelector('[data-action="next"]')?.addEventListener("click", () => {
      if (state[scope].loading || state[scope].page >= state[scope].totalPages) return;
      state[scope].page += 1; loader();
    });
    bindPagerPages(scope, loader);
  }

  function syncPager(scope, loader) {
    const root = pagerRoot(scope);
    if (!root?.querySelector(".pagination-controls")) return;
    const s = state[scope];
    const totalPages = Math.max(1, s.totalPages || 1);
    const summary = root.querySelector(".pagination-summary");
    if (summary) summary.textContent = paginationSummary(scope);
    const size = root.querySelector('[data-action="page-size"]');
    if (size && size.value !== String(s.pageSize)) size.value = String(s.pageSize);
    const previous = root.querySelector('[data-action="prev"]');
    const next = root.querySelector('[data-action="next"]');
    if (previous) previous.disabled = s.page <= 1;
    if (next) next.disabled = s.page >= totalPages;
    const pages = root.querySelector(".pagination-pages");
    const pageSet = pageNumbers(s.page, totalPages).join(",");
    if (pages && pages.dataset.pageSet !== pageSet) {
      pages.innerHTML = pageNumbers(s.page, totalPages).map((page) => `<button class="pagination-page-btn ${page === s.page ? "is-active" : ""}" type="button" data-page="${page}" ${page === s.page ? 'aria-current="page"' : ""}>${page}</button>`).join("");
      pages.dataset.pageSet = pageSet;
    }
    pages?.querySelectorAll("[data-page]").forEach((button) => {
      const active = Number(button.dataset.page) === s.page;
      button.classList.toggle("is-active", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    const pageLabel = root.querySelector(".pagination-page");
    if (pageLabel) pageLabel.textContent = `第 ${s.page}/${totalPages} 页`;
    bindPagerPages(scope, loader);
  }

  function ensurePager(scope, loader) {
    const root = pagerRoot(scope);
    if (!root) return;
    if (!root.querySelector(".pagination-controls")) {
      root.innerHTML = pager(scope);
      root.dataset.bound = "";
      bindPager(scope, loader);
    } else {
      bindPager(scope, loader);
    }
    syncPager(scope, loader);
  }

  const l2Options = () => state.product.categories.filter((c) => Number(c.category_level) === 2 && c.is_active).map((c) => ({ value: c.category_id, label: `${c.parent_category_name ? `${c.parent_category_name} / ` : ""}${c.category_name}` }));
  const productOptions = () => state.product.products.filter((p) => p.is_active).map((p) => ({ value: p.product_id, label: `${p.product_name} (${p.company_product_code})` }));
  const l1Options = () => state.product.categories.filter((c) => Number(c.category_level) === 1 && c.is_active).map((c) => ({ value: c.category_id, label: c.category_name }));

  async function productPrimaryAction() {
    const s = state.product;
    try {
      if (s.view === "products") {
        const data = await formDialog("新增公司商品", [
          { name: "company_product_code", label: "公司商品编码", maxlength: 128 },
          { name: "product_name", label: "商品名称" },
          { name: "category_id", label: "二级分类", type: "select", options: l2Options() },
          { name: "product_type", label: "商品类型", type: "select", value: "merchandise", options: [{value:"merchandise",label:"普通商品"},{value:"non_product",label:"非商品"},{value:"promotion",label:"营销特殊项"}] },
        ]);
        if (!data) return app().toast("已取消新增商品操作");
        await app().api("/api/products", { method: "POST", body: JSON.stringify(data) });
        s.productsLoaded = false;
      } else if (s.view === "mappings") {
        const data = await mappingForm();
        if (!data) return app().toast("已取消新增编码映射");
        await app().api("/api/product-mappings", { method: "POST", body: JSON.stringify(data) });
      } else if (s.view === "normalizations") {
        const data = await normalizationForm();
        if (!data) return app().toast("已取消新增编码修正规则");
        await app().api("/api/product-code-normalizations", { method: "POST", body: JSON.stringify(data) });
      } else {
        const fields = [{ name: "category_name", label: `${s.view === "l1" ? "一" : "二"}级分类名称` }];
        if (s.view === "l2") fields.push({ name: "parent_category_id", label: "所属一级分类", type: "select", options: l1Options() });
        const data = await formDialog(`新增${s.view === "l1" ? "一" : "二"}级分类`, fields);
        if (!data) return app().toast(`已取消新增${s.view === "l1" ? "一级" : "二级"}分类`);
        await app().api("/api/product-categories", { method: "POST", body: JSON.stringify({ ...data, category_level: s.view === "l1" ? 1 : 2 }) });
        s.categoriesLoaded = false;
      }
      app().toast("保存成功"); await loadProduct();
    } catch (error) { app().toast(error.message, true); }
  }

  async function mappingForm(row = {}) {
    await fetchBaseProductData(true);
    return formDialog(row.mapping_id ? "编辑编码映射" : "新增编码映射", [
      { name: "source_product_code", label: "去数量编码表达", value: row.source_product_code, maxlength: 128 },
      { name: "quantity_position", label: "数量位置", type: "select", value: row.quantity_position || "suffix", options: [{value:"suffix",label:"后缀，如 M-MGNT-2"},{value:"prefix",label:"前缀，如 2MG"},{value:"none",label:"无数量，精确匹配"}] },
      { name: "product_id", label: "公司商品", type: "select", value: row.product_id, options: productOptions() },
    ]);
  }

  async function productTableAction(event) {
    const action = event.currentTarget.dataset.action;
    const row = state.product.rows[Number(event.currentTarget.closest("tr").dataset.index)];
    try {
      let successMessage = "操作成功";
      if (action === "edit-company-product") {
        await fetchBaseProductData(true);
        const product = state.product.products.find((item) => item.product_id === row.current_product_id);
        if (!product) throw new Error("未找到对应公司商品，请刷新后重试");
        const data = await formDialog("维护公司商品", [
          { name: "company_product_code", label: "公司商品编码", value: product.company_product_code, maxlength: 128 },
          { name: "product_name", label: "商品名称", value: product.product_name },
          { name: "category_id", label: "二级分类", type: "select", value: product.category_id, options: l2Options() },
          { name: "product_type", label: "商品类型", type: "select", value: product.product_type, options: [{value:"merchandise",label:"普通商品"},{value:"non_product",label:"非商品"},{value:"promotion",label:"营销特殊项"}] },
        ]);
        if (!data) return app().toast("已取消编辑");
        await app().api(`/api/products/${encodeURIComponent(product.product_id)}`, { method: "PUT", body: JSON.stringify(data) });
        state.product.productsLoaded = false;
        successMessage = "公司商品已保存";
      } else if (action === "edit-product") {
        const data = await formDialog("编辑公司商品", [
          { name: "company_product_code", label: "公司商品编码", value: row.company_product_code, maxlength: 128 },
          { name: "product_name", label: "商品名称", value: row.product_name },
          { name: "category_id", label: "二级分类", type: "select", value: row.category_id, options: l2Options() },
          { name: "product_type", label: "商品类型", type: "select", value: row.product_type, options: [{value:"merchandise",label:"普通商品"},{value:"non_product",label:"非商品"},{value:"promotion",label:"营销特殊项"}] },
        ]);
        if (!data) return app().toast("已取消编辑");
        await app().api(`/api/products/${encodeURIComponent(row.product_id)}`, { method: "PUT", body: JSON.stringify(data) });
        state.product.productsLoaded = false;
        successMessage = "保存成功";
      } else if (action.endsWith("product")) {
        if (action === "delete-product") {
          if (!confirm("确定删除该公司商品？")) return;
          await app().api(`/api/products/${encodeURIComponent(row.product_id)}`, { method: "DELETE" });
          state.product.productsLoaded = false;
          successMessage = `${row.product_name || "公司商品"}已删除`;
        } else {
          const enabled = action === "enable-product";
          await app().api(`/api/products/${encodeURIComponent(row.product_id)}/status`, { method: "PUT", body: JSON.stringify({ is_active: enabled }) });
          state.product.productsLoaded = false;
          successMessage = `${row.product_name || "公司商品"}已${enabled ? "启用" : "停用"}`;
        }
      } else if (action === "edit-mapping") {
        const data = await mappingForm(row);
        if (!data) return app().toast("已取消编辑");
        await app().api(`/api/product-mappings/${row.mapping_id}`, { method: "PUT", body: JSON.stringify(data) });
        successMessage = "保存成功";
      } else if (action.endsWith("mapping")) {
        const mappingName = row.source_product_code || "编码映射";
        if (action === "delete-mapping") {
          if (!confirm("确定删除该编码映射？")) return;
          await app().api(`/api/product-mappings/${row.mapping_id}`, { method: "DELETE" });
          successMessage = `${mappingName}已删除`;
        } else {
          const enabled = action === "enable-mapping";
          await app().api(`/api/product-mappings/${row.mapping_id}/status`, { method: "PUT", body: JSON.stringify({ is_active: enabled }) });
          successMessage = `${mappingName}已${enabled ? "启用" : "停用"}`;
        }
      } else if (action === "edit-normalization") {
        const data = await normalizationForm(row);
        if (!data) return app().toast("已取消编辑");
        await app().api(`/api/product-code-normalizations/${row.normalization_rule_id}`, { method: "PUT", body: JSON.stringify(data) });
        successMessage = "编码修正规则已保存";
      } else if (action.endsWith("normalization")) {
        if (action === "delete-normalization") {
          if (!confirm("确定删除该编码修正规则？")) return;
          await app().api(`/api/product-code-normalizations/${row.normalization_rule_id}`, { method: "DELETE" });
          successMessage = "编码修正规则已删除";
        } else {
          const enabled = action === "enable-normalization";
          await app().api(`/api/product-code-normalizations/${row.normalization_rule_id}/status`, { method: "PUT", body: JSON.stringify({ is_active: enabled }) });
          successMessage = `编码修正规则已${enabled ? "启用" : "停用"}`;
        }
      } else if (action === "edit-category") {
        const fields = [{ name: "category_name", label: "分类名称", value: row.category_name }];
        if (Number(row.category_level) === 2) fields.push({ name: "parent_category_id", label: "所属一级分类", type: "select", value: row.parent_category_id, options: l1Options() });
        const data = await formDialog("编辑分类", fields);
        if (!data) return app().toast("已取消编辑");
        await app().api(`/api/product-categories/${row.category_id}`, { method: "PUT", body: JSON.stringify(data) });
        state.product.categoriesLoaded = false;
        successMessage = "保存成功";
      } else if (action.endsWith("category")) {
        const categoryName = row.category_name || "分类";
        if (action === "delete-category") {
          if (!confirm("确定删除该分类？")) return;
          await app().api(`/api/product-categories/${row.category_id}`, { method: "DELETE" });
          state.product.categoriesLoaded = false;
          successMessage = `${categoryName}已删除`;
        } else {
          const enabled = action === "enable-category";
          await app().api(`/api/product-categories/${row.category_id}/status`, { method: "PUT", body: JSON.stringify({ is_active: enabled }) });
          state.product.categoriesLoaded = false;
          successMessage = `${categoryName}已${enabled ? "启用" : "停用"}`;
        }
      }
      app().toast(successMessage); await loadProduct();
    } catch (error) { app().toast(error.message, true); }
  }

  function influencerLayout() {
    const root = document.getElementById("influencerMasterApp");
    root.innerHTML = `<nav class="catalog-subnav"><button class="catalog-subtab" data-view="company">公司达人库</button><button class="catalog-subtab" data-view="source">平台达人映射</button><button class="catalog-subtab" data-view="assignment">商务归属</button></nav>
      <div class="catalog-toolbar"><div class="catalog-filters"><label class="inline-field" id="influencerStatusField"><span>状态</span><select id="influencerStatus" class="select-chevron"><option value="all">全部状态</option><option value="active">启用</option><option value="inactive">停用</option><option value="mapped">已映射</option><option value="unmapped">未映射</option></select></label><label class="inline-field" id="influencerPlatformField"><span>平台</span><select id="influencerPlatform" class="select-chevron">${platformOptions()}</select></label><label class="inline-field" id="influencerBusinessField" hidden><span>商务</span><select id="influencerBusiness" class="select-chevron"><option value="">全部商务</option></select></label><label class="inline-field" id="influencerGmvFilterField" hidden><span>GMV</span><select id="influencerGmvFilter" class="select-chevron"><option value="">全部GMV</option><option value="0.01">GMV &gt; 0</option><option value="10000">GMV ≥ 1万</option><option value="100000">GMV ≥ 10万</option></select></label><label class="product-search"><svg><use href="#i-search"/></svg><input id="influencerSearch" type="search" placeholder="搜索公司达人名称或ID"></label><button id="influencerQueryAction" class="button button-primary query-button" type="button"><svg><use href="#i-search"/></svg>查询</button><button id="influencerResetAction" class="button reset-button" type="button"><svg><use href="#i-refresh"/></svg>重置</button></div><div class="catalog-actions"><button id="influencerPrimaryAction" class="button button-primary batch-toggle-button" type="button"><svg><use id="influencerPrimaryIcon" href="#i-plus"/></svg><span>新增公司达人</span></button></div></div>
      <section class="catalog-card"><div id="influencerMasterTable" class="product-table-shell"></div><div id="influencerMasterPager"></div></section>`;
    root.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => { state.influencer.view = button.dataset.view; state.influencer.page = 1; state.influencer.selected.clear(); state.influencer.batchMode = false; loadInfluencer(); }));
    root.querySelector("#influencerQueryAction").addEventListener("click", () => {
      state.influencer.search = root.querySelector("#influencerSearch").value.trim();
      state.influencer.status = root.querySelector("#influencerStatus").value;
      state.influencer.platform = root.querySelector("#influencerPlatform").value;
      state.influencer.business = root.querySelector("#influencerBusiness").value;
      state.influencer.gmvMin = root.querySelector("#influencerGmvFilter").value;
      state.influencer.page = 1;
      loadInfluencer();
    });
    root.querySelector("#influencerResetAction").addEventListener("click", () => { state.influencer.search = ""; state.influencer.status = "all"; state.influencer.platform = ""; state.influencer.business = ""; state.influencer.gmvMin = ""; state.influencer.page = 1; root.querySelector("#influencerSearch").value = ""; loadInfluencer(); });
    root.querySelector("#influencerPrimaryAction").addEventListener("click", influencerPrimaryAction);
    bindInfluencerAssignDropdown();
  }

  function renderInfluencerBusinessFilter() {
    const filter = document.getElementById("influencerBusiness");
    if (!filter) return;
    const current = state.influencer.business;
    filter.innerHTML = `<option value="">全部商务</option>${state.influencer.businesses.filter((b) => b.is_active !== false).map((b) => `<option value="${esc(b.business_owner_id)}">${esc(b.business_owner_name)}</option>`).join("")}`;
    filter.value = current;
  }

  function setInfluencerToolbar() {
    const s = state.influencer;
    document.querySelectorAll("#influencerMasterApp [data-view]").forEach((b) => b.classList.toggle("is-active", b.dataset.view === s.view));
    document.getElementById("influencerPlatformField").hidden = !["company", "source", "assignment"].includes(s.view);
    document.getElementById("influencerBusinessField").hidden = s.view !== "assignment";
    document.getElementById("influencerGmvFilterField").hidden = s.view !== "source";
    document.getElementById("influencerStatusField").hidden = s.view === "assignment";
    [...document.getElementById("influencerStatus").options].forEach((o) => {
      o.hidden = s.view === "source"
        ? !["all", "mapped", "unmapped"].includes(o.value)
        : ["mapped", "unmapped"].includes(o.value);
    });
    if (s.view !== "source" && ["mapped", "unmapped"].includes(s.status)) s.status = "all";
    document.getElementById("influencerStatus").value = s.status;
    document.getElementById("influencerPlatform").value = s.platform;
    document.getElementById("influencerBusiness").value = s.business;
    document.getElementById("influencerGmvFilter").value = s.gmvMin;
    document.getElementById("influencerSearch").value = s.search;
    document.getElementById("influencerSearch").placeholder = s.view === "source" ? "搜索平台达人名称或UID" : s.view === "assignment" ? "搜索达人名称 / 商务 / 公司达人ID" : "搜索公司达人名称或ID";
    const batchActive = s.view === "source" && s.batchMode;
    const action = document.getElementById("influencerPrimaryAction");
    action.querySelector("span").textContent = s.view === "company" ? "新增公司达人" : s.view === "source" ? (batchActive ? `关闭批量勾选${s.selected.size ? ` (${s.selected.size})` : ""}` : "开启批量勾选") : "刷新归属";
    action.classList.toggle("batch-mode-active", batchActive);
    document.getElementById("influencerPrimaryIcon").setAttribute("href", s.view === "assignment" ? "#i-refresh" : s.view === "source" ? (batchActive ? "#i-x-square" : "#i-check-square") : "#i-plus");
  }

  async function loadInfluencer() {
    const s = state.influencer; s.selected.clear(); closeInfluencerAssignDropdown(); setInfluencerToolbar();
    const hadTable = beginTableLoad("influencerMasterTable");
    s.loading = true;
    try {
      const [companies, businesses] = await Promise.all([app().api("/api/company-influencers?page=1&page_size=100&status=active"), app().api("/api/businesses")]);
      s.companies = companies.rows || []; s.businesses = businesses || []; renderInfluencerBusinessFilter();
      const common = `search=${encodeURIComponent(s.search)}&page=${s.page}&page_size=${s.pageSize}`;
      let data;
      if (s.view === "company") data = await app().api(`/api/company-influencers?${common}&status=${s.status}&platform=${encodeURIComponent(s.platform)}`);
      else if (s.view === "source") data = await app().api(`/api/influencer-source-accounts?${common}&mapping_status=${s.status}&platform=${encodeURIComponent(s.platform)}&gmv_min=${encodeURIComponent(s.gmvMin)}`);
      else data = await app().api(`/api/company-influencer-assignments?${common}&month=${encodeURIComponent(document.getElementById("globalMonth").value)}&business_owner_id=${encodeURIComponent(s.business)}&platform=${encodeURIComponent(s.platform)}`);
      s.rows = data.rows || []; s.total = data.pagination?.total || 0; s.unmappedTotal = s.view === "source" ? (data.pagination?.unmapped_total || 0) : 0; s.totalPages = data.pagination?.total_pages || 1; renderInfluencerTable();
    } catch (error) {
      if (!hadTable) document.getElementById("influencerMasterTable").innerHTML = `<div class="product-empty">${esc(error.message)}</div>`;
      app().toast(error.message, true);
    } finally {
      s.loading = false;
      endTableLoad("influencerMasterTable");
    }
  }

  function influencerCompanyPicker(row) {
    const companyName = row.mapping_active ? (row.company_influencer_name || "") : "";
    return `<div class="assign-combobox influencer-assign-combobox"><button type="button" class="assign-trigger influencer-assign-trigger" role="combobox" aria-expanded="false" aria-controls="assignDropdown" aria-label="选择公司达人" title="${esc(companyName || "未映射")}" data-influencer-assign-trigger data-value="${esc(row.company_influencer_id || "")}" data-name="${esc(companyName)}"><span class="assign-value ${companyName ? "" : "empty"}">${esc(companyName || "未映射")}</span><svg><use href="#i-down"/></svg></button></div>`;
  }

  function productCompanyPicker(row) {
    const productName = row.current_product_id ? (row.product_name || "") : "";
    const displayName = productName || "未配置";
    if (row.mapping_kind === "company_code") return `<div class="product-company-display" title="${esc(`${displayName} (${row.company_product_code || ""})`)}"><strong>${esc(displayName)}</strong><span class="subtext">${esc(row.company_product_code || "")}</span></div>`;
    return `<div class="assign-combobox product-assign-combobox"><button type="button" class="assign-trigger product-assign-trigger" role="combobox" aria-expanded="false" aria-controls="assignDropdown" aria-label="选择公司商品" title="${esc(displayName)}" data-product-assign-trigger data-value="${esc(row.current_product_id || "")}" data-name="${esc(productName)}"><span class="assign-value ${productName ? "" : "empty"}">${esc(displayName)}</span><svg><use href="#i-down"/></svg></button></div>`;
  }

  async function normalizationForm(row = {}) {
    return formDialog(row.normalization_rule_id ? "编辑编码修正规则" : "新增编码修正规则", [
      { name: "source_code_component", label: "原始异常组件", value: row.source_code_component, maxlength: 512 },
      { name: "normalized_code_expression", label: "修正后组件（多个用 + 分隔）", value: row.normalized_code_expression, maxlength: 1024 },
      { name: "note", label: "规则说明", type: "textarea", required: false, value: row.note },
    ]);
  }

  function renderInfluencerTable() {
    const s = state.influencer, shell = document.getElementById("influencerMasterTable");
    if (!s.rows.length) shell.innerHTML = '<div class="product-empty">配置库中没有匹配记录</div>';
    else if (s.view === "company") shell.innerHTML = `<table class="master-table"><thead><tr><th>公司达人ID</th><th>公司达人</th><th>平台</th><th>账号数</th><th>备注</th><th>状态</th><th>操作</th></tr></thead><tbody>${s.rows.map((r, i) => `<tr data-index="${i}"><td class="money">${esc(r.company_influencer_id)}</td><td><strong>${esc(r.company_influencer_name)}</strong></td><td>${esc(platformText(r.platforms))}</td><td>${r.active_source_account_count}/${r.source_account_count}</td><td>${esc(r.note || "-")}</td><td>${statusBadge(r.is_active)}</td><td>${actions([["edit-company", "编辑"], [r.is_active ? "disable-company" : "enable-company", r.is_active ? "停用" : "启用", r.is_active ? "warning" : "action-enable"], ["delete-company", "删除", "danger"]])}</td></tr>`).join("")}</tbody></table>`;
    else if (s.view === "source") {
      const allSelected = s.rows.length > 0 && s.rows.every((r) => s.selected.has(`${r.platform_code}|${r.source_influencer_id}`));
      shell.innerHTML = `<table class="master-table${s.batchMode ? " batch-selection-mode" : ""}"><thead><tr><th class="master-selection-col"><input type="checkbox" data-action="select-all-source" aria-label="全选平台达人" ${allSelected ? "checked" : ""}></th><th>平台</th><th>平台达人</th><th>UID</th><th>店铺</th><th>GMV</th><th>公司达人</th><th>状态</th><th>操作</th></tr></thead><tbody>${s.rows.map((r, i) => { const key = `${r.platform_code}|${r.source_influencer_id}`; return `<tr data-index="${i}" class="${s.selected.has(key) ? "is-selected" : ""}"><td class="master-selection-col"><input type="checkbox" data-action="select-source-account" data-key="${esc(key)}" aria-label="选择${esc(r.source_influencer_name)}" ${s.selected.has(key) ? "checked" : ""}></td><td>${esc(platformNames[r.platform_code] || r.platform_code)}</td><td>${esc(r.source_influencer_name)}</td><td><code>${esc(r.source_influencer_id)}</code></td><td class="wrap-cell">${esc(r.shop_names || "-")}</td><td class="money">¥${money.format(Number(r.gmv_amount || 0))}</td><td class="influencer-company-cell">${influencerCompanyPicker(r)}</td><td class="influencer-status-cell">${statusBadge(r.mapping_status === "mapped", true)}</td><td>${r.mapping_id ? actions([[r.mapping_active ? "disable-source-map" : "enable-source-map", r.mapping_active ? "停用" : "启用", r.mapping_active ? "warning" : "action-enable"], ["delete-source-map", "删除", "danger"]]) : "-"}</td></tr>`; }).join("")}</tbody></table>`;
    }
    else shell.innerHTML = `<table class="master-table"><thead><tr><th>公司达人ID</th><th>公司达人</th><th>平台账号</th><th>当前商务</th><th>生效月</th><th>备注</th><th>操作</th></tr></thead><tbody>${s.rows.map((r, i) => `<tr data-index="${i}"><td class="money">${esc(r.company_influencer_id)}</td><td>${esc(r.company_influencer_name)}</td><td>${r.source_account_count}</td><td><select class="select-chevron assignment-owner">${[{ business_owner_id: "", business_owner_name: "未分配" }, ...s.businesses].map((b) => `<option value="${b.business_owner_id}" ${String(b.business_owner_id) === String(r.business_owner_id || "") ? "selected" : ""}>${esc(b.business_owner_name)}</option>`).join("")}</select></td><td>${dateText(r.effective_month)}</td><td><input class="inline-note" value="${esc(r.note || "")}" maxlength="1000"></td><td>${actions([["save-assignment", "保存"], ["delete-assignment", "删除", "danger"]])}</td></tr>`).join("")}</tbody></table>`;
    shell.querySelectorAll("[data-action]").forEach((el) => el.addEventListener("click", influencerTableAction));
    shell.querySelectorAll("[data-influencer-assign-trigger]").forEach((button) => button.addEventListener("click", (event) => { event.stopPropagation(); openInfluencerAssignDropdown(button); }));
    if (s.view === "source") shell.querySelectorAll("tbody tr[data-index]").forEach((row) => row.addEventListener("click", (event) => {
      if (!state.influencer.batchMode || event.target.closest("button,input,select,textarea,a,.row-actions,.assign-combobox,[data-action]")) return;
      const source = state.influencer.rows[Number(row.dataset.index)];
      if (!source) return;
      const key = `${source.platform_code}|${source.source_influencer_id}`;
      if (state.influencer.selected.has(key)) state.influencer.selected.delete(key);
      else state.influencer.selected.set(key, { platform_code: source.platform_code, source_influencer_id: source.source_influencer_id, source_influencer_name: source.source_influencer_name });
      renderInfluencerTable();
    }));
    ensurePager("influencer", loadInfluencer);
    setInfluencerToolbar();
  }

  function renderAssignOptions(query = "") {
    const context = assignContext;
    const options = document.getElementById("assignOptions");
    if (!context || !options) return;
    const keyword = query.trim().toLowerCase();
    const isProduct = context.kind === "product";
    const items = (isProduct ? state.product.products : state.influencer.companies)
      .filter((item) => item.is_active !== false)
      .map((item) => isProduct
        ? { id: String(item.product_id), name: `${item.product_name || "公司商品"} (${item.company_product_code || "未设置编码"})`, item }
        : { id: String(item.company_influencer_id), name: String(item.company_influencer_name || ""), item })
      .filter((item) => {
        const name = item.name.toLowerCase();
        return !keyword || name.includes(keyword) || item.id.toLowerCase().includes(keyword);
      });
    const valueAttribute = isProduct ? "data-assign-product-id" : "data-assign-company-id";
    options.innerHTML = items.length
      ? items.map((item) => {
        const active = String(context.trigger.dataset.value || "") === item.id;
        return `<button type="button" class="assign-option ${active ? "active" : ""}" title="${esc(item.name)}" ${valueAttribute}="${esc(item.id)}"><span>${esc(item.name)}</span></button>`;
      }).join("")
      : `<div class="assign-empty">${keyword ? (isProduct ? "未找到匹配的公司商品" : "未找到匹配的公司达人") : (isProduct ? "暂无可用公司商品" : "暂无可用公司达人")}</div>`;
    options.querySelectorAll("[data-assign-company-id], [data-assign-product-id]").forEach((button) => {
      button.addEventListener("mousedown", (event) => event.preventDefault());
      button.addEventListener("click", () => {
        const currentContext = assignContext;
        const row = currentContext?.trigger.closest("tr");
        const rows = currentContext?.kind === "product" ? state.product.rows : state.influencer.rows;
        const rowData = row ? rows[Number(row.dataset.index)] : null;
        const selectedId = button.dataset.assignProductId || button.dataset.assignCompanyId;
        const selectedItems = currentContext?.kind === "product" ? state.product.products : state.influencer.companies;
        const item = selectedItems.find((candidate) => String(currentContext.kind === "product" ? candidate.product_id : candidate.company_influencer_id) === selectedId);
        closeAssignDropdown();
        if (!rowData || !item) return;
        if (currentContext.kind === "product") {
          const rowKey = `${rowData.quantity_position}|${rowData.source_product_code}`;
          if (state.product.selected.size === 1 && state.product.selected.has(rowKey) && String(rowData.current_product_id || "") === selectedId && rowData.mapping_status === "mapped") return;
          saveSingleProductMapping(rowData, item).catch((error) => app().toast(error.message, true));
          return;
        }
        const rowKey = `${rowData.platform_code}|${rowData.source_influencer_id}`;
        if (state.influencer.selected.size === 1 && state.influencer.selected.has(rowKey) && String(rowData.company_influencer_id || "") === selectedId && rowData.mapping_active) return;
        saveSingleInfluencerMapping(rowData, item).catch((error) => app().toast(error.message, true));
      });
    });
  }

  function renderInfluencerAssignOptions(query = "") {
    renderAssignOptions(query);
  }

  function placeAssignDropdown(dropdown, trigger) {
    const rect = trigger.getBoundingClientRect();
    const width = Math.min(250, window.innerWidth - 16);
    const height = dropdown.offsetHeight || 286;
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8));
    const below = rect.bottom + 6;
    const top = below + height <= window.innerHeight - 8 ? below : Math.max(8, rect.top - height - 6);
    dropdown.style.width = `${width}px`;
    dropdown.style.left = `${left}px`;
    dropdown.style.top = `${top}px`;
  }

  function placeInfluencerAssignDropdown(dropdown, trigger) {
    placeAssignDropdown(dropdown, trigger);
  }

  function openAssignDropdown(trigger, kind) {
    if (assignContext?.trigger === trigger) {
      closeAssignDropdown();
      return;
    }
    closeAssignDropdown();
    const dropdown = document.getElementById("assignDropdown");
    const search = document.getElementById("assignSearch");
    if (!dropdown || !search) return;
    assignContext = { trigger, kind };
    trigger.setAttribute("aria-expanded", "true");
    search.value = "";
    search.placeholder = kind === "product" ? "查找公司商品" : "查找公司达人";
    dropdown.hidden = false;
    renderAssignOptions();
    placeAssignDropdown(dropdown, trigger);
    setTimeout(() => {
      if (assignContext?.trigger === trigger) search.focus();
    }, 0);
  }

  function openInfluencerAssignDropdown(trigger) {
    openAssignDropdown(trigger, "influencer");
  }

  async function openProductAssignDropdown(trigger) {
    if (trigger.disabled) return;
    trigger.disabled = true;
    trigger.setAttribute("aria-busy", "true");
    try {
      await fetchBaseProductData(true);
      if (trigger.isConnected) openAssignDropdown(trigger, "product");
    } catch (error) { app().toast(error.message, true); }
    finally { trigger.disabled = false; trigger.removeAttribute("aria-busy"); }
  }

  function closeAssignDropdown() {
    const context = assignContext;
    const dropdown = document.getElementById("assignDropdown");
    context?.trigger?.setAttribute("aria-expanded", "false");
    if (dropdown) {
      dropdown.hidden = true;
      ["left", "top", "width"].forEach((property) => dropdown.style.removeProperty(property));
    }
    assignContext = null;
  }

  function closeInfluencerAssignDropdown() {
    closeAssignDropdown();
  }

  function bindInfluencerAssignDropdown() {
    const search = document.getElementById("assignSearch");
    const dropdown = document.getElementById("assignDropdown");
    if (!search || !dropdown) return;
    search.addEventListener("input", (event) => renderAssignOptions(event.target.value));
    search.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeAssignDropdown();
    });
    document.addEventListener("mousedown", (event) => {
      if (assignContext && !dropdown.contains(event.target) && !assignContext.trigger.contains(event.target)) closeAssignDropdown();
    });
    const reposition = () => {
      if (assignContext && !dropdown.hidden) placeAssignDropdown(dropdown, assignContext.trigger);
    };
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
  }

  async function saveSingleProductMapping(row, product) {
    const sourceName = row.source_product_code || "编码表达";
    const targetName = product.product_name || `公司商品 ${product.product_id}`;
    const s = state.product;
    const items = s.selected.size ? [...s.selected.values()] : [{
      source_product_code: row.source_product_code,
      quantity_position: row.quantity_position,
    }];
    const body = {
      product_id: product.product_id,
      items,
    };
    const apply = async () => {
      try {
        await app().api("/api/product-mappings/batch", { method: "POST", body: JSON.stringify(body) });
      } catch (error) {
        if (!error.details?.conflicts || !confirm(`${error.message}\n确定将「${sourceName}」映射到「${targetName}」吗？`)) return;
        await app().api("/api/product-mappings/batch", {
          method: "POST",
          body: JSON.stringify({ ...body, confirm_replace: true }),
        });
      }
      s.selected.clear();
      app().toast(items.length > 1 ? `批量映射成功，共 ${items.length} 条` : `已将「${sourceName}」映射到「${targetName}」`);
      await loadProduct();
    };
    if (items.length > 1) {
      showTablePopover("batch-confirm", `<div class="popover-message"><span class="popover-icon warning">!</span><div class="popover-copy"><p>已选中 <em>${items.length}</em> 行，确认批量修改公司商品为「<em class="highlight">${esc(targetName)}</em>」？</p></div></div><div class="popover-actions"><button class="mini-button" data-popover-cancel>取消</button><button class="mini-button primary" data-popover-confirm>确定修改</button></div>`, apply);
      return;
    }
    await apply();
  }
  async function saveSingleInfluencerMapping(row, company) {
    const sourceName = row.source_influencer_name || row.source_influencer_id || "平台达人";
    const targetName = company.company_influencer_name || `公司达人 ${company.company_influencer_id}`;
    const s = state.influencer;
    const items = s.selected.size ? [...s.selected.values()] : [{
      platform_code: row.platform_code,
      source_influencer_id: row.source_influencer_id,
      source_influencer_name: row.source_influencer_name,
    }];
    const body = {
      company_influencer_id: company.company_influencer_id,
      items,
    };
    const apply = async () => {
      try {
        await app().api("/api/influencer-source-mappings/batch", { method: "POST", body: JSON.stringify(body) });
      } catch (error) {
        if (!error.details?.moves) throw error;
        if (!confirm(`${error.message}\n确定将「${sourceName}」映射到「${targetName}」吗？`)) return;
        const hasAssignmentConflict = error.details.assignment_conflicts?.length;
        const resolution = hasAssignmentConflict && confirm("检测到同月商务归属冲突。\n点“确定”使用来源达人归属，点“取消”保留目标达人归属。") ? "use_source" : "keep_target";
        await app().api("/api/influencer-source-mappings/batch", {
          method: "POST",
          body: JSON.stringify({ ...body, confirm_move: true, assignment_resolution: resolution }),
        });
      }
      s.selected.clear();
      app().toast(items.length > 1 ? `批量映射成功，共 ${items.length} 条` : `已将「${sourceName}」映射到「${targetName}」`);
      await loadInfluencer();
    };
    if (items.length > 1) {
      showTablePopover("batch-confirm", `<div class="popover-message"><span class="popover-icon warning">!</span><div class="popover-copy"><p>已选中 <em>${items.length}</em> 行，确认批量修改公司达人为「<em class="highlight">${esc(targetName)}</em>」？</p></div></div><div class="popover-actions"><button class="mini-button" data-popover-cancel>取消</button><button class="mini-button primary" data-popover-confirm>确定修改</button></div>`, apply);
      return;
    }
    await apply();
  }

  const companyOptions = () => state.influencer.companies.map((r) => ({ value: r.company_influencer_id, label: `${r.company_influencer_name} (ID ${r.company_influencer_id})` }));
  async function influencerPrimaryAction() {
    const s = state.influencer;
    if (s.view === "assignment") return loadInfluencer();
    if (s.view === "source") {
      s.batchMode = !s.batchMode;
      s.selected.clear();
      closeInfluencerAssignDropdown();
      hideTablePopover();
      return renderInfluencerTable();
    }
    const data = await formDialog("新增公司达人", [{ name: "company_influencer_name", label: "公司达人名称" }, { name: "note", label: "备注", type: "textarea", required: false }]);
    if (!data) return;
    try { await app().api("/api/company-influencers", { method: "POST", body: JSON.stringify(data) }); app().toast("新增成功"); await loadInfluencer(); } catch (error) { app().toast(error.message, true); }
  }

  async function influencerTableAction(event) {
    const action = event.currentTarget.dataset.action;
    if (!state.influencer.batchMode && ["select-all-source", "select-source-account"].includes(action)) return;
    if (action === "select-all-source") {
      const allSelected = state.influencer.rows.length > 0 && state.influencer.rows.every((r) => state.influencer.selected.has(`${r.platform_code}|${r.source_influencer_id}`));
      state.influencer.rows.forEach((r) => {
        const key = `${r.platform_code}|${r.source_influencer_id}`;
        if (allSelected) state.influencer.selected.delete(key);
        else state.influencer.selected.set(key, { platform_code: r.platform_code, source_influencer_id: r.source_influencer_id, source_influencer_name: r.source_influencer_name });
      });
      return renderInfluencerTable();
    }
    if (action === "select-source-account") {
      const row = state.influencer.rows[Number(event.currentTarget.closest("tr").dataset.index)], key = `${row.platform_code}|${row.source_influencer_id}`;
      event.currentTarget.checked ? state.influencer.selected.set(key, { platform_code: row.platform_code, source_influencer_id: row.source_influencer_id, source_influencer_name: row.source_influencer_name }) : state.influencer.selected.delete(key);
      return renderInfluencerTable();
    }
    const tr = event.currentTarget.closest("tr"), row = state.influencer.rows[Number(tr.dataset.index)];
    try {
      let successMessage = "操作成功";
      if (action === "edit-company") {
        const data = await formDialog("编辑公司达人", [
          { name: "company_influencer_name", label: "公司达人名称", value: row.company_influencer_name },
          { name: "note", label: "备注", type: "textarea", required: false, value: row.note },
        ]);
        if (!data) return app().toast("已取消编辑");
        await app().api(`/api/company-influencers/${row.company_influencer_id}`, { method: "PUT", body: JSON.stringify(data) });
        successMessage = "保存成功";
      } else if (action.endsWith("company")) {
        const influencerName = row.company_influencer_name || "公司达人";
        if (action === "delete-company") {
          if (!confirm("确定删除该公司达人？")) return;
          await app().api(`/api/company-influencers/${row.company_influencer_id}`, { method: "DELETE" });
          successMessage = `${influencerName}已删除`;
        } else {
          const enabled = action === "enable-company";
          await app().api(`/api/company-influencers/${row.company_influencer_id}/status`, { method: "PUT", body: JSON.stringify({ is_active: enabled }) });
          successMessage = `${influencerName}已${enabled ? "启用" : "停用"}`;
        }
      } else if (action.endsWith("source-map")) {
        const sourceName = row.source_influencer_name || row.source_influencer_id || "平台达人映射";
        if (action === "delete-source-map") {
          if (!confirm("确定删除平台账号映射？")) return;
          await app().api(`/api/influencer-source-mappings/${row.mapping_id}`, { method: "DELETE" });
          successMessage = `${sourceName}已删除`;
        } else {
          const enabled = action === "enable-source-map";
          await app().api(`/api/influencer-source-mappings/${row.mapping_id}/status`, { method: "PUT", body: JSON.stringify({ is_active: enabled }) });
          successMessage = `${sourceName}已${enabled ? "启用" : "停用"}`;
        }
      } else if (action === "save-assignment") {
        await app().api("/api/company-influencer-assignments", { method: "POST", body: JSON.stringify({ company_influencer_id: row.company_influencer_id, effective_month: document.getElementById("globalMonth").value, business_owner_id: tr.querySelector(".assignment-owner").value, note: tr.querySelector(".inline-note").value, is_active: true }) });
        successMessage = "商务归属已保存";
      } else if (action === "delete-assignment") {
        if (!row.effective_month) return app().toast("当前没有可删除的归属版本", true);
        if (!confirm("确定删除当前生效归属版本？")) return;
        await app().api(`/api/company-influencer-assignments/${row.company_influencer_id}/${String(row.effective_month).slice(0, 7)}`, { method: "DELETE" });
        successMessage = "商务归属已删除";
      }
      app().toast(successMessage); await loadInfluencer();
    } catch (error) { app().toast(error.message, true); }
  }

  async function activateProductView(view) {
    const targetView = view === "category"
      ? (["products", "l1", "l2"].includes(state.product.view) ? state.product.view : "products")
      : view;
    if (state.product.view !== targetView) {
      state.product.page = 1;
      state.product.selected.clear();
      state.product.batchMode = false;
    }
    productLayout(targetView);
    state.product.initialized = true;
    await loadProduct();
  }
  window.productCategoryModule = { activate: () => activateProductView("category") };
  window.productMappingModule = {
    activate: () => activateProductView("mappings"),
    onSaved: () => { showProductRefresh({ pending: true }); watchProductRefresh(); },
  };
  window.influencerMasterModule = { activate: async (force = false) => { if (!state.influencer.initialized) { influencerLayout(); state.influencer.initialized = true; } state.influencer.batchMode = false; state.influencer.selected.clear(); if (force || document.querySelector('.tab-button.is-active')?.dataset.tab === "assignmentPanel") await loadInfluencer(); } };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => window.influencerMasterModule.activate());
  else window.influencerMasterModule.activate();
})();
