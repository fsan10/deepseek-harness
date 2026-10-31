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
    await page.waitForFunction(() => typeof state !== 'undefined' && Boolean(state.statement?.rows?.length));
    const result = await page.evaluate(() => {
      const calculations = {
        add: calculateAmountExpression('+100', 1000),
        subtract: calculateAmountExpression('-100', 1000),
        multiply: calculateAmountExpression('*1.2', 1000),
        divide: calculateAmountExpression('/4', 1000),
        precedence: calculateAmountExpression('1000+100*2', 1000),
      };
      let divideZero = '';
      try { calculateAmountExpression('/0', 1000) } catch (error) { divideZero = error.message }

      const originalStatement = state.statement;
      const originalExpanded = state.expandedOds;
      const parent = structuredClone(originalStatement.rows[0]);
      const row = parent.split_rows[0];
      parent.split_rows = [row];
      row.original_amount = 900;
      row.adjusted_diff = 100;
      row.adjusted_amount = 1000;
      state.statement = {
        ...originalStatement,
        rows: [parent],
        summary: { ...originalStatement.summary, is_submitted: false },
      };
      state.expandedOds = new Set();
      renderStatement();
      const restoreButton = document.querySelector('[data-restore]');
      const restoreUi = {
        exists: Boolean(restoreButton),
        label: restoreButton?.textContent.trim(),
        bound: typeof restoreButton?.onclick === 'function',
        color: restoreButton ? getComputedStyle(restoreButton).color : '',
      };

      document.querySelector('[data-adjust]').click();
      const input = document.querySelector('#adjustAmount');
      input.value = '+100';
      input.dispatchEvent(new Event('input', { bubbles: true }));
      const livePreview = document.querySelector('#amountCalculatorPreview').textContent.trim();
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
      const committedValue = input.value;
      const inputType = input.type;
      const help = document.querySelector('.amount-calculator-help').textContent.trim();
      document.querySelector('#modal').close();

      state.statement = originalStatement;
      state.expandedOds = originalExpanded;
      renderStatement();
      return { calculations, divideZero, restoreUi, livePreview, committedValue, inputType, help };
    });

    assert.deepEqual(result.calculations, {
      add: 1100,
      subtract: 900,
      multiply: 1200,
      divide: 250,
      precedence: 1200,
    });
    assert.match(result.divideZero, /除数不能为0/);
    assert.equal(result.restoreUi.exists, true);
    assert.equal(result.restoreUi.label, '复原');
    assert.equal(result.restoreUi.bound, true);
    assert.equal(result.restoreUi.color, 'rgb(114, 46, 209)');
    assert.equal(result.livePreview, '= 1,100.00');
    assert.equal(result.committedValue, '1100.00');
    assert.equal(result.inputType, 'text');
    assert.match(result.help, /\+100.*-50.*\*1\.2.*\/2/);
    console.log('调账计算器页面回测通过：加减乘除、实时预览、Enter 回填及复原按钮均符合预期');
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
