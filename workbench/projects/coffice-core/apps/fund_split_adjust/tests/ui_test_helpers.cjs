const assert = require('node:assert/strict');

async function openAuthenticated(page) {
  const base = process.env.UI_TEST_BASE || 'http://127.0.0.1:8770';
  await page.goto(base, { waitUntil: 'networkidle' });
  if ((await page.title()).startsWith('登录')) {
    const username = process.env.UI_TEST_USERNAME;
    const password = process.env.UI_TEST_PASSWORD;
    assert.ok(username && password, '启用登录后必须设置 UI_TEST_USERNAME 和 UI_TEST_PASSWORD');
    await page.getByRole('textbox', { name: '用户名' }).fill(username);
    await page.getByRole('textbox', { name: '密码' }).fill(password);
    const loginResponse = page.waitForResponse(response => response.url().endsWith('/api/auth/login'));
    await page.getByRole('button', { name: '登录' }).click();
    const response = await loginResponse;
    assert.equal(response.status(), 200, '测试账号登录失败');
    await page.waitForFunction(() => !document.title.startsWith('登录'));
    // 动态权限导航可能把超级管理员送到排序第一的看板；这些用例固定回测银行首页。
    await page.goto(base, { waitUntil: 'networkidle' });
  }
}

module.exports = { openAuthenticated };
