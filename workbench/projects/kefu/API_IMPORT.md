# 局域网批量导入 API

系统启动后，局域网内的 Python、影刀 RPA 或其他程序都可以通过 HTTP 批量写入数据。

## 接口地址

- 服务器本机：`http://127.0.0.1:3000/api/import`
- 局域网设备：`http://<服务器局域网IP>:3000/api/import`
- 方法：`POST`
- 单次最多：200 条；更多数据请分批发送
- 鉴权：`Authorization: Bearer <IMPORT_API_KEY>`

`IMPORT_API_KEY` 在项目根目录的 `.env.local` 中配置。请勿把这个文件发给无关人员。

配套入口：

- `GET /api/import`：返回接口版本、批量上限、鉴权方式与平台能力矩阵。
- `GET /api/import/template`：下载可编辑的 CSV 模板（与 `automation/import_template.csv` 一致）。

## 请求格式

```json
{
  "requestId": "rpa-20260714-001",
  "dryRun": false,
  "records": [
    {
      "reportDate": "2026-07-14",
      "platform": "抖音",
      "shopName": "元养颜旗舰店",
      "shopKind": "own",
      "metricName": "飞鸽平均响应时长",
      "metricCategory": "服务体验",
      "unit": "秒",
      "value": 13.2,
      "targetOperator": "≤",
      "targetValue": 15,
      "note": "自动导入",
      "source": "影刀RPA"
    }
  ]
}
```

必填字段是 `reportDate`、`platform`、`shopName`、`metricName`、`value`。`shopKind` 可填 `own` 或 `competitor`，不填时默认为 `own`。百分比值可以传 `98.6%`，系统会保存为 `0.986`。

相同“日期 + 店铺 + 指标”的数据再次导入时会更新原记录，不会重复新增，因此 RPA 重跑是安全的。首次联调建议传 `"dryRun": true`；此模式**只校验、绝不写入数据库**。校验成功后必须改为 `"dryRun": false` 再请求一次才会正式入库。

## 平台可导入范围

| 平台 | 可导入数据 |
|---|---|
| 抖音 | 店铺分、接待量、退款率 |
| 天猫 | 店铺分、接待量 |
| 拼多多 | 店铺分、接待量 |
| 京东 | 仅接待量 |
| 微信小店 | 仅接待量 |
| 小红书 | 仅接待量 |
| 快手 | 仅接待量 |

API 会同时校验平台、店铺和数据类型。不在项目配置范围内的自营店铺，或给“仅接待量”平台发送店铺分/退款率，都会返回 `422`，避免错误数据悄悄进入数据库。

时长值可以传 `47.09小时`、`12.3秒`，也可以把数值和 `unit` 分开传。天猫体验分导入会自动规范化一级指标名称：`真实体验分`、`宝贝质量`、`物流速度`、`服务保障` 分别保存为 `店铺体验分`、`宝贝质量分`、`物流速度分`、`服务体验分`。

各平台的接待量页面可以提交页面原名，例如 `咨询人数`、`咨询量` 或 `接待人数`，`metricCategory` 填 `接待量`、`unit` 填 `单`。API 会统一保存为 `接待量 / 运营 / reception_count`，这样接待量趋势和明细页面才能识别。店铺分与接待量可以放在同一个 `records` 数组中一次上传。

近30天有效订单使用 `metricName: "近30天有效订单"`、`metricCategory: "总览"`、`unit: "单"`，可以和店铺分、接待量放在同一批 `records` 中上传。

拼多多同行排名使用 `metricName: "本店铺体验分在同行排名"`、`metricCategory: "总览"`、`unit: "区间"`，值按页面原文传递，例如 `30%-40%`。API 会保留完整区间文本，不会错误转换成 30% 或 40%。

抖音页面名称会在 API 中统一：新页面的 `我的总分`、`商品体验`、`物流体验`、`服务体验`，以及旧页面的 `我的体验分`、`商品体验得分`、`物流体验得分`、`服务体验得分`，分别保存为总览下的 `店铺体验分`、`商品体验分`、`物流体验分`、`服务体验分`。商品、物流和服务明细保留页面原指标名称。

抖音退款率使用 `metricName: "退款率"`、`metricCategory: "退款统计"`、`unit: "%"`。可传 `2.35%`，API 保存为小数 `0.0235`；其他平台发送退款率会被拒绝。

## Python 导入

多平台 WebAPI 采集沿用本接口的 Bearer 鉴权、字段校验与规范化，不直接写指标表。采集器先执行 `dryRun:true`，确认 `valid` 与记录数一致，再正式提交并核对 `processed`。来源为 `商家WebAPI`，接待量的 `note` 保留平台原始统计口径；体验分的 `reportDate` 使用平台最新快照的业务日期。

天猫新采集店铺的精确名称为 `MOCK旗舰店`。历史 `mock天猫旗舰店` 数据保留，不因名称调整而合并或改写。完整有效店铺范围仍以 `db/reporting-config.ts` 为准。

项目已经提供不依赖第三方包的客户端和 CSV 模板。先在当前进程配置 `KEFU_API_KEY`（下方有环境变量示例），再执行：

```powershell
& .\.venv\Scripts\python.exe -m automation.import_client `
  --url http://192.168.1.20:3000/api/import `
  --file automation\import_template.csv `
  --dry-run
```

校验通过后删掉 `--dry-run` 即可正式写入。客户端会自动按每批 200 条拆分，并对临时网络错误重试。

也可以使用环境变量，避免把密钥写进命令或 RPA 日志：

```powershell
$env:KEFU_API_URL="http://192.168.1.20:3000/api/import"
$env:KEFU_API_KEY="你的IMPORT_API_KEY"
& .\.venv\Scripts\python.exe -m automation.import_client --file automation\import_template.csv
```

## 影刀 RPA 配置

在影刀中使用“HTTP 请求/发送网络请求”动作：

1. 请求方法选择 `POST`，地址填局域网 API 地址。
2. 请求头添加 `Content-Type: application/json; charset=utf-8`。
3. 请求头添加 `Authorization: Bearer 你的IMPORT_API_KEY`。
4. 请求体选择 JSON，按照上方格式填入 `records` 数组。
5. 检查 HTTP 状态码为 200，且返回 JSON 的 `ok` 为 `true`。

常见返回码：`401` 密钥错误；`422` 数据字段校验失败；`413` 单批超过 200 条；`500` 服务端写入失败。
