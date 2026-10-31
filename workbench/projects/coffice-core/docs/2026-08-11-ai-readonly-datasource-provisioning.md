# AI PostgreSQL 专属只读账号与数据源配置标准

## 1. 目标与边界

为“AI 管理与数据分析中心”创建数据库专属只读账号，并安全配置到“AI 管理 → 数据源管理”。极简版不再提供应用层 AI 数据权限，因此数据库角色及数据源 schema 白名单共同决定 AI 最终能接触的数据范围。

禁止使用 `postgres`、项目服务账号或对象所有者账号执行 AI 查询；禁止修改 ODS；禁止在代码、SQL、文档、接口响应和日志中保存明文密码。

权限模式按安全性排序：表/视图白名单、schema 当前对象、schema 未来对象。默认使用前两种，不自动授权未来新表。

## 2. 当前测试库落地结果

- PostgreSQL：`192.168.77.111:5432/mock_coffice`
- 角色：`mock_ai_reader`
- 属性：`LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS`
- 连接上限：5
- 允许 schema：`ads`、`dim`
- 权限：数据库 `CONNECT`、schema `USAGE`、现有表/视图 `SELECT`
- 默认只读事务：`on`
- 查询/锁/空闲事务超时：30 秒、3 秒、30 秒
- 数据源编码：`mock_coffice_ai_readonly`
- 返回行数：不由应用自动限行；模型应优先在数据库聚合
- 目录扫描：32 个对象、424 个字段

未开放 ODS、DWD、DWS、IAM、AI 配置表或 `common`，也未自动授权未来新表。密码只以 PostgreSQL 密码哈希和应用 AES-GCM 密文保存。

## 3. PostgreSQL 模板

密码使用交互式 `\password` 或安全环境变量提供，不要写入 SQL 文件：

```sql
CREATE ROLE mock_ai_reader
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS
    CONNECTION LIMIT 5;

GRANT CONNECT ON DATABASE mock_coffice TO mock_ai_reader;
GRANT USAGE ON SCHEMA ads, dim TO mock_ai_reader;
REVOKE CREATE ON SCHEMA ads, dim FROM mock_ai_reader;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA ads, dim FROM mock_ai_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA ads, dim TO mock_ai_reader;

ALTER ROLE mock_ai_reader IN DATABASE mock_coffice SET default_transaction_read_only = 'on';
ALTER ROLE mock_ai_reader IN DATABASE mock_coffice SET statement_timeout = '30s';
ALTER ROLE mock_ai_reader IN DATABASE mock_coffice SET lock_timeout = '3s';
ALTER ROLE mock_ai_reader IN DATABASE mock_coffice SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE mock_ai_reader IN DATABASE mock_coffice SET search_path = 'ads', 'dim';
```

表白名单模式应将 schema 级 `GRANT SELECT ON ALL TABLES` 替换为：

```sql
GRANT SELECT ON TABLE ads.table_one, dim.table_two TO mock_ai_reader;
```

## 4. 执行方式

当前仓库未包含独立的只读角色自动化脚本。请由 DBA 在安全终端中执行上方 SQL 模板，并通过交互式 `\password` 或一次性环境变量设置密码；不得把凭据写入仓库。执行后必须按第 8 节逐项核验，再到数据源页面录入加密配置。

## 5. 数据源页面配置

在“AI 管理 → 数据源管理”填写：

- 名称/编码：`mock_coffice AI只读数据源` / `mock_coffice_ai_readonly`
- 主机/端口/数据库：`192.168.77.111` / `5432` / `mock_coffice`
- 用户：`mock_ai_reader`
- SSL：测试环境 `prefer`；正式环境支持证书时使用 `require` 或 `verify-full`
- 连接、查询、锁、空闲事务超时：10 秒、30000、3000、30000 ms
- Schema 白名单：`ads, dim`

保存后必须执行“测试”和“扫描”。最低通过标准是返回数据库 `mock_coffice`、用户 `mock_ai_reader` 和 `transaction_read_only=on`，且扫描对象仅属于允许 schema。

## 6. 创建不同范围账号

- 经营汇总：`mock_ai_ads_reader`，只授权 `ads`。
- 达播分析：`mock_ai_influencer_reader`，只授权达播相关 ADS 表和必要 DIM 表。
- 银行分析：`mock_ai_bank_reader`，只授权银行 ADS 表和必要分类 DIM 表。

不得创建“全库只读账号”后只依赖前端隐藏。极简版已经移除应用层 AI 数据权限，因此每个账号必须在 PostgreSQL 层直接限定最终可读 schema、表和视图；需要不同数据范围时，应拆分专用只读账号和数据源配置。

## 7. 轮换、扩权与回收

- 轮换密码：重新运行 Skill 脚本，在同一维护窗口编辑数据源密码并立即测试。
- 新增表：完成数据口径和敏感性确认后，单独 `GRANT SELECT`，再增量扫描目录。
- 回收：先停用数据源，再撤销 `CONNECT/USAGE/SELECT`，确认无活跃会话和默认权限引用后 `DROP ROLE`。

## 8. 验收

```sql
SHOW default_transaction_read_only;
SHOW statement_timeout;
SHOW search_path;

SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
       rolreplication, rolbypassrls
FROM pg_roles
WHERE rolname = 'mock_ai_reader';
```

预期只有 `rolcanlogin=true`，其余高权限字段均为 `false`。同时验证授权 SELECT 成功、未授权对象不可读、写 SQL 被数据库和应用层共同拒绝。
