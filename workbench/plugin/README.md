# dsh-workbench（bundle）

工作台的 dsh 插件包。Host 侧注册 `/api/workbench/*` 与 4 个 tool；Client 侧注册侧边栏入口与 `main` 全局面板。

安装：

```powershell
pnpm dsh plugin --profile web add "link:D:/fsan10/deepseek-harness/workbench/plugin"
```

组成：

| 文件 | 作用 |
|---|---|
| `lib/index.js` | 注册表、状态、执行器、审计、HTTP 路由、4 个 tool |
| `lib/client.js` | 侧边栏图标 + `main` 面板（控制室与 14 页渲染） |
| `lib/{registry,status,runner,audit,views,db,yaml}.js` | Host 逻辑，无第三方依赖 |
| `cordis.patch.yml` | 只 insert 一行 `dsh-workbench`，不覆盖官方插件 |

工作区根目录默认由插件包位置推导（`plugin/lib/../../`），也可用环境变量 `DSH_WORKBENCH_ROOT` 指定。
数据目录 `var/` 不入库；`project.yaml` 与 `views/*.view.json` 才是需要版本管理的内容。
