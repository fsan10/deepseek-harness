# 经营配置中心正式环境 Docker 部署手册

版本：2026-08-20  
适用部署包：`coffice_production_deploy`

## 1. 部署目标与边界

本部署包在目标电脑运行以下容器：

- `bootstrap`：幂等升级 `coffice_production` 结构并写入必要初始化配置，成功后退出。
- `init-admin`：仅在管理员不存在时创建首次超级管理员，后续部署不会重置密码。
- `web`：经营配置中心、银行资金、达播运营、数据导入、平台费用、AI管理和DataEase嵌入代理。
- `worker`：串行处理文件导入、Loader和ETL任务。
- `scheduler`：每天指定时间创建一次全量ETL任务，数据库级防重复。

目标电脑已经运行的 PostgreSQL 和 DataEase 不会由本 Compose 重建、停止或删除。默认通过宿主机已发布端口访问：PostgreSQL `5432`、DataEase `8100`。

部署包明确不包含：

- `scripts/auto_download` 及 Playwright/Cloak 登录下载代码；这些继续留在原电脑运行。
- 测试业务数据、ODS/DWD/DWS/ADS事实数据、数据库dump、上传文件和ETL历史。
- `.vendor` 中的 Windows 二进制依赖、`node_modules`、测试目录、原型项目和本地临时文件。
- 任何明文密码、Token、API Key或AI加密主密钥。

原电脑的自动下载程序可以继续调用新服务器的数据导入API，地址改为新服务器IP，并使用 `.env` 中配置的 `INGEST_ROBOT_TOKEN`。

## 2. 当前数据库迁移结果

现有正式数据库名称为 `coffice_production`。2026-08-20 已完成：

- 239 张正式保留表、2 个视图、3 个函数、2 个触发器（其中 205 张来自结构迁移清单，34 张为当前应用兼容表）。
- 新增 `iam`、`config`、`ai` schema。
- 新增多工作表上传批次关联结构和小红书结算扩展字段。
- 新增平台费用 `source_role`、`metric_role`、`dedup_rule_code` 字段、约束和索引。
- 同步24条公司店铺DIM、银行配置字典、商务人员、达人归属、3条0元GMV目标、商品目录、商品编码映射、平台费用分类和映射；非零 GMV 目标不作为正式库初始化数据。
- 同步54条IAM权限资源、2个DataEase看板配置。
- 仅以内存方式迁移AI模型、AI只读数据源和飞书应用密文；密文没有写入部署文件。
- AI只读角色已获得 `coffice_production` 的 `ads`、`dim` 只读权限。

没有迁移任何订单、资金、结算、银行流水、上传任务、ETL历史、AI会话、消息、查询审计、登录历史或操作日志。

明确排除17张旧表：旧独立达人佣金ADS/DWD/DWS、旧天猫通用资金ODS和天猫订单历史备份表。用途不能确认的两张银行兼容表和 `ai.tool_execution` 仍按安全原则保留空结构。

## 3. 目标电脑前置检查

以管理员PowerShell执行：

```powershell
docker version
docker compose version
docker ps
```

最低要求：

- Docker Engine或Docker Desktop正在运行。
- Docker Compose v2可用。
- PostgreSQL容器向宿主机发布 `5432`，且数据库 `coffice_production` 已存在。
- DataEase容器向宿主机发布 `8100`。
- 目标电脑至少有4GB可用内存和10GB可用磁盘空间。
- 防火墙允许内网访问经营配置中心端口 `8770`；如需嵌入看板，允许 `8101`。

如果PostgreSQL没有发布到宿主机端口，应把本Compose加入PostgreSQL所在的外部Docker网络，并将 `PGHOST` 改为PostgreSQL容器服务名。不要填写 `127.0.0.1`，因为容器内的 `127.0.0.1` 指向容器自身。

## 4. 复制部署包

将整个目录复制到目标电脑，例如：

```text
D:\coffice_production_deploy
```

以下命令均在该目录执行：

```powershell
Set-Location D:\coffice_production_deploy
```

不要只复制 `apps`；`etl`、`sql`、`scripts/production_db/generated` 和 `deploy/production` 都是运行所必需的。

## 5. 配置 `.env`

```powershell
Copy-Item .\deploy\production\.env.example .\.env
notepad .\.env
```

`.env` 不得提交到Git或发送到聊天工具。逐项配置：

| 变量 | 是否必填 | 说明 |
|---|---:|---|
| `PGHOST` | 是 | 数据库地址。PostgreSQL发布到宿主机时使用 `host.docker.internal`。 |
| `PGPORT` | 是 | 默认 `5432`。 |
| `PGDATABASE` | 是 | 必须为 `coffice_production`，不得填 `mock_coffice`。 |
| `PGUSER` / `PGPASSWORD` | 是 | 当前迁移和运行账号。部署稳定后建议拆分DDL账号与最小权限应用账号。 |
| `DATABASE_ADMIN_URL` | 条件必填 | 仅当数据库尚不存在并使用 `-CreateDatabase` 时填写，格式为 `postgresql://用户:密码@主机:端口/postgres`。 |
| `INITIAL_ADMIN_USERNAME` | 是 | 首次超级管理员用户名，小写字母开头。 |
| `INITIAL_ADMIN_PASSWORD` | 是 | 至少12位并包含大小写字母、数字和特殊字符。首次创建后立即从 `.env` 移除。 |
| `AI_CONFIG_ENCRYPTION_KEY` | 是 | url-safe base64编码的32字节密钥。使用已迁移AI配置时必须与原电脑用户环境变量完全一致。 |
| `INGEST_ROBOT_TOKEN` | 是 | 原电脑自动下载程序调用上传API使用的Bearer Token，应为随机长字符串。 |
| `AUTOMATION_ROBOT_TOKEN` | 验证码转发启用时是 | 原电脑自动化脚本调用 `/api/automation/verification/*` 使用的Bearer Token。建议与 `INGEST_ROBOT_TOKEN` 分开生成；未设置时服务端兼容回退到上传令牌。 |
| `INGEST_FILE_ROOT` | 是 | 容器内保持 `/app/.uploads/file_ingest`。 |
| `DATAEASE_BASE_URL` | 是 | 容器访问DataEase的地址，默认 `http://host.docker.internal:8100`。看板链接的内部地址可以与此不同，但必须列在 `DATAEASE_PUBLIC_ORIGINS`。 |
| `DATAEASE_PUBLIC_ORIGINS` | 是 | 浏览器可访问的DataEase真实地址，例如 `http://192.168.77.111:8100`。多个地址用逗号分隔；代理会接受这些地址下的公共分享链接。 |
| `DATAEASE_PROXY_PUBLIC_URL` | 是 | 浏览器访问嵌入代理的地址，例如 `http://192.168.77.111:8101`。 |
| `AUTH_COOKIE_SECURE` | 是 | 内网HTTP为 `false`；配置HTTPS后必须为 `true`。 |
| `FEISHU_AI_LONG_CONNECTION_ENABLED` | 否 | 已确认飞书配置可用后改为 `true`。 |

生成新AI主密钥的方法（仅用于没有历史AI密文的新环境）：

```powershell
$keyBytes = [byte[]]::new(32)
[Security.Cryptography.RandomNumberGenerator]::Fill($keyBytes)
[Convert]::ToBase64String($keyBytes).TrimEnd('=').Replace('+','-').Replace('/','_')
```

本项目已有AI密文，正式部署必须安全复制原电脑现有的 `AI_CONFIG_ENCRYPTION_KEY`，不能生成新值，否则服务会启动但既有模型、数据源和飞书密文无法解密。

## 6. DataEase地址确认

当前初始化看板链接指向 `http://192.168.77.111:8100`。如果目标电脑IP不同：

1. 将 `.env` 中 `DATAEASE_PUBLIC_ORIGINS`、`DATAEASE_PROXY_PUBLIC_URL` 改为目标IP。
2. 首次登录后进入“系统管理 → 看板管理”。
3. 将两个看板的分享链接改为目标DataEase的实际 `/#/de-link/...` 地址。

数据库只校验DataEase公共链接格式；允许来源由 `DATAEASE_PUBLIC_ORIGINS` 白名单控制。

## 7. 一键部署

数据库已存在时：

```powershell
.\deploy\production\deploy.ps1
```

数据库不存在且已经配置 `DATABASE_ADMIN_URL` 时：

```powershell
.\deploy\production\deploy.ps1 -CreateDatabase
```

脚本执行顺序：Compose校验 → 构建镜像 → 可选创建数据库 → 幂等数据库升级 → 首次管理员初始化 → 启动Web、Worker和Scheduler。

重复执行不会重复建表、重复写入配置或重置管理员密码：

```powershell
.\deploy\production\deploy.ps1
```

仅修改 `.env` 后无需重建镜像：

```powershell
.\deploy\production\deploy.ps1 -SkipBuild
```

如果更新了 `apps`、`etl`、`sql` 或 `scripts`，禁止使用 `-SkipBuild`。必须执行不带
`-SkipBuild` 的部署命令；脚本会注入新的构建指纹，确保 Worker、Scheduler 和 Web
不会继续复用旧镜像中的代码。

## 8. 部署验证

查看容器：

```powershell
docker compose --env-file .env -f deploy/production/compose.yml ps
```

预期：

- `bootstrap`、`init-admin` 为 `Exited (0)`。
- `web` 为 `Up (healthy)`。
- `worker`、`scheduler` 为 `Up`。

查看日志：

```powershell
docker compose --env-file .env -f deploy/production/compose.yml logs --tail 200 bootstrap
docker compose --env-file .env -f deploy/production/compose.yml logs --tail 200 web
docker compose --env-file .env -f deploy/production/compose.yml logs --tail 200 worker
docker compose --env-file .env -f deploy/production/compose.yml logs --tail 200 scheduler
```

浏览器访问：

```text
http://目标电脑IP:8770/login/
```

登录后按顺序验证：

1. 银行资金、达播运营、数据导入、平台费用、AI管理和经营配置导航可见。
2. 商务人员、达人归属、0元GMV目标、商品目录和编码映射有数据。
3. 数据导入页面能读取28类报表和24条店铺配置。
4. 上传一个小文件，提交后Worker日志出现Loader任务；正式测试文件必须由业务人员确认。
5. DataEase看板能加载；若不能，检查 `DATAEASE_BASE_URL` 与两项公开URL。
6. 经营配置页面在空库显示零值而不报缺表；其 `finance_operating_config` ETL 仍不加入夜间/手动全量刷新。
7. AI模型、正式只读数据源和飞书配置能执行“测试”；不得把数据库管理员账号配置为AI数据源。

确认首次管理员登录成功后，从 `.env` 删除 `INITIAL_ADMIN_PASSWORD`，再执行：

```powershell
.\deploy\production\deploy.ps1 -SkipBuild
```

`init-admin` 发现账号已存在会正常退出，不会修改现有密码。

## 9. 原电脑自动下载对接

自动下载脚本继续在原电脑运行。下载和改名完成后，将上传API基础地址改为：

```text
http://目标电脑IP:8770
```

请求头使用：

```text
Authorization: Bearer <INGEST_ROBOT_TOKEN>
```

自动下载目录不需要映射进Docker；文件通过HTTP上传后存入命名卷 `coffice-production-ingest-files`，Web与Worker共享该卷。

## 10. 日常运维

重启：

```powershell
docker compose --env-file .env -f deploy/production/compose.yml restart web worker scheduler
```

停止但保留数据库和上传卷：

```powershell
docker compose --env-file .env -f deploy/production/compose.yml stop
```

重新启动：

```powershell
docker compose --env-file .env -f deploy/production/compose.yml up -d
```

查看实时日志：

```powershell
docker compose --env-file .env -f deploy/production/compose.yml logs -f web worker scheduler
```

更新代码：用新的完整部署包覆盖到一个新目录，复制旧 `.env`，执行新目录的 `deploy.ps1`。不要直接删除旧目录；验证通过后再归档。

## 11. 备份与回滚

代码回滚：保留上一版部署目录和镜像标签，切回旧目录执行其 `deploy.ps1 -SkipBuild`。

数据库回滚原则：迁移脚本不提供自动 `DROP DATABASE` 或逆向删除列。升级前应由PostgreSQL管理员执行备份，例如：

```powershell
docker exec <postgres容器名> pg_dump -U postgres -Fc coffice_production -f /tmp/coffice_production_before_deploy.dump
docker cp <postgres容器名>:/tmp/coffice_production_before_deploy.dump .\backup\
```

发生问题时先停止 `web/worker/scheduler`，保留现场日志，再由DBA决定恢复备份。不得用 `mock_coffice` 覆盖正式库。

上传文件位于Docker命名卷：

```text
coffice-production-ingest-files
coffice-production-bank-uploads
```

执行 `docker compose down` 不会删除卷；禁止使用 `docker compose down -v`，除非已经备份且明确要永久删除上传文件。

## 12. 可直接交给目标电脑AI的执行指令

可以把下面内容连同部署包交给目标电脑上的AI：

```text
你正在目标Windows电脑上部署经营配置中心。项目目录为 D:\coffice_production_deploy。

要求：
1. 先读取 docs/deployment/production_docker_deployment.md 和 deploy/production/.env.example。
2. 只检查现有Docker、PostgreSQL和DataEase状态，不删除、重建或清空任何现有容器、数据库、卷。
3. 确认PostgreSQL宿主机端口、coffice_production数据库、DataEase宿主机端口和目标电脑内网IP。
4. 创建根目录.env，只填写环境变量；不得把密码、Token、AI_CONFIG_ENCRYPTION_KEY输出到聊天或日志。
5. PGDATABASE必须为coffice_production，禁止连接mock_coffice执行写操作。
6. 使用 deploy/production/deploy.ps1 一键部署；数据库已存在时不要传-CreateDatabase。
7. 等待bootstrap和init-admin退出码为0、web变为healthy、worker和scheduler为Up。
8. 检查四个服务最近200行日志，确认没有缺表、缺列、连接拒绝、密钥解密或DataEase代理错误。
9. 访问http://目标IP:8770/login/并按文档验证页面。不要自行上传业务文件或触发全量ETL，除非用户明确授权。
10. 测试结束不要停止正式容器；只报告部署结果、访问地址、容器状态、异常和仍需人工确认项。
```

## 13. 常见故障

`connection refused`：检查PostgreSQL是否发布5432、`PGHOST`是否为 `host.docker.internal`、Windows防火墙和PostgreSQL监听配置。

`未配置AI_CONFIG_ENCRYPTION_KEY`：`.env` 缺少密钥，或Compose未加载根目录 `.env`。

`InvalidTag`/解密失败：使用了新生成密钥。恢复原电脑同一 `AI_CONFIG_ENCRYPTION_KEY` 后重启Web。

Web正常但导入不执行：检查 `worker` 是否Up、命名卷是否同时挂载、`ops.worker_heartbeat`是否更新。

DataEase页面空白：检查 `DATAEASE_BASE_URL` 的容器可达性、公开URL是否使用浏览器可达IP，以及系统中的看板分享链接是否属于白名单来源。

`bootstrap`失败：查看其最后一个“步骤”名称。整个数据库事务已回滚；修复配置后重新执行 `deploy.ps1`，不要手工跳过失败DDL。
