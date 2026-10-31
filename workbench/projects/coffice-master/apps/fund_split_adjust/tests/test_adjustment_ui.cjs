const assert = require('node:assert/strict');
const path = require('node:path');

const nodeModules = process.env.CODEX_NODE_MODULES;
if (!nodeModules) throw new Error('请设置 CODEX_NODE_MODULES');
const { chromium } = require(path.join(nodeModules, 'playwright'));
const { openAuthenticated } = require('./ui_test_helpers.cjs');

(async () => {
  const executablePath = process.env.BROWSER_EXECUTABLE || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
  const browser = await chromium.launch({ headless: true, executablePath });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await openAuthenticated(page);
    await page.waitForFunction(() => typeof state !== 'undefined' && Boolean(document.querySelector('#batchSelect')?.value && state.statement?.rows?.length));

    const result = await page.evaluate(async () => {
      const batchId = document.querySelector('#batchSelect').value;
      const response = await fetch(`/api/statement/${batchId}?page_size=200`);
      const payload = await response.json();
      const statement = payload.data;
      let index = statement.rows.findIndex(parent => parent.split_rows.length === 1 &&
        parent.split_rows.some(row => Math.abs(Number(row.adjusted_diff || 0)) >= 0.005)
      );
      if (index < 0) index = statement.rows.findIndex(parent =>
        parent.split_rows.some(row => Math.abs(Number(row.adjusted_diff || 0)) >= 0.005)
      );
      if (index < 0) return { skipped: true };

      state.pages.statement = Math.floor(index / state.pageSize) + 1;
      await loadStatement();
      const parent = statement.rows[index];
      const original = parent.split_rows.reduce((sum, row) => sum + Number(row.original_amount || 0), 0);
      const diff = parent.split_rows.reduce((sum, row) => sum + Number(row.adjusted_diff || 0), 0);
      const stack = document.querySelector('.amount-adjustment');
      const adjustButton = document.querySelector('tr.adjusted [data-adjust]');
      const buttonAmount = adjustButton?.dataset.amount;
      adjustButton?.click();
      const modalAmount = document.querySelector('#adjustAmount')?.value;
      document.querySelector('#modal')?.close();
      const probe = document.createElement('div');
      probe.className = 'amount-adjustment';
      probe.innerHTML = '<span class="adjusted-diff increase">↑多 1.00</span><span class="adjusted-diff decrease">↓少 1.00</span><input class="split-amount-input" value="1.00">';
      document.body.appendChild(probe);
      const styleOf = element => {
        const style = getComputedStyle(element);
        return { color: style.color, fontSize: style.fontSize, fontWeight: style.fontWeight };
      };
      return {
        skipped: false,
        current: stack?.querySelector('.adjusted-current')?.textContent,
        source: stack?.querySelector('.adjusted-source')?.textContent,
        difference: stack?.querySelector('.adjusted-diff')?.textContent,
        expectedCurrent: money(original + diff),
        expectedSource: money(original),
        expectedDiff: money(Math.abs(diff)),
        direction: diff > 0 ? '↑多' : '↓少',
        buttonAmount,
        modalAmount,
        expectedRowAmount: parent.split_rows[0].adjusted_amount,
        styles: {
          current: styleOf(stack.querySelector('.adjusted-current')),
          source: styleOf(stack.querySelector('.adjusted-source')),
          difference: styleOf(stack.querySelector('.adjusted-diff')),
          increase: styleOf(probe.querySelector('.increase')),
          decrease: styleOf(probe.querySelector('.decrease')),
          splitInput: styleOf(probe.querySelector('.split-amount-input')),
          debit: styleOf(document.querySelector('.debit-amount')),
          credit: styleOf(document.querySelector('.credit-amount')),
        },
      };
    });

    if (result.skipped) {
      console.log('当前没有调账数据，跳过页面金额展示断言');
      return;
    }
    assert.equal(result.current, result.expectedCurrent);
    assert.match(result.source, new RegExp(result.expectedSource.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
    assert.match(result.difference, new RegExp(`${result.direction} ${result.expectedDiff.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`));
    assert.equal(Number(result.buttonAmount), Number(result.expectedRowAmount));
    assert.equal(Number(result.modalAmount), Number(result.expectedRowAmount));
    assert.deepEqual(result.styles.current, { color: 'rgb(210, 26, 67)', fontSize: '15px', fontWeight: '700' });
    assert.equal(result.styles.source.fontSize, '10px');
    assert.equal(result.styles.difference.fontSize, '11px');
    assert.equal(result.styles.increase.color, 'rgb(82, 196, 26)');
    assert.equal(result.styles.decrease.color, 'rgb(251, 105, 79)');
    assert.equal(result.styles.debit.color, 'rgb(210, 26, 67)');
    assert.equal(result.styles.credit.color, 'rgb(56, 158, 50)');
    assert.equal(result.styles.debit.fontSize, '15px');
    assert.equal(result.styles.debit.fontWeight, '700');
    assert.equal(result.styles.credit.fontSize, '15px');
    assert.equal(result.styles.credit.fontWeight, '700');
    assert.equal(result.styles.splitInput.fontSize, '15px');
    assert.equal(result.styles.splitInput.fontWeight, '700');

    const withdrawUi = await page.evaluate(() => {
      state.statement.summary.is_submitted = true;
      renderStatement();
      const button = document.querySelector('#withdrawSubmit');
      const visible = !button.hidden;
      button.click();
      const title = document.querySelector('#modalTitle').textContent;
      const reasonExists = Boolean(document.querySelector('#withdrawReason'));
      const submittedDisabled = document.querySelector('#submitBatch').disabled;
      document.querySelector('#modal').close();
      return { visible, title, reasonExists, submittedDisabled };
    });
    assert.deepEqual(withdrawUi, { visible: true, title: '撤回提交', reasonExists: true, submittedDisabled: true });

    const splitResult = await page.evaluate(async () => {
      const batchId = document.querySelector('#batchSelect').value;
      const response = await fetch(`/api/statement/${batchId}?page_size=200`);
      const statement = (await response.json()).data;
      const index = statement.rows.findIndex(parent => parent.split_rows.length > 1);
      if (index < 0) return { skipped: true };
      const parent = statement.rows[index];
      state.pages.statement = Math.floor(index / state.pageSize) + 1;
      state.expandedOds.add(parent.ods_id);
      await loadStatement();
      const parentRow = document.querySelector('tr.split-parent');
      const parentButton = parentRow.querySelector('[data-adjust-parent]');
      const childRows = [...document.querySelectorAll('tr.split-child')];
      parentButton.click();
      const modalAmount = document.querySelector('#adjustAmount').value;
      document.querySelector('#modal').close();
      const childButton = childRows[0].querySelector('[data-adjust-child]');
      childButton.click();
      const childModalAmount = document.querySelector('#adjustAmount').value;
      document.querySelector('#modal').close();
      return {
        skipped: false,
        parentId: Number(parentButton.dataset.adjustParent),
        expectedParentId: Number(parent.ods_id),
        parentButtonHasChildId: parentButton.hasAttribute('data-adjust'),
        modalAmount: Number(modalAmount),
        expectedParentAmount: parent.split_rows.reduce((sum, row) => sum + Number(row.adjusted_amount), 0),
        childIds: childRows.slice(0, -1).map(row => Number(row.querySelector('[data-adjust-child]').dataset.adjustChild)),
        expectedChildIds: parent.split_rows.slice(0, -1).map(row => Number(row.split_id)),
        childModalAmount: Number(childModalAmount),
        expectedChildModalAmount: Number(parent.split_rows[0].adjusted_amount),
        autoHasAdjustButton: Boolean(childRows.at(-1).querySelector('[data-adjust-child]')),
        childAmounts: childRows.map(row => row.querySelector('.split-current-amount')?.textContent),
        expectedChildAmounts: parent.split_rows.map(row => money(row.adjusted_amount)),
        childHasAdjustmentDetail: childRows.some(row => row.querySelector('.adjusted-source, .adjusted-diff')),
      };
    });
    assert.equal(splitResult.skipped, false, '当前批次应至少包含一条拆分母行');
    assert.equal(splitResult.parentId, splitResult.expectedParentId);
    assert.equal(splitResult.parentButtonHasChildId, false);
    assert.equal(splitResult.modalAmount, splitResult.expectedParentAmount);
    assert.deepEqual(splitResult.childIds, splitResult.expectedChildIds);
    assert.equal(splitResult.childModalAmount, splitResult.expectedChildModalAmount);
    assert.equal(splitResult.autoHasAdjustButton, false);
    assert.deepEqual(splitResult.childAmounts, splitResult.expectedChildAmounts);
    assert.equal(splitResult.childHasAdjustmentDetail, false);
    if (process.env.SCREENSHOT_PATH) {
      await page.screenshot({ path: process.env.SCREENSHOT_PATH, fullPage: true });
    }
    const managementResult = await page.evaluate(async () => {
      const mergedSearch = {
        oldAccountSearchExists: Boolean(document.querySelector('#accountNameFilter')),
        keywordCount: document.querySelectorAll('#statementKeyword').length,
        placeholder: document.querySelector('#statementKeyword')?.placeholder,
        transactionTypeFilterExists: Boolean(document.querySelector('#transactionType')),
        expenseTypeOptions: [...document.querySelectorAll('#expenseTypeFilter option')].map(option => ({
          value: option.value,
          label: option.textContent.trim(),
        })),
      };
      switchPage('types');
      await loadTypes();
      const typeButtons = [...document.querySelectorAll('[data-toggle-type]')].map(button => ({
        label: button.textContent.trim(),
        color: getComputedStyle(button).color,
      }));
      switchPage('accounts');
      await loadAccounts();
      const accountButtons = [...document.querySelectorAll('[data-toggle-account]')].map(button => ({
        label: button.textContent.trim(),
        color: getComputedStyle(button).color,
      }));
      switchPage('logs');
      await loadLogs();
      const logFilters = {
        typeValues: [...document.querySelectorAll('#logType option')].map(option => option.value).filter(Boolean),
        operatorTag: document.querySelector('#logOperator')?.tagName,
        operatorOptions: [...document.querySelectorAll('#logOperator option')].map(option => option.textContent.trim()),
        searchPlaceholder: document.querySelector('#logKeyword')?.placeholder,
      };
      return { mergedSearch, buttons: [...typeButtons, ...accountButtons], logFilters };
    });
    assert.equal(managementResult.mergedSearch.oldAccountSearchExists, false);
    assert.equal(managementResult.mergedSearch.keywordCount, 1);
    assert.match(managementResult.mergedSearch.placeholder, /时间.*日期.*类型.*账号.*金额.*费用类型.*入账.*摘要/);
    assert.equal(managementResult.mergedSearch.transactionTypeFilterExists, false);
    assert.deepEqual(managementResult.mergedSearch.expenseTypeOptions.slice(0, 2), [
      { value: '', label: '全部费用类型' },
      { value: 'unassigned', label: '未分配' },
    ]);
    assert.ok(managementResult.mergedSearch.expenseTypeOptions.length > 2);
    assert.ok(managementResult.buttons.length > 0);
    managementResult.buttons.forEach(button => {
      assert.equal(button.color, button.label === '停用' ? 'rgb(250, 140, 22)' : 'rgb(82, 196, 26)');
    });
    const expectedLogTypes = [
      'import', 'split', 'cancel_split', 'adjust', 'child_adjust', 'one_click_allocate',
      'batch_assign', 'summary', 'remark', 'submit', 'withdraw_submit', 'type_create', 'type_update',
      'type_toggle', 'type_delete', 'account_create', 'account_update', 'account_toggle', 'account_delete',
    ];
    expectedLogTypes.forEach(type => assert.ok(managementResult.logFilters.typeValues.includes(type)));
    assert.equal(managementResult.logFilters.operatorTag, 'SELECT');
    assert.ok(managementResult.logFilters.operatorOptions.length > 1);
    assert.match(managementResult.logFilters.searchPlaceholder, /日志编号.*时间.*操作人.*类型.*对象.*金额.*IP/);
    console.log('调账金额页面展示测试通过');
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
