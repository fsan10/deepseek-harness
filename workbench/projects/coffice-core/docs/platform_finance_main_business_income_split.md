# 主营收入 ETL 拆分说明

主营收入链路现在拆成三个独立任务，避免“抖音快手任务”与七平台共享 ADS 校验混在一起：

| ETL key | 页面名称 | 处理范围 |
|---|---|---|
| `douyin_main_business_income` | 抖音主营收入 | 抖音 ODS → 抖音 DWD → 抖音 DWS |
| `ks_main_business_income` | 快手主营收入 | 快手 ODS → 快手 DWD → 快手 DWS |
| `platform_main_business_income_shared_ads` | 七平台共享主营收入 ADS | 七个平台 DWS → 共享 ADS，并校验平台覆盖、公司映射和 DWS/ADS 一致性 |

抖音或快手单独刷新时，任务编排会自动追加共享 ADS；共享 ADS 成功后再追加平台银行汇总。共享 ADS 不会重新读取 ODS，也不会重复刷新抖音或快手 DWD/DWS。

旧的 `douyin_ks_main_business_income` 入口保留为兼容脚本，但不再进入夜间或手动“全量刷新”；历史 ETL 记录仍可重试。新的导入和任务编排均使用三个新任务。

## 手动运行

```powershell
C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe -m etl.platform_finance.run_douyin_main_business_income_etl
C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe -m etl.platform_finance.run_ks_main_business_income_etl
C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe -m etl.platform_finance.run_platform_main_business_income_shared_ads_etl
```

生产环境不应只运行共享 ADS 而跳过对应平台 DWS；共享任务的校验失败时，应先查看错误中列出的平台数量和上游 DWS 任务状态。
