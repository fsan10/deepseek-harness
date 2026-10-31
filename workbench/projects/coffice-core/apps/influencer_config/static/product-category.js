(() => {
  const state = {
    initialized: false,
    loading: false,
    view: "catalog",
    categories: [],
    summary: {},
    rows: [],
    page: 1,
    pageSize: 10,
    totalPages: 1,
    total: 0,
    searchTimer: null,
    confirmResolve: null,
    refreshTimer: null,
    watchedRefreshRevision: 0,
  };

  const app = () => window.influencerApp;
  const root = () => document.getElementById("productCategoryApp");
  const number = new Intl.NumberFormat("zh-CN");
  const esc = (value) => app().escapeHtml(value ?? "");
  const viewLevel = () => state.view === "l1" ? 1 : state.view === "l2" ? 2 : null;
  const l1Categories = () => state.categories.filter((item) => Number(item.category_level) === 1);
  const l2Categories = (parentId = null) => state.categories.filter((item) =>
    Number(item.category_level) === 2
      && (parentId === null || Number(item.parent_category_id) === Number(parentId)));
  const findCategory = (id) => state.categories.find((item) => Number(item.category_id) === Number(id));

  function layout() {
    root().innerHTML = `
      <div id="catalogMetrics" class="metric-grid product-metrics"></div>
      <nav class="catalog-subnav" aria-label="商品分类配置子页面">
          <button class="catalog-subtab is-active" data-view="catalog" type="button">商品品类配置</button>
          <button class="catalog-subtab" data-view="l1" type="button">一级分类配置</button>
          <button class="catalog-subtab" data-view="l2" type="button">二级分类配置</button>
      </nav>
      <div class="catalog-toolbar">
          <div class="catalog-filters">
            <select id="catalogStatus" class="select-chevron" aria-label="配置状态">
              <option value="all">全部状态</option>
              <option value="active">当前启用</option>
              <option value="inactive">已停用</option>
            </select>
            <label class="product-search"><span class="sr-only">搜索配置</span><svg><use href="#i-search"/></svg><input id="catalogSearch" type="search" placeholder="搜索分类、产品、商家编码"></label>
          </div>
          <div class="catalog-actions">
            <button id="addCatalogRecord" class="button button-primary" type="button"><svg><use href="#i-plus"/></svg><span>新增产品</span></button>
          </div>
      </div>
      <section class="catalog-card">
        <div id="catalogTableShell" class="product-table-shell"><div class="product-empty">正在读取商品分类配置…</div></div>
        <div id="catalogPagination" class="product-pagination"></div>
      </section>
      <div class="definition-card definition-grid assignment-definitions product-guide">
        <article><strong>唯一关系</strong><span>一级分类 → 二级分类 → 产品 ↔ 商家编码（一一对应）</span></article>
        <article><strong>直接编辑</strong><span>点击单元格修改；分类支持搜索和自动新增</span></article>
        <article><strong>看板同步</strong><span>配置立即保存，二级分类与产品GMV占比在后台合并刷新</span></article>
        <article><strong>删除区别</strong><span>停用可恢复；删除会永久移除无依赖配置</span></article>
      </div>
      <dialog id="newProductDialog" class="product-dialog">
        <form id="newProductForm">
          <div class="dialog-heading"><div><p>商品品类配置</p><h3>新增产品</h3></div><button class="dialog-close close-dialog" type="button" aria-label="关闭">×</button></div>
          <div class="product-form">
            <label><span>产品名称 <em>*</em></span><input id="newProductName" maxlength="255" required autocomplete="off"></label>
            <label><span>商家编码 <em>*</em></span><input id="newMerchantCode" maxlength="128" placeholder="例如 M-NXSY-X" required autocomplete="off"><small>产品和编码一一对应；数量位置使用 X。</small></label>
          </div>
          <div class="dialog-actions"><span class="dialog-spacer"></span><button class="button close-dialog" type="button">取消</button><button class="button button-primary" type="submit">新增产品</button></div>
        </form>
      </dialog>
      <dialog id="newCategoryDialog" class="product-dialog">
        <form id="newCategoryForm">
          <div class="dialog-heading"><div><p>分类配置</p><h3 id="newCategoryTitle">新增分类</h3></div><button class="dialog-close close-dialog" type="button" aria-label="关闭">×</button></div>
          <div class="product-form">
            <label id="newCategoryParentField" hidden><span>所属一级分类</span><select id="newCategoryParent" class="select-chevron"></select></label>
            <label><span>分类名称 <em>*</em></span><input id="newCategoryName" maxlength="128" required autocomplete="off"></label>
          </div>
          <div class="dialog-actions"><span class="dialog-spacer"></span><button class="button close-dialog" type="button">取消</button><button class="button button-primary" type="submit">新增分类</button></div>
        </form>
      </dialog>
      <dialog id="autoCategoryDialog" class="auto-add-dialog">
        <div class="auto-add-body">
          <span class="auto-add-icon">＋</span>
          <div><h3>自动添加新类型</h3><p id="autoCategoryMessage"></p></div>
        </div>
        <div class="auto-add-actions"><button id="cancelAutoCategory" class="button" type="button">取消</button><button id="confirmAutoCategory" class="button button-primary" type="button">确定添加</button></div>
      </dialog>`;
    bind();
  }

  function metricCard(label, value, meta) {
    return `<article class="metric-card"><div class="metric-label">${esc(label)}</div><div class="metric-value">${esc(value)}</div><div class="metric-meta">${esc(meta)}</div></article>`;
  }

  function renderSummary(summary) {
    state.summary = summary;
    document.getElementById("catalogMetrics").innerHTML = [
      metricCard("一级分类", number.format(summary.category_l1_total || 0), "公司统一产品大类"),
      metricCard("二级分类", number.format(summary.category_l2_total || 0), "达播看板主要展示层级"),
      metricCard("产品 / 编码", `${number.format(summary.product_total || 0)} / ${number.format(summary.mapping_total || 0)}`, "严格一一对应"),
      metricCard("启用配置", number.format(summary.active_mapping_total || 0), "参与当前订单匹配"),
    ].join("");
  }

  function statusChip(active) {
    return active
      ? '<span class="status-chip">启用</span>'
      : '<span class="status-chip disabled">停用</span>';
  }

  function selectOptions(values, selectedId, includeBlank = false) {
    const blank = includeBlank ? '<option value="">请选择</option>' : "";
    return blank + values.map((item) =>
      `<option value="${item.category_id}" ${Number(item.category_id) === Number(selectedId) ? "selected" : ""}>${esc(item.category_name)}${item.is_active ? "" : "（停用）"}</option>`
    ).join("");
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

  function renderPagination() {
    const pagination = document.getElementById("catalogPagination");
    const pages = getPageNumbers(state.page, state.totalPages);
    pagination.innerHTML = `
      <span class="pagination-summary">共 ${number.format(state.total)} 条</span>
      <div class="product-pagination-actions">
        <select id="catalogPageSize" class="select-chevron pagination-size" aria-label="每页条数">
          <option value="10" ${state.pageSize === 10 ? "selected" : ""}>10 条/页</option>
          <option value="20" ${state.pageSize === 20 ? "selected" : ""}>20 条/页</option>
          <option value="50" ${state.pageSize === 50 ? "selected" : ""}>50 条/页</option>
          <option value="100" ${state.pageSize === 100 ? "selected" : ""}>100 条/页</option>
        </select>
        <button id="previousCatalogPage" class="pagination-nav" type="button" aria-label="上一页" ${state.page <= 1 ? "disabled" : ""}><svg><use href="#i-left"/></svg></button>
        <div id="catalogPageNumbers" class="pagination-pages" aria-label="页码">${pages
          .map((page) => `<button class="pagination-page-btn ${page === state.page ? "is-active" : ""}" type="button" data-page="${page}" aria-label="第 ${page} 页" ${page === state.page ? "aria-current='page'" : ""}>${number.format(page)}</button>`)
          .join("")}</div>
        <button id="nextCatalogPage" class="pagination-nav" type="button" aria-label="下一页" ${state.page >= state.totalPages ? "disabled" : ""}><svg><use href="#i-right"/></svg></button>
        <span class="pagination-page">第 ${state.page}/${state.totalPages} 页</span>
      </div>`;
    document.getElementById("catalogPageSize").addEventListener("change", guarded(async (event) => {
      state.pageSize = Number(event.target.value);
      state.page = 1;
      await loadActiveView();
    }));
    document.getElementById("previousCatalogPage").addEventListener("click", guarded(async () => {
      state.page -= 1;
      await loadActiveView();
    }));
    document.getElementById("nextCatalogPage").addEventListener("click", guarded(async () => {
      state.page += 1;
      await loadActiveView();
    }));
    document.getElementById("catalogPageNumbers")?.querySelectorAll(".pagination-page-btn").forEach((button) => {
      button.addEventListener("click", guarded(async () => {
        state.page = Number(button.dataset.page);
        await loadActiveView();
      }));
    });
  }

  function categoryCell(row, level) {
    const id = level === 1 ? row.category_l1_id : row.category_l2_id;
    const name = level === 1 ? row.category_l1_name : row.category_l2_name;
    return `<div class="category-picker" data-level="${level}" data-selected-id="${id || ""}">
      <button type="button" class="assign-trigger category-trigger" role="combobox" aria-expanded="false" aria-label="${level === 1 ? "一级分类" : "二级分类"}"><span class="assign-value ${name ? "" : "empty"}">${esc(name || "请选择")}</span><svg><use href="#i-down"/></svg></button>
      <div class="category-picker-menu" hidden>
        <label class="category-picker-menu-search"><svg><use href="#i-search"/></svg><input class="category-picker-menu-input" type="search" placeholder="查找或创建选项" autocomplete="off"></label>
        <div class="category-picker-options"></div>
      </div>
    </div>`;
  }

  function renderCatalogRows() {
    const shell = document.getElementById("catalogTableShell");
    if (!state.rows.length) {
      shell.innerHTML = '<div class="product-empty"><div><strong>暂无匹配配置</strong><br><span>可调整筛选条件或新增产品。</span></div></div>';
      renderPagination();
      return;
    }
    shell.innerHTML = `<table class="product-config-table catalog-table"><thead><tr><th>一级分类</th><th>二级分类</th><th>产品名</th><th>商家编码</th><th>状态</th><th>操作</th></tr></thead><tbody>${state.rows.map((row, index) => `
      <tr data-index="${index}">
        <td>${categoryCell(row, 1)}</td>
        <td>${categoryCell(row, 2)}</td>
        <td><input class="catalog-cell-input product-name-input" maxlength="255" value="${esc(row.product_name)}" aria-label="产品名"></td>
        <td><input class="catalog-cell-input merchant-code-input money" maxlength="128" value="${esc(row.merchant_code)}" aria-label="商家编码"></td>
        <td>${statusChip(row.row_active)}</td>
        <td><div class="product-row-actions">
          <button class="table-action action-save save-catalog-row" type="button"><svg><use href="#i-check"/></svg>保存</button>
          <span class="action-divider">|</span>
          <button class="table-action ${row.row_active ? "action-disable" : "action-enable"} toggle-catalog-row" type="button"><svg><use href="#i-power"/></svg>${row.row_active ? "停用" : "启用"}</button>
          <span class="action-divider">|</span>
          <button class="table-action action-delete delete-catalog-row" type="button"><svg><use href="#i-trash"/></svg>删除</button>
        </div></td>
      </tr>`).join("")}</tbody></table>`;

    shell.querySelectorAll("tr[data-index]").forEach((node) => {
      const row = state.rows[Number(node.dataset.index)];
      node.querySelectorAll(".category-picker").forEach((picker) => bindCategoryPicker(picker, row));
      node.querySelector(".product-name-input").addEventListener("input", (event) => {
        row.product_name = event.target.value;
      });
      node.querySelector(".merchant-code-input").addEventListener("input", (event) => {
        row.merchant_code = event.target.value;
      });
      node.querySelector(".save-catalog-row").addEventListener("click", guarded((event) => saveCatalogRow(row, event.currentTarget)));
      node.querySelector(".toggle-catalog-row").addEventListener("click", guarded(() => toggleCatalogRow(row)));
      node.querySelector(".delete-catalog-row").addEventListener("click", guarded(() => deleteCatalogRow(row)));
    });
    renderPagination();
  }

  function pickerValues(row, level) {
    if (level === 1) return l1Categories();
    return l2Categories(row.category_l1_id);
  }

  function bindCategoryPicker(picker, row) {
    const trigger = picker.querySelector(".assign-trigger");
    const valueLabel = picker.querySelector(".assign-value");
    const menu = picker.querySelector(".category-picker-menu");
    const menuSearch = picker.querySelector(".category-picker-menu-input");
    const options = picker.querySelector(".category-picker-options");
    const level = Number(picker.dataset.level);
    const original = {
      id: level === 1 ? row.category_l1_id : row.category_l2_id,
      name: level === 1 ? row.category_l1_name : row.category_l2_name,
    };
    const setValueLabel = (text, empty = false) => {
      valueLabel.textContent = text || "请选择";
      valueLabel.classList.toggle("empty", empty || !text);
    };
    const restoreOriginal = () => {
      const valid = pickerValues(row, level).find((item) =>
        Number(item.category_id) === Number(original.id));
      setValueLabel(valid?.category_name || "");
    };

    const renderOptions = () => {
      const query = menuSearch.value.trim().toLocaleLowerCase("zh-CN");
      const values = pickerValues(row, level).filter((item) =>
        item.category_name.toLocaleLowerCase("zh-CN").includes(query));
      options.innerHTML = values.length
        ? values.map((item) => `<button class="category-option ${Number(item.category_id) === Number(picker.dataset.selectedId) ? "is-selected" : ""}" data-id="${item.category_id}" type="button"><span>${esc(item.category_name)}</span>${Number(item.category_id) === Number(picker.dataset.selectedId) ? "<strong>✓</strong>" : ""}</button>`).join("")
        : `<div class="category-no-result">未找到“${esc(menuSearch.value.trim())}”</div>`;
      options.querySelectorAll(".category-option").forEach((option) => {
        option.addEventListener("mousedown", (event) => {
          event.preventDefault();
          const selected = findCategory(option.dataset.id);
          applyCategorySelection(row, level, selected);
          original.id = selected.category_id;
          original.name = selected.category_name;
          setValueLabel(selected.category_name);
          picker.dataset.selectedId = String(selected.category_id);
          menu.hidden = true;
          trigger.setAttribute("aria-expanded", "false");
          menuSearch.blur();
        });
      });
    };

    const open = () => {
      document.querySelectorAll(".category-picker-menu").forEach((other) => {
        if (other !== menu) other.hidden = true;
      });
      document.querySelectorAll(".assign-trigger[aria-expanded='true']").forEach((other) => {
        if (other !== trigger) other.setAttribute("aria-expanded", "false");
      });
      menu.hidden = false;
      trigger.setAttribute("aria-expanded", "true");
      menuSearch.value = "";
      renderOptions();
      menuSearch.focus();
    };

    trigger.addEventListener("click", (event) => {
      event.stopPropagation();
      if (menu.hidden) open(); else { menu.hidden = true; trigger.setAttribute("aria-expanded", "false"); }
    });
    menuSearch.addEventListener("input", () => {
      renderOptions();
    });
    const handleKeydown = (event) => {
      if (event.key === "Escape") {
        restoreOriginal();
        menu.hidden = true;
        trigger.setAttribute("aria-expanded", "false");
        menuSearch.blur();
      }
      if (event.key === "Enter") {
        event.preventDefault();
        const first = options.querySelector(".category-option");
        if (first) first.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
        else menuSearch.blur();
      }
    };
    menuSearch.addEventListener("keydown", handleKeydown);
    const finalizeCategory = () => window.setTimeout(guarded(async () => {
      if (picker.contains(document.activeElement)) return;
      menu.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
      const typed = menuSearch.value.trim();
      if (!typed) {
        restoreOriginal();
        return;
      }
      const exact = pickerValues(row, level).find((item) =>
        item.category_name.toLocaleLowerCase("zh-CN") === typed.toLocaleLowerCase("zh-CN"));
      if (exact) {
        applyCategorySelection(row, level, exact);
        original.id = exact.category_id;
        original.name = exact.category_name;
        setValueLabel(exact.category_name);
        picker.dataset.selectedId = String(exact.category_id);
        return;
      }
      if (level === 2 && !row.category_l1_id) {
        restoreOriginal();
        app().toast("请先选择一级分类", true);
        return;
      }
      const confirmed = await confirmAutoCategory(level, typed);
      if (!confirmed) {
        restoreOriginal();
        return;
      }
      const created = await app().api("/api/product-categories", {
        method: "POST",
        body: JSON.stringify({
          category_level: level,
          parent_category_id: level === 2 ? row.category_l1_id : null,
          category_name: typed,
        }),
      });
      state.categories.push(created);
      applyCategorySelection(row, level, created);
      original.id = created.category_id;
      original.name = created.category_name;
      setValueLabel(created.category_name);
      picker.dataset.selectedId = String(created.category_id);
      notifyMutation(`已自动添加${level === 1 ? "一级" : "二级"}分类 ${typed}`, created.dashboard_refresh);
      renderSummary(await refreshMetadata());
    }), 120);
    menuSearch.addEventListener("blur", finalizeCategory);
  }

  function applyCategorySelection(row, level, category) {
    if (level === 1) {
      const changed = Number(row.category_l1_id) !== Number(category.category_id);
      row.category_l1_id = category.category_id;
      row.category_l1_name = category.category_name;
      if (changed && Number(row.category_l2_parent_id || findCategory(row.category_l2_id)?.parent_category_id) !== Number(category.category_id)) {
        row.category_l2_id = null;
        row.category_l2_name = "";
        const rowNode = [...document.querySelectorAll("tr[data-index]")].find((node) => state.rows[Number(node.dataset.index)] === row);
        const l2Picker = rowNode?.querySelector('.category-picker[data-level="2"]');
        if (l2Picker) {
          l2Picker.dataset.selectedId = "";
          const l2Label = l2Picker.querySelector(".assign-value");
          if (l2Label) { l2Label.textContent = "请选择"; l2Label.classList.add("empty"); }
        }
      }
    } else {
      row.category_l2_id = category.category_id;
      row.category_l2_name = category.category_name;
      row.category_l2_parent_id = category.parent_category_id;
    }
  }

  function confirmAutoCategory(level, name) {
    return new Promise((resolve) => {
      state.confirmResolve = resolve;
      document.getElementById("autoCategoryMessage").innerHTML = `${level === 1 ? "一级分类" : "二级分类"}「<strong>${esc(name)}</strong>」不存在，是否自动添加到类型管理？`;
      document.getElementById("autoCategoryDialog").showModal();
    });
  }

  async function saveCatalogRow(row, button) {
    if (!row.category_l1_id || !row.category_l2_id) return app().toast("一级分类和二级分类不能为空", true);
    if (!row.product_name.trim()) return app().toast("产品名称不能为空", true);
    if (!row.merchant_code.trim()) return app().toast("商家编码不能为空", true);
    button.disabled = true;
    button.innerHTML = "保存中";
    try {
      const saved = await app().api(`/api/product-catalog/${row.mapping_id}`, {
        method: "PUT",
        body: JSON.stringify({
          category_l1_id: row.category_l1_id,
          category_l2_id: row.category_l2_id,
          product_name: row.product_name.trim(),
          code_pattern: row.merchant_code.trim(),
          code_role: row.code_role || "box",
        }),
      });
      await reload("商品配置已保存", saved.dashboard_refresh);
    } finally {
      button.disabled = false;
      button.innerHTML = '<svg><use href="#i-check"/></svg>保存';
    }
  }

  async function toggleCatalogRow(row) {
    const enabling = !row.row_active;
    if (!window.confirm(`确认${enabling ? "启用" : "停用"}“${row.product_name}”吗？`)) return;
    const saved = await app().api(`/api/product-catalog/${row.mapping_id}/status`, {
      method: "PUT",
      body: JSON.stringify({ is_active: enabling }),
    });
    await reload(`已${enabling ? "启用" : "停用"} ${row.product_name}`, saved.dashboard_refresh);
  }

  async function deleteCatalogRow(row) {
    if (!window.confirm(`确认永久删除产品“${row.product_name}”及商家编码“${row.merchant_code}”吗？此操作不可恢复。`)) return;
    const deleted = await app().api(`/api/product-catalog/${row.mapping_id}`, { method: "DELETE" });
    await reload(`已删除 ${row.product_name}`, deleted.dashboard_refresh);
  }

  function renderCategoryRows(level) {
    const shell = document.getElementById("catalogTableShell");
    if (!state.rows.length) {
      shell.innerHTML = `<div class="product-empty"><div><strong>暂无${level === 1 ? "一级" : "二级"}分类</strong></div></div>`;
      renderPagination();
      return;
    }
    shell.innerHTML = `<table class="product-config-table category-table category-level-${level}"><thead><tr>${level === 2 ? '<th class="category-col-parent">一级分类</th>' : ''}<th class="category-col-name">${level === 1 ? "一级分类" : "二级分类"}</th><th class="category-col-related">关联${level === 1 ? "二级分类" : "产品"}</th><th class="category-col-status">状态</th><th class="category-col-time">更新时间</th><th class="category-col-actions">操作</th></tr></thead><tbody>${state.rows.map((row, index) => {
      const parentName = level === 2 ? (l1Categories().find((item) => Number(item.category_id) === Number(row.parent_category_id))?.category_name || "") : "";
      return `
      <tr data-index="${index}">
        ${level === 2 ? `<td class="category-col-parent"><div class="category-picker parent-picker" data-level="parent"><button type="button" class="assign-trigger category-trigger" role="combobox" aria-expanded="false" aria-label="一级分类"><span class="assign-value ${parentName ? "" : "empty"}">${esc(parentName || "请选择")}</span><svg><use href="#i-down"/></svg></button><div class="category-picker-menu" hidden><label class="category-picker-menu-search"><svg><use href="#i-search"/></svg><input class="category-picker-menu-input" type="search" placeholder="查找选项" autocomplete="off"></label><div class="category-picker-options"></div></div></div></td>` : ""}
        <td class="category-col-name"><input class="catalog-cell-input category-name-input" maxlength="128" value="${esc(row.category_name)}" aria-label="${level === 1 ? "一级分类" : "二级分类"}名称"></td>
        <td class="category-col-related money">${number.format(row.related_count || 0)}</td>
        <td class="category-col-status">${statusChip(row.is_active)}</td>
        <td class="category-col-time">${esc(String(row.updated_at || "").replace("T", " ").slice(0, 19))}</td>
        <td class="category-col-actions"><div class="product-row-actions">
          <button class="table-action action-save save-category-row" type="button"><svg><use href="#i-check"/></svg>保存</button>
          <span class="action-divider">|</span>
          <button class="table-action ${row.is_active ? "action-disable" : "action-enable"} toggle-category-row" type="button"><svg><use href="#i-power"/></svg>${row.is_active ? "停用" : "启用"}</button>
          <span class="action-divider">|</span>
          <button class="table-action action-delete delete-category-row" type="button"><svg><use href="#i-trash"/></svg>删除</button>
        </div></td>
      </tr>`;
    }).join("")}</tbody></table>`;
    shell.querySelectorAll("tr[data-index]").forEach((node) => {
      const row = state.rows[Number(node.dataset.index)];
      node.querySelector(".category-name-input").addEventListener("input", (event) => {
        row.category_name = event.target.value;
      });
      const parentPicker = node.querySelector(".parent-picker");
      if (parentPicker) bindParentPicker(parentPicker, row);
      node.querySelector(".save-category-row").addEventListener("click", guarded(() => saveCategoryRow(row)));
      node.querySelector(".toggle-category-row").addEventListener("click", guarded(() => toggleCategoryRow(row)));
      node.querySelector(".delete-category-row").addEventListener("click", guarded(() => deleteCategoryRow(row)));
    });
    renderPagination();
  }

  function bindParentPicker(picker, row) {
    const trigger = picker.querySelector(".assign-trigger");
    const valueLabel = picker.querySelector(".assign-value");
    const menu = picker.querySelector(".category-picker-menu");
    const menuSearch = picker.querySelector(".category-picker-menu-input");
    const options = picker.querySelector(".category-picker-options");
    const renderOptions = () => {
      const query = menuSearch.value.trim().toLocaleLowerCase("zh-CN");
      const values = l1Categories().filter((item) => item.category_name.toLocaleLowerCase("zh-CN").includes(query));
      options.innerHTML = values.length
        ? values.map((item) => `<button class="category-option ${Number(item.category_id) === Number(row.parent_category_id) ? "is-selected" : ""}" data-id="${item.category_id}" type="button"><span>${esc(item.category_name)}${item.is_active ? "" : "（停用）"}</span>${Number(item.category_id) === Number(row.parent_category_id) ? "<strong>✓</strong>" : ""}</button>`).join("")
        : `<div class="category-no-result">未找到“${esc(menuSearch.value.trim())}”</div>`;
      options.querySelectorAll(".category-option").forEach((option) => {
        option.addEventListener("mousedown", (event) => {
          event.preventDefault();
          row.parent_category_id = Number(option.dataset.id);
          const selected = l1Categories().find((item) => Number(item.category_id) === row.parent_category_id);
          valueLabel.textContent = selected ? selected.category_name : "请选择";
          valueLabel.classList.toggle("empty", !selected);
          menu.hidden = true;
          trigger.setAttribute("aria-expanded", "false");
          menuSearch.blur();
        });
      });
    };
    const open = () => {
      document.querySelectorAll(".category-picker-menu").forEach((other) => { if (other !== menu) other.hidden = true; });
      document.querySelectorAll(".assign-trigger[aria-expanded='true']").forEach((other) => { if (other !== trigger) other.setAttribute("aria-expanded", "false"); });
      menu.hidden = false;
      trigger.setAttribute("aria-expanded", "true");
      menuSearch.value = "";
      renderOptions();
      menuSearch.focus();
    };
    trigger.addEventListener("click", (event) => {
      event.stopPropagation();
      if (menu.hidden) open(); else { menu.hidden = true; trigger.setAttribute("aria-expanded", "false"); }
    });
    menuSearch.addEventListener("input", renderOptions);
    menuSearch.addEventListener("blur", () => window.setTimeout(() => {
      if (!picker.contains(document.activeElement)) { menu.hidden = true; trigger.setAttribute("aria-expanded", "false"); }
    }, 120));
    menuSearch.addEventListener("keydown", (event) => {
      if (event.key === "Escape") { menu.hidden = true; trigger.setAttribute("aria-expanded", "false"); menuSearch.blur(); }
    });
  }

  async function saveCategoryRow(row) {
    const name = row.category_name.trim();
    if (!name) return app().toast("分类名称不能为空", true);
    const saved = await app().api(`/api/product-categories/${row.category_id}`, {
      method: "PUT",
      body: JSON.stringify({
        category_name: name,
        parent_category_id: row.category_level === 2 ? row.parent_category_id : null,
      }),
    });
    await reload("分类已保存", saved.dashboard_refresh);
  }

  async function toggleCategoryRow(row) {
    const enabling = !row.is_active;
    if (!window.confirm(`确认${enabling ? "启用" : "停用"}分类“${row.category_name}”吗？`)) return;
    const saved = await app().api(`/api/product-categories/${row.category_id}/status`, {
      method: "PUT",
      body: JSON.stringify({ is_active: enabling }),
    });
    await reload(`分类已${enabling ? "启用" : "停用"}`, saved.dashboard_refresh);
  }

  async function deleteCategoryRow(row) {
    if (!window.confirm(`确认永久删除分类“${row.category_name}”吗？仅无下级配置的分类可删除。`)) return;
    const deleted = await app().api(`/api/product-categories/${row.category_id}`, { method: "DELETE" });
    await reload(`分类 ${row.category_name} 已删除`, deleted.dashboard_refresh);
  }

  async function refreshMetadata() {
    const data = await app().api("/api/product-categories");
    state.categories = data.categories;
    state.summary = data.summary;
    return data.summary;
  }

  function notifyMutation(message, refresh) {
    const queued = refresh && Number(refresh.requested_revision) > 0;
    app().toast(queued ? `${message}；看板数据正在后台刷新` : message);
    if (queued) watchDashboardRefresh(Number(refresh.requested_revision));
  }

  function watchDashboardRefresh(revision) {
    state.watchedRefreshRevision = Math.max(state.watchedRefreshRevision, revision);
    window.clearTimeout(state.refreshTimer);
    let attempts = 0;
    const poll = async () => {
      attempts += 1;
      try {
        const status = await app().api("/api/refresh-status");
        const task = status.product_dashboard || {};
        if (task.status === "failed" && Number(task.requested_revision || 0) >= state.watchedRefreshRevision) {
          app().toast(`配置已保存，但看板刷新失败：${task.last_error || "请查看服务日志"}`, true);
          return;
        }
        if (Number(task.completed_revision || 0) >= state.watchedRefreshRevision) {
          app().toast(`看板数据刷新完成${task.duration_seconds == null ? "" : `（${task.duration_seconds}秒）`}`);
          return;
        }
      } catch (error) {
        if (attempts >= 3) {
          app().toast(`配置已保存，但暂时无法读取看板刷新状态：${error.message}`, true);
          return;
        }
      }
      if (attempts >= 120) {
        app().toast("配置已保存，看板刷新仍在后台执行，请稍后查看", true);
        return;
      }
      state.refreshTimer = window.setTimeout(poll, 750);
    };
    state.refreshTimer = window.setTimeout(poll, 350);
  }

  async function activeViewRequest() {
    const params = new URLSearchParams({
      search: document.getElementById("catalogSearch")?.value.trim() || "",
      status: document.getElementById("catalogStatus")?.value || "all",
      page: String(state.page),
      page_size: String(state.pageSize),
    });
    const level = viewLevel();
    const request = level
      ? await app().api(`/api/product-category-list?level=${level}&${params}`)
      : await app().api(`/api/product-catalog?${params}`);
    return { level, data: request };
  }

  function applyActiveView({ level, data }) {
    state.rows = data.rows;
    state.page = Number(data.pagination.page);
    state.totalPages = Number(data.pagination.total_pages);
    state.total = Number(data.pagination.total);
    if (state.page > state.totalPages) {
      state.page = state.totalPages;
      return false;
    }
    if (level) renderCategoryRows(level);
    else renderCatalogRows();
    return true;
  }

  async function loadActiveView() {
    const view = await activeViewRequest();
    if (!applyActiveView(view)) return loadActiveView();
  }

  async function reload(message = "", refresh = null) {
    if (message) notifyMutation(message, refresh);
    try {
      const [summary, view] = await Promise.all([refreshMetadata(), activeViewRequest()]);
      renderSummary(summary);
      if (!applyActiveView(view)) await loadActiveView();
    } catch (error) {
      if (!message) throw error;
      app().toast(`${message}，但列表刷新失败：${error.message}`, true);
    }
  }

  function updateToolbarForView() {
    const level = viewLevel();
    const button = document.getElementById("addCatalogRecord");
    button.querySelector("span").textContent = level ? `新增${level === 1 ? "一级" : "二级"}分类` : "新增产品";
    document.getElementById("catalogSearch").placeholder = level
      ? `搜索${level === 1 ? "一级" : "二级"}分类`
      : "搜索分类、产品、商家编码";
  }

  function openAddDialog() {
    const level = viewLevel();
    if (!level) {
      document.getElementById("newProductForm").reset();
      document.getElementById("newProductDialog").showModal();
      document.getElementById("newProductName").focus();
      return;
    }
    document.getElementById("newCategoryForm").reset();
    document.getElementById("newCategoryTitle").textContent = `新增${level === 1 ? "一级" : "二级"}分类`;
    const parentField = document.getElementById("newCategoryParentField");
    parentField.hidden = level === 1;
    document.getElementById("newCategoryParent").innerHTML = selectOptions(
      l1Categories().filter((item) => item.is_active),
      "",
      true,
    );
    document.getElementById("newCategoryDialog").dataset.level = String(level);
    document.getElementById("newCategoryDialog").showModal();
    document.getElementById("newCategoryName").focus();
  }

  async function addProduct(event) {
    event.preventDefault();
    const created = await app().api("/api/product-catalog", {
      method: "POST",
      body: JSON.stringify({
        product_name: document.getElementById("newProductName").value.trim(),
        code_pattern: document.getElementById("newMerchantCode").value.trim(),
      }),
    });
    document.getElementById("newProductDialog").close();
    state.page = 1;
    await reload("产品已新增；可在列表中设置一级、二级分类", created.dashboard_refresh);
  }

  async function addCategory(event) {
    event.preventDefault();
    const level = Number(document.getElementById("newCategoryDialog").dataset.level);
    const created = await app().api("/api/product-categories", {
      method: "POST",
      body: JSON.stringify({
        category_level: level,
        parent_category_id: level === 2 ? document.getElementById("newCategoryParent").value : null,
        category_name: document.getElementById("newCategoryName").value.trim(),
      }),
    });
    document.getElementById("newCategoryDialog").close();
    state.page = 1;
    await reload("分类已新增", created.dashboard_refresh);
  }

  function resolveAutoCategory(result) {
    document.getElementById("autoCategoryDialog").close();
    state.confirmResolve?.(result);
    state.confirmResolve = null;
  }

  function guarded(action) {
    return async (event) => {
      try {
        await action(event);
      } catch (error) {
        app().toast(error.message, true);
      }
    };
  }

  function bind() {
    root().querySelectorAll(".catalog-subtab").forEach((button) => {
      button.addEventListener("click", guarded(async () => {
        root().querySelectorAll(".catalog-subtab").forEach((item) => item.classList.remove("is-active"));
        button.classList.add("is-active");
        state.view = button.dataset.view;
        state.page = 1;
        document.getElementById("catalogSearch").value = "";
        document.getElementById("catalogStatus").value = "all";
        updateToolbarForView();
        await loadActiveView();
      }));
    });
    document.getElementById("addCatalogRecord").addEventListener("click", openAddDialog);
    document.getElementById("newProductForm").addEventListener("submit", guarded(addProduct));
    document.getElementById("newCategoryForm").addEventListener("submit", guarded(addCategory));
    root().querySelectorAll(".close-dialog").forEach((button) =>
      button.addEventListener("click", () => button.closest("dialog").close()));
    document.getElementById("cancelAutoCategory").addEventListener("click", () => resolveAutoCategory(false));
    document.getElementById("confirmAutoCategory").addEventListener("click", () => resolveAutoCategory(true));
    document.getElementById("catalogSearch").addEventListener("input", () => {
      clearTimeout(state.searchTimer);
      state.searchTimer = setTimeout(guarded(async () => {
        state.page = 1;
        await loadActiveView();
      }), 280);
    });
    document.getElementById("catalogStatus").addEventListener("change", guarded(async () => {
      state.page = 1;
      await loadActiveView();
    }));
  }

  async function activate() {
    if (state.loading) return;
    if (!state.initialized) {
      layout();
      state.initialized = true;
    }
    state.loading = true;
    try {
      await reload();
    } catch (error) {
      app().toast(error.message, true);
      document.getElementById("catalogTableShell").innerHTML = `<div class="product-empty">读取失败：${esc(error.message)}</div>`;
    } finally {
      state.loading = false;
    }
  }

  window.productCategoryModule = { activate };
})();
