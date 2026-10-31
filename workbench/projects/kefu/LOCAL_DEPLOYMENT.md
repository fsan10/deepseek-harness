# Windows 本地与局域网部署

## 一、准备环境

安装 64 位 Node.js 22.13 或更高版本，以及 Python 3.12，并确认 PowerShell 中以下命令能输出版本号：

```powershell
node --version
npm --version
py -3.12 --version
```

首次安装依赖需要联网。安装完成后，日常启动、查看和局域网导入都不需要互联网。

## 二、一键安装

在项目目录 `D:\fsan10\kefu` 打开 PowerShell，执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-local.ps1
```

脚本会安装 Node 依赖、创建 kefu 自己的 `.venv` 并安装采集依赖、生成 `.env.local` 和随机 API 密钥，再完成生产构建。已经存在的 `.env.local` 不会被覆盖。仅补装采集环境时运行 `scripts\setup-reviews.ps1`；它不会启动服务。

## 三、启动服务

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-local.ps1
```

保持这个 PowerShell 窗口运行。默认端口是 3000，也可以指定其他端口：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-local.ps1 -Port 3100
```

访问地址：

- 本机：`http://localhost:3000`
- 局域网：`http://服务器局域网IP:3000`
- 导入 API：`http://服务器局域网IP:3000/api/import`

可以用 `ipconfig` 查看服务器的 IPv4 地址。建议在路由器中为这台服务器固定局域网 IP，避免地址变化后需要修改 RPA。

## 四、放行 Windows 防火墙

如果其他电脑打不开网页，请以管理员身份打开 PowerShell，执行一次：

```powershell
New-NetFirewallRule -DisplayName "客服数据台 3000" -Direction Inbound -Protocol TCP -LocalPort 3000 -Action Allow
```

如果改用了其他端口，请同步修改规则中的端口号。只建议在可信的公司/家庭局域网内开放，不要在路由器上做公网端口映射。

## 五、配置与数据

项目根目录 `.env.local` 的内容类似：

```dotenv
IMPORT_API_KEY=kf_local_一段随机密钥
KEFU_DB_PATH=./data/kefu.sqlite
```

- 修改 `.env.local` 后需要重启服务。
- 数据库文件默认是 `data/kefu.sqlite`。
- 备份时先停止服务，然后复制 `data/kefu.sqlite` 到安全位置。
- 恢复时先停止服务，再用备份文件替换数据库。
- 不要把 `.env.local` 或数据库文件提交到 Git、发送到公共群组或放到公网。

## 六、手动安装方式

不使用脚本时，也可以执行：

```powershell
npm install
Copy-Item .env.example .env.local
# 编辑 .env.local，把 IMPORT_API_KEY 改成足够长的随机密钥
powershell -ExecutionPolicy Bypass -File scripts\setup-reviews.ps1
npm run build
npm run start:lan
```

Python 与影刀导入方法见 `API_IMPORT.md`。

## 七、多平台 WebAPI 采集

接待量和店铺体验分的入口为 `/reception/collection`、`/scores/collection`，统一设置位于 `/collection/settings`。先同步 Cloak 店铺并显式登录保存加密会话，再开始采集。打开采集或设置页会启动后台调度；计划默认关闭，网页服务需要保持运行。详细范围、登录处理、飞书配置与 CLI 见 [多平台指标采集](docs/多平台指标采集.md)。

飞书密钥在后台填写，以当前 Windows 用户 DPAPI 加密保存。迁移机器或 Windows 用户后需重新登录店铺、重新填写飞书密钥；不能把密文当作跨用户可用的配置备份。多平台会话、飞书配置和运行数据库均不得提交 Git。
