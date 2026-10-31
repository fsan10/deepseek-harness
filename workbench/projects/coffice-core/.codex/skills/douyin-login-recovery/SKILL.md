---
name: douyin-login-recovery
description: 在抖店 profile 登录态失效时复用已保存的邮箱凭据、勾选协议、等待可选人机验证并选择 profile 对应店铺；适用于订单、资金/结算和千川下载脚本。
---

# 抖店登录态恢复

适用于 `fxg.jinritemai.com` 的订单、资金/结算和千川下载入口。脚本启动或深链跳转后，先判断当前页面是业务页、登录页还是登录后的店铺选择页；不要把登录页当成业务页面继续等待固定业务选择器。

## profile 与店铺

- 只使用用户指定或当前运行 profile；从 profile `note` 的 `platform/company/shop` 键值读取业务参数，不凭文件名、profile 标题或店铺列表顺序推断公司。
- 当前登录成功后可能仍停留在 `/login/common`，但页面正文已变为“请选择店铺”；此时以目标 `shop` 的完整文本精确匹配店铺卡片，不能固定点击第一项。

## 登录流程

复用 `scripts/auto_download/playwright/douyin_login.py`，不要在订单、账单、千川脚本内复制登录逻辑：

1. 目标页重定向到登录页时，使用 `//*[@d="root"]/div/div[1]/div/div/div/div` 作为首选登录根节点，并保留 `#ecomLoginForm`、邮箱输入框和页面标题作为版本兼容回退。
2. 点击邮箱登录 `//*[@id="ecomLoginForm"]/section/div[2]/div[2]`。账号和密码由当前 profile 的已保存凭据自动填充；不得读取、打印、写入状态文件或通过命令行传递凭据。
3. 使用 `//*[@id="root"]/div/div[1]/div/div/div/div/div[2]/div[4]/div[1]/label/span/input` 勾选用户协议。当前版本勾选后可能立即提交，旧版本仍需点击“登录”，所以只在登录表单仍可见且按钮可用时补点一次。
4. 登录成功后，若页面出现店铺列表 `//*[@id="root"]/div/div[1]/div/div/div/div/div/div/div[3]`，按 `shop` 的完整可见文本选择对应卡片，并等待回到首页或目标业务页。

## 滑块处理边界

- 只有实际出现 `//*[@id="captcha_container"]/iframe`（或等价可见 iframe）时才进入验证码分支；没有滑块就继续正常登录。
- 滑块是第三方人机校验。本项目脚本只检测 iframe、监听 `/captcha/verify` 的 HTTP 500 失败信号、保留当前 profile 页面并等待人工完成；不自动识别缺口、不模拟绕过行为、不记录验证 URL、响应体、token 或凭据。
- HTTP 500 表示本轮失败；页面会刷新下一题，脚本继续等待而不重复提交登录。超时退出码为 1，页面留给人工接管。
- 网易易盾基础示例 `scripts/auto_download/playwright/jigsaw_slider_demo.py` 仅用于合法测试页的 iframe/坐标诊断和人工提供偏移量的 UI 拖拽验证；不把它当作抖音生产验证码求解器。
- 结构参考：[网易易盾滑动拼图体验页](https://dun.163.com/trial/jigsaw) 与 [滑动验证码教学文章](https://blog.csdn.net/qq_31907917/article/details/141535006)；这些资料中的图像识别/自动过验证方案不属于本项目生产登录流程。

## 验收

- 登录态有效：脚本直接进入业务流程，不点击登录入口。
- 登录态失效且无滑块：邮箱入口、协议复选框、自动登录和目标店铺选择全部完成。
- 登录态失效且有滑块：日志只出现“检测到登录滑块”和非敏感失败状态；人工完成后脚本继续店铺选择/业务流程。
- 页面改版时先检查 URL、可见节点和目标店铺文本，再调整选择器；不要把隐藏旧节点或固定序号当作成功依据。
