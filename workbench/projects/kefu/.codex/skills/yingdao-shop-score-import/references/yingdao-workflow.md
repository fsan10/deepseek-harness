# 影刀流程

## Recommended visual flow

1. Open the platform score page and wait for the primary score plus detail container to finish rendering.
2. Use “获取网页元素源代码/OuterHTML” for each complete document block. Do not capture a single value node.
3. Save blocks to stable flow variables, for example:
   - `web_element_attribute`: score details;
   - `web_element_attribute2`: primary scores;
   - `web_element_attribute3`: reception/consultation count.
   - `valid_order_count`: directly captured 30-day valid order value, not HTML.
4. Add a Python code module containing `scripts/shop_score_pipeline.py`.
5. Use “调用模块中的函数” and call:

```text
yingdao_parse(platform, source_block1, source_block2, reception_source, valid_order_count, report_date)
```

Keep functions selected directly by 影刀 on one signature line with no trailing
comma before `)`. Some 影刀 versions parse that trailing comma as an extra keyword
whose name is empty, producing `unexpected keyword argument ''`.

Example parameter mapping for Tmall:

| Function parameter | 影刀 value |
|---|---|
| `platform` | `天猫` |
| `source_block1` | `web_element_attribute` |
| `source_block2` | `web_element_attribute2` |
| `reception_source` | `web_element_attribute3` |
| `valid_order_count` | the 影刀 variable containing the displayed order number |
| `report_date` | empty, or the selected page date when explicitly available |

### Tmall semantic XPath (recommended)

Do not copy a generated class such as `items--sJXRccUG` or
`container--m5T0eOQL` into 影刀. Capture the complete `outerHTML` with these
semantic XPath expressions:

Primary-score block (`source_block2`):

```xpath
(//span[normalize-space(text())='真实体验分']/ancestor::div[count(.//span[normalize-space(text())='真实体验分'])=1 and count(.//span[normalize-space(text())='宝贝质量'])=1 and count(.//span[normalize-space(text())='物流速度'])=1 and count(.//span[normalize-space(text())='服务保障'])=1][1])[1]
```

Performance/detail block including its update date (`source_block1`):

```xpath
//*[@id='voc-shop-performance-newGoods-v2025']/ancestor::div[.//*[@id='voc-shop-performance-newLogistics-v2025'] and .//*[@id='voc-shop-performance-newServices-v2025'] and .//*[contains(normalize-space(.),'更新时间')]][1]
```

The outer parentheses on the primary-score XPath are intentional: the inner
`[1]` chooses the nearest complete card for each matching label, while the final
`[1]` reduces duplicate/hidden page copies to one element. These expressions
contain no class name and no absolute DOM path. The parser uses
the same semantic labels and section IDs, then pairs each name/value inside its
local container. If Tmall changes the visible primary labels or removes the
`voc-shop-performance-*` IDs, both XPath and the adapter must be reviewed; no DOM
selector can remain correct after all semantic anchors are removed.

Save the return value as `parsed_score_result`. For the supplied Tmall sample this
contains 12 score metrics plus `咨询人数` and `近30天有效订单`, for 14 metrics total.
The order parameter accepts values such as `1234`, `1,234`, `1234单`, or `1.23万`.
An empty value omits the order record and preserves the previous workflow.

Example parameter mapping for Douyin:

| Function parameter | 影刀 value |
|---|---|
| `platform` | `抖音` |
| `source_block1` | fragment 1: `//section[@aria-label='体验分公式概览'][1]` 的 OuterHTML |
| `source_block2` | fragment 2: `//section[@data-e2e='formal-score-detail'][1]` 的 OuterHTML |
| `reception_source` | empty until a Douyin reception adapter is configured |
| `valid_order_count` | directly captured order count, or empty |
| `report_date` | required `YYYY-MM-DD` data date |

The supplied Douyin blocks contain no date. Do not use the RPA runtime implicitly;
pass the page's data date explicitly. The new overview labels are `我的总分`、
`商品体验`、`物流体验`、`服务体验`; old labels remain supported. With the supplied
blocks the parser emits 4 primary scores plus 9 detail metrics; adding valid orders
produces 14 records.

For a platform or flow that imports reception only, call:

```text
yingdao_parse_reception(platform, reception_source, report_date)
```

The date must be the data date selected on the platform page, not the RPA run time.

When 影刀 already captured a scalar reception count, use this simpler entry point;
it does not require HTML:

```text
yingdao_create_direct_result(platform, report_date, reception_count)
```

For JD, WeChat Shop, Xiaohongshu, and Kuaishou, pass the platform, data date, and
captured reception count. These four platforms accept reception only, so this
function deliberately has no refund-rate parameter.

For Tmall and Pinduoduo, first parse the score blocks, then append the captured
reception count:

```text
parsed_score_result = yingdao_parse(platform, source_block1, source_block2, "", valid_order_count, report_date)
parsed_score_result = yingdao_add_reception(parsed_score_result, reception_count)
```

For Douyin, the same supplement function accepts both reception count and refund
rate:

```text
parsed_score_result = yingdao_parse("抖音", source_block1, source_block2, "", valid_order_count, report_date)
parsed_score_result = yingdao_add_douyin_metrics(parsed_score_result, reception_count, refund_rate)
```

`reception_count` accepts values such as `1234`, `1,234`, `1234单`, or `1.23万`.
`refund_rate` accepts `2.35` or `2.35%`, both meaning 2.35%. Refund rate is rejected
for non-Douyin platforms.

Example parameter mapping for Pinduoduo:

| Function parameter | 影刀 value |
|---|---|
| `platform` | `拼多多` |
| `source_block1` | complete `score_scoreWrapper__...` OuterHTML |
| `source_block2` | empty |
| `reception_source` | empty when reception is captured as a scalar |
| `valid_order_count` | empty |
| `report_date` | required separately captured `YYYY-MM-DD` data date |

The Pinduoduo parser emits exactly seven top-level metrics and no detail rows. The
peer rank is preserved as text such as `30%-40%`; it is not converted to either
boundary or to a false numeric score.

6. Call:

```text
yingdao_build_api_body(parsed_score_result, shop_name, dry_run)
```

Save the return value as `api_request_body`.

7. Add 影刀 “HTTP 请求/发送网络请求”:

```text
POST http://<server-ip>:3000/api/import
Content-Type: application/json; charset=utf-8
Authorization: Bearer <IMPORT_API_KEY>
Body: api_request_body
```

Use the native HTTP action so status codes, retries, and response logging remain visible in the RPA flow.

## Two-phase import

First call `yingdao_build_api_body(..., dry_run=True)`.

Require:

```json
{"ok": true, "dryRun": true, "valid": 14}
```

This response does not mean data was inserted. It only means validation succeeded.

Then call the same function with `dry_run=False` and send again. Require:

```json
{"ok": true, "processed": 14}
```

## Required flow checks

- Stop when the HTTP status is not 200.
- Stop when response `ok` is not true.
- Compare `valid` or `processed` with `len(parsed_score_result["metrics"])`.
- Log `requestId`, platform, shop name, report date, and counts. Do not log the API key or full source HTML.
- Keep the exact configured shop name in one 影刀 variable shared by all score imports.

## Common failures

| Symptom | Check |
|---|---|
| HTTP 200 but database empty | Request used `dryRun=true`; send again with false. |
| Database has rows but dashboard is empty | Imported shop name differs from configured shop identity. |
| 咨询人数写入后接待量页面为空 | API did not normalize it to `接待量/运营/reception_count`, or the shop is not reception-enabled. |
| Values do not change with date | Confirm UI range contains `reportDate`; inspect dashboard API `from` and `to`. |
| A time metric returns 422 | Send numeric `value` with explicit `unit` of `小时` or `秒`. |
| Platform/type returns 422 | Check the capability matrix; reception-only platforms cannot submit score or refund records. |
| Refund rate is 100 times too small/large | Pass the displayed percent (`2.35` or `2.35%`), not decimal storage form `0.0235`. |
| Names and values shift | Parser extracted two independent lists; pair them within each DOM row. |
| Parser breaks after a deployment | Remove generated class suffixes/absolute indexes from selectors. |
