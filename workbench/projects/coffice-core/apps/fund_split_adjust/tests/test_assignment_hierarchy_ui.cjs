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
    await page.waitForFunction(() => typeof state !== 'undefined' && Boolean(state.statement));
    const result = await page.evaluate(() => {
      const originalAccounts = state.accounts;
      state.accounts = [
        { id: 11, name: '二级A', expense_types: [{ id: 1, name: '一级A' }] },
        { id: 22, name: '二级B', expense_types: [{ id: 2, name: '一级B' }] },
        { id: 33, name: '二级AB', expense_types: [{ id: 1, name: '一级A' }, { id: 2, name: '一级B' }] },
      ];
      const filteredTrigger = document.createElement('button');
      filteredTrigger.dataset.field = 'account_entry_id';
      filteredTrigger.dataset.expenseId = '1';
      filteredTrigger.dataset.value = '';
      filteredTrigger.getBoundingClientRect = () => ({ left: 10, top: 10, bottom: 42 });
      document.body.appendChild(filteredTrigger);
      const filteredIds = assignItems(filteredTrigger).map(item => item.id);

      const emptyTrigger = document.createElement('button');
      emptyTrigger.dataset.field = 'account_entry_id';
      emptyTrigger.dataset.expenseId = '';
      emptyTrigger.dataset.value = '';
      emptyTrigger.getBoundingClientRect = () => ({ left: 10, top: 10, bottom: 42 });
      document.body.appendChild(emptyTrigger);
      openAssignDropdown(emptyTrigger);
      const noExpense = {
        itemCount: state.assignContext.items.length,
        searchDisabled: document.querySelector('#assignSearch').disabled,
        placeholder: document.querySelector('#assignSearch').placeholder,
        emptyText: document.querySelector('#assignOptions').textContent.trim(),
      };
      closeAssignDropdown(false);
      filteredTrigger.remove();
      emptyTrigger.remove();
      state.accounts = originalAccounts;
      return { filteredIds, noExpense };
    });

    assert.deepEqual(result.filteredIds, [11, 33]);
    assert.deepEqual(result.noExpense, {
      itemCount: 0,
      searchDisabled: true,
      placeholder: '请先选择费用类型',
      emptyText: '请先选择费用类型',
    });
    console.log('一、二级分类页面回测通过：入账选项只显示当前费用类型下的二级分类');
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
