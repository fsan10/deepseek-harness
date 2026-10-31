# Platform adapter contract

## Shared output

Every parser returns:

```python
{
    "platform": "天猫",
    "reportDate": "2026-07-14",
    "metrics": [
        {
            "metricName": "真实体验分",
            "metricCategory": "体验分",
            "unit": "分",
            "value": "5.00",
        }
    ],
}
```

`metricName` and `metricCategory` should reflect the platform page. Server-side normalization may map aliases to canonical dashboard names.

Direct scalar supplements do not require an HTML adapter. Use the canonical shared
identities `近30天有效订单/总览/单`, `接待量/运营/单`, and (Douyin only)
`退款率/退款统计/%`.

Do not create DOM adapters for JD, WeChat Shop, Xiaohongshu, or Kuaishou when the
RPA already captures their reception value directly; use
`yingdao_create_direct_result`.

## Adapter requirements

1. Accept one or more complete OuterHTML source blocks as strings.
2. Extract a valid `YYYY-MM-DD` report date from source or require an explicit date argument.
3. Emit primary metrics and every current detail metric under stable primary groups.
4. Pair name and value inside the same row container.
5. Preserve `%`, `小时`, `秒`, `分`, and `单` semantics.
6. Ignore benchmarks, targets, trend labels, peer ranks, weights, and decorative score scales.
7. Raise a clear error if a required primary metric group is absent.
8. Implement reception parsing separately and register it with `register_reception_adapter`; ignore comparisons such as `较前1日` and peer benchmarks.

## Tmall adapter

Implemented in `scripts/shop_score_pipeline.py`.

Primary metrics:

- 真实体验分
- 宝贝质量
- 物流速度
- 服务保障

Stable detail groups:

- 宝贝质量
- 物流速度
- 服务保障

Current Tmall pages expose these groups through semantic IDs containing
`newGoods`, `newLogistics`, and `newServices`. Detail rows use an ID beginning
with `metricsNameContainer-`; the suffix is the current dynamic metric name.
Primary scores are paired by their visible labels inside the nearest local
container. Generated class names are compatibility fallbacks only. Ignore the
`additionalPoints` group.

Detail names are intentionally dynamic. Do not restore an old hardcoded detail list.

Reception metric:

- Page name: `咨询人数`
- API normalization: `接待量` / `运营` / `reception_count`
- Stable extraction rule: find the `咨询人数` level-1 group and read its level-1 value. Never select the percentage under `较前1日` or `同行同层优秀`.

## Douyin adapter

Implemented in `scripts/shop_score_pipeline.py`.

Primary source: the overview section with `aria-label="体验分公式概览"`. The
current page labels are `我的总分`, `商品体验`, `物流体验`, and `服务体验`.
The parser also accepts the previous labels `我的体验分`, `商品体验得分`,
`物流体验得分`, and `服务体验得分` (and the canonical `*体验分` variants).
It pairs each `data-title="true"` label with the score and `分` unit in its
nearest card, so Tailwind class changes do not affect extraction.

Ignore `差行为扣分` as a primary score card. The API normalizes the four required
labels to the dashboard's canonical score-card names.

Detail source: the complete `section[aria-label="正式分分数详情"]` block. Current
markup uses these stable semantic group IDs (and `data-group-key` values):

- `formal-score-detail-group-goods` / `goods` -> 商品体验
- `formal-score-detail-group-logistics` / `logistics` -> 物流体验
- `formal-score-detail-group-service` / `service` -> 服务体验

Within each group, read every `article[id^="formal-score-detail-metric-"]`.
The metric name is the visible text of its `aria-label` beginning with `查看` and
containing `指标说明`; the first numeric value in that article's body is the
店铺表现. This ignores comparison, diagnosis, target and trend text. The
previous `data-experience-score-card-id` table structure remains supported as a
fallback:

- `product` -> 商品体验
- `logistics` -> 物流体验
- `service` -> 服务体验

Within each old table row, read the metric name from the first cell and `店铺表现`
from the third cell. Never import the second-cell score, formulas, weights,
thresholds, comparisons, or the `badBehavior`/`add`/`deduct` groups. Detail names
remain dynamic.

The supplied blocks do not contain a date, so `report_date` is required.

## Pinduoduo adapter

Implemented in `scripts/shop_score_pipeline.py`.

Use the complete `score_scoreWrapper__...` block and match stable class prefixes,
never their generated suffixes. Required metrics:

- 本店铺体验分在同行排名 (`区间`, for example `30%-40%`)
- 消费者服务体验分
- 服务态度体验分
- 基础服务体验分
- 商品服务体验分
- 发货服务体验分
- 物流服务体验分

Pair every label with the value in its local score container. Ignore `较前7日`
percentages and explanatory text. There are no detail groups. The source block has
no required date, so 影刀 must pass `report_date` explicitly.

## Adding another platform

Before editing code, obtain:

- all source blocks needed for primary metrics and details;
- one expected value for every primary metric;
- the platform's stable primary group names;
- examples of unavailable/null values;
- the displayed data date;
- units and whether durations are seconds or hours.

Then:

1. Add a function with signature:

```python
def parse_platform(source_block1, source_block2=""):
    return {"platform": "平台名", "reportDate": date, "metrics": metrics}
```

2. Register it:

```python
register_adapter("平台名", parse_platform)
```

3. Add and register the reception parser:

```python
def parse_platform_reception(source_block):
    return {
        "metricName": "平台页面指标名",
        "metricCategory": "接待量",
        "unit": "单",
        "value": value,
    }

register_reception_adapter("平台名", parse_platform_reception)
```

4. Add a minimal self-test fixture that uses changed/random class suffixes.
5. Test the supplied real HTML separately.
6. Add the platform's reception label to `normalizeImportedMetric` when it differs from existing aliases.
7. If primary dashboard labels differ, update `db/reporting-config.ts`; do not force cross-platform score names inside the parser.
8. Keep the shared 影刀 functions and API builder unchanged unless the shared input contract itself gains a platform-independent field.
