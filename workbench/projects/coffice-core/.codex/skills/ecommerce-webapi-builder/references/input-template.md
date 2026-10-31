# 电商 WebAPI 开发输入模板

## 用户唯一需要提供的内容

```text
使用 $ecommerce-webapi-builder
平台：拼多多
报表：订单
Profile：PDD-拼多多-MOCK饮品旗舰店
开发 WebAPI 下载脚本
```

AI 随后必须自行完成：

1. 通过 Cloak Login MCP 检查、精确匹配并按需启动 Profile。
2. 取得当前 `wsEndpoint`。
3. 在项目中搜索对应的现有 DOM 下载脚本。
4. 启动技能自带 HTTP 监听器。
5. 用现有 DOM 脚本产生一次完整请求链。
6. 分析 `.codex_tmp/captures/` 中的 JSON。
7. 按 [正式实现规范](implementation-standard.md) 编写混合式 WebAPI 下载脚本，并接入当前平台统一入口。
8. 完成最低测试矩阵和一次真实 WebAPI 端到端下载。

## 不应要求用户提供

- CDP endpoint 或 debug port。
- DOM 脚本路径；AI 应先用 `rg` 搜索。
- 页面 URL、日期组件、下拉框或下载按钮 DOM。
- API 地址、请求头、Payload、响应示例或 HAR。
- Cookie、账号密码、验证码、ticket、token、签名和风控字段。

只有以下阻塞才询问用户：

- Cloak Login MCP 不可用，或 Profile 启动后始终没有 endpoint。
- Profile 名称不存在或有多个完全同名结果。
- 项目中没有相应 DOM 脚本，且无法从已有代码确定首页入口；此时只询问首页菜单路径或一个 XPath。
- 出现验证码、短信、人机验证或权限不足，需要返回 `NEEDS_HUMAN`。

## 可选业务覆盖

用户只在需要改变项目默认行为时补充：

```text
日期：昨天 / YYYY-MM-DD 至 YYYY-MM-DD
筛选：例如 资金类型=现金，流水类型=支出
无数据：0 条直接结束
输出：原始文件目录
后处理：不解压不校验 / 解压 / 校验 / 归档
```

这些值用于构造 WebAPI Payload 和验收结果，不授权重新实现对应页面控件。
