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
    await page.waitForFunction(() => typeof state !== 'undefined' && Boolean(state.statement?.summary));

    const result = await page.evaluate(() => {
      const originalSummary = { ...state.statement.summary };

      state.statement.summary.is_submitted = true;
      renderStatement();
      const submitted = {
        withdrawHidden: document.querySelector('#withdrawSubmit').hidden,
        submitDisabled: document.querySelector('#submitBatch').disabled,
        submitLabel: document.querySelector('#submitBatch').textContent.trim(),
      };

      state.statement.summary.is_submitted = false;
      state.statement.summary.is_balanced = true;
      state.statement.summary.unassigned_count = 0;
      renderStatement();
      const newlyImported = {
        withdrawHidden: document.querySelector('#withdrawSubmit').hidden,
        submitDisabled: document.querySelector('#submitBatch').disabled,
        submitLabel: document.querySelector('#submitBatch').textContent.trim(),
      };

      state.statement.summary = originalSummary;
      renderStatement();
      return { submitted, newlyImported };
    });

    assert.deepEqual(result.submitted, {
      withdrawHidden: false,
      submitDisabled: true,
      submitLabel: '已提交',
    });
    assert.deepEqual(result.newlyImported, {
      withdrawHidden: true,
      submitDisabled: false,
      submitLabel: '提交',
    });
    console.log('批次提交按钮状态回测通过：已提交批次显示撤回，未提交新批次隐藏撤回并恢复提交')
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
