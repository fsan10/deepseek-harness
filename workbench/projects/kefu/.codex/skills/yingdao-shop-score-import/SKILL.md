---
name: yingdao-shop-score-import
description: Build, extend, and troubleshoot Yingdao RPA shop-score, valid-order-count, reception-count, and Douyin refund-rate ingestion for this customer-service dashboard. Use when Codex needs to inspect captured element OuterHTML, accept directly captured scalar metrics, create or update a platform parser, prepare combined `/api/import` payloads, configure Yingdao calls, validate dry-run results, diagnose missing data, or add a new platform's metric model.
---

# Yingdao shop-score import

Use this project-local skill to turn platform shop-score and reception HTML captured by 影刀 into normalized API records. Keep extraction platform-specific; keep validation, payload construction, and import behavior shared.

## Route the task

- For 影刀 module setup, variable mapping, HTTP actions, or runbook questions, read [references/yingdao-workflow.md](references/yingdao-workflow.md).
- For API fields, units, dry-run behavior, responses, and database identity rules, read [references/api-contract.md](references/api-contract.md).
- For adding or changing a platform parser, read [references/platform-adapters.md](references/platform-adapters.md).
- Use [scripts/shop_score_pipeline.py](scripts/shop_score_pipeline.py) as the deterministic parser and payload builder. Patch and test it instead of rewriting equivalent code in chat.

## Core workflow

1. Inspect project truth before changing behavior:
   - `app/api/import/route.ts`
   - `db/reporting-config.ts`
   - `app/api/dashboard/route.ts`
2. Obtain complete `outerHTML` source blocks for scores and dynamic detail groups. Directly captured scalar values may be used for valid orders, reception count, and Douyin refund rate. Never infer a platform DOM from screenshots alone.
3. Identify stable semantic boundaries:
   - fixed component class prefixes, IDs, headings, or accessible text;
   - a fixed primary-metric group;
   - each detail row's local name/value relationship.
4. Never depend on generated class suffixes, absolute XPath indexes, or two independent global name/value lists.
5. Add or update only the platform adapter. Preserve the shared result contract documented in `platform-adapters.md`.
6. Run the bundled self-test and the supplied real HTML sample. Assert date, primary metrics, details, units, and expected record count.
7. Configure 影刀 to call `yingdao_parse` for score HTML. Add reception with `yingdao_add_reception`; use `yingdao_add_douyin_metrics` when Douyin also supplies refund rate; or start a reception-only result with `yingdao_create_direct_result`. Then call `yingdao_build_api_body` and 影刀's native HTTP action. Douyin and Pinduoduo require an explicit `report_date` for the supplied blocks.
8. Send `dryRun=true` first. Require HTTP 200, `ok=true`, and the expected `valid` count. Explain explicitly that dry-run writes nothing.
9. Send the same payload with `dryRun=false` only after validation. Require `ok=true` and the expected `processed` count.
10. Verify the dashboard with a date range containing `reportDate` and an exact configured shop identity.

## Non-negotiable guards

- Treat `(platform, shopName, shopKind)` as exact identity. Check `db/reporting-config.ts`; do not silently invent aliases.
- Keep API keys in 影刀 configuration or environment variables. Never embed or print them in parser code.
- Do not connect 影刀 directly to SQLite. Always use `/api/import`.
- Preserve percentages as percentage strings for the API. Split `小时`/`秒` from numeric values and send the unit explicitly.
- Do not hardcode mutable detail metric names. Collect all rows inside each stable primary group.
- Map platform-facing reception aliases such as `咨询人数` to the API's canonical `接待量/运营/reception_count`; otherwise reception dashboards will ignore the record.
- Normalize directly captured valid orders to a non-negative integer and store them as `近30天有效订单/总览/单`.
- Enforce the project capability matrix: Douyin accepts score/reception/refund; Tmall and Pinduoduo accept score/reception; JD, WeChat Shop, Xiaohongshu, and Kuaishou accept reception only.
- Store Douyin refund rate as `退款率/退款统计/%`; reject refund records for every other platform.
- Preserve Pinduoduo peer rank as validated range text (`本店铺体验分在同行排名/总览/区间`); never replace it with one numeric boundary.
- Fail loudly on empty source, missing primary groups, missing required primary scores, invalid dates, or unsupported platforms.
- If records exist but the dashboard is empty, check in order: `dryRun`, exact shop name, reporting scope flags, selected date range, platform metric aliases.

## Completion evidence

Report:

- parser test results and extracted metric count;
- dry-run response (`valid`);
- formal response (`processed`) if the user authorized the write;
- the exact platform/shop/date used;
- any primary metric that is intentionally absent from the captured source.
