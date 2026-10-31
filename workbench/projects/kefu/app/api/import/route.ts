import { getLocalDb } from "@/db/local";
import { importOverview, recordImportBatch } from "@/lib/import-batches";
import {
  hasImportScope,
  hasReportingScope,
  normalizeImportedMetric,
  PLATFORM_IMPORT_CAPABILITIES,
  type ImportScope,
} from "@/db/reporting-config";

export const runtime = "nodejs";

const MAX_BATCH_SIZE = 200;
const VALID_KINDS = new Set(["own", "competitor"]);
const VALID_OPERATORS = new Set(["≥", "≤", ">", "<"]);

type ImportRecord = {
  reportDate?: unknown;
  platform?: unknown;
  shopName?: unknown;
  shopKind?: unknown;
  metricName?: unknown;
  metricCategory?: unknown;
  unit?: unknown;
  value?: unknown;
  targetOperator?: unknown;
  targetValue?: unknown;
  note?: unknown;
  source?: unknown;
};

type NormalizedRecord = {
  reportDate: string;
  platform: string;
  shopName: string;
  shopKind: "own" | "competitor";
  metricName: string;
  metricCategory: string;
  unit: string;
  numericValue: number | null;
  textValue: string;
  targetOperator: string | null;
  targetValue: number | null;
  note: string;
  source: string;
  metricCode: string;
  importScope: ImportScope;
};

function limitedText(input: unknown, maxLength: number) {
  return String(input ?? "").trim().slice(0, maxLength);
}

function parseNumber(input: unknown) {
  if (typeof input === "number") return Number.isFinite(input) ? input : null;
  const raw = String(input ?? "").trim();
  if (!raw || raw === "/" || raw === "-") return null;
  const numeric = Number(raw.replaceAll(",", "").replace(/小时|秒|%/g, ""));
  if (!Number.isFinite(numeric)) return null;
  return raw.includes("%") ? numeric / 100 : numeric;
}

function validDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

function validPercentageRange(value: string) {
  const match = value.match(/^(\d+(?:\.\d+)?)%\s*(?:-|~|～|—|至)\s*(\d+(?:\.\d+)?)%$/);
  if (!match) return false;
  const lower = Number(match[1]);
  const upper = Number(match[2]);
  return lower >= 0 && upper <= 100 && lower <= upper;
}

function inferUnit(metricName: string, rawValue: unknown) {
  const value = String(rawValue ?? "");
  if (value.includes("小时")) return "小时";
  if (value.includes("秒")) return "秒";
  if (metricName.includes("率") || metricName.includes("比例") || value.includes("%")) return "%";
  if (metricName.includes("时长")) return "秒";
  if (metricName.includes("接待") || metricName.includes("订单") || metricName.includes("数量")) return "单";
  return "分";
}

function importScopeForMetric(metricName: string, metricCategory: string): ImportScope {
  if (metricName === "接待量" && metricCategory === "运营") return "reception";
  if (metricCategory === "退款统计" || metricName.includes("退款率")) return "refund";
  return "score";
}

function metricCodeFor(metricName: string, metricCategory: string, unit: string, metricKey: string) {
  if (metricName === "接待量" && metricCategory === "运营" && unit === "单") return "reception_count";
  if (metricName === "退款率" && metricCategory === "退款统计" && unit === "%") return "refund_rate";
  return `api_${hash(metricKey)}`;
}

function hash(value: string) {
  let current = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    current ^= value.charCodeAt(index);
    current = Math.imul(current, 16777619);
  }
  return (current >>> 0).toString(36).padStart(7, "0");
}

function safeEqual(left: string, right: string) {
  if (left.length !== right.length) return false;
  let mismatch = 0;
  for (let index = 0; index < left.length; index += 1) mismatch |= left.charCodeAt(index) ^ right.charCodeAt(index);
  return mismatch === 0;
}

function authorized(request: Request) {
  const configured = process.env.IMPORT_API_KEY?.trim() ?? "";
  if (!configured) return false;
  const authorization = request.headers.get("authorization") ?? "";
  const bearer = authorization.startsWith("Bearer ") ? authorization.slice(7).trim() : "";
  const apiKey = bearer || request.headers.get("x-api-key")?.trim() || "";
  return safeEqual(apiKey, configured);
}

function normalize(record: ImportRecord, index: number) {
  const reportDate = limitedText(record.reportDate, 10);
  const platform = limitedText(record.platform, 40);
  const shopName = limitedText(record.shopName, 120);
  const shopKind = limitedText(record.shopKind || "own", 20) as "own" | "competitor";
  const rawMetricName = limitedText(record.metricName, 120);
  const rawMetricCategory = limitedText(record.metricCategory || "自动导入", 80);
  const normalizedMetric = normalizeImportedMetric(platform, rawMetricName, rawMetricCategory);
  const metricName = normalizedMetric.metricName;
  const metricCategory = normalizedMetric.metricCategory;
  const unit = limitedText(record.unit || inferUnit(metricName, record.value), 20);
  const importScope = importScopeForMetric(metricName, metricCategory);
  const numericValue = parseNumber(record.value);
  const textValue = limitedText(record.value, 80);
  const isPinduoduoRankRange = platform === "拼多多"
    && metricName === "本店铺体验分在同行排名"
    && metricCategory === "总览"
    && unit === "区间"
    && validPercentageRange(textValue);
  const targetOperator = record.targetOperator == null || record.targetOperator === "" ? null : limitedText(record.targetOperator, 1);
  const targetValue = record.targetValue == null || record.targetValue === "" ? null : parseNumber(record.targetValue);
  const errors: string[] = [];

  if (!validDate(reportDate)) errors.push("reportDate 必须为 YYYY-MM-DD 格式的有效日期");
  if (!platform) errors.push("platform 不能为空");
  if (!shopName) errors.push("shopName 不能为空");
  if (!VALID_KINDS.has(shopKind)) errors.push("shopKind 只能是 own 或 competitor");
  if (!metricName) errors.push("metricName 不能为空");
  if (numericValue === null && !isPinduoduoRankRange) {
    errors.push("value 必须是有效数值，或合法的拼多多同行排名区间");
  }
  if (importScope === "reception" && unit !== "单") errors.push("接待量 unit 必须为 单");
  if (importScope === "reception" && numericValue !== null && (numericValue < 0 || !Number.isInteger(numericValue))) {
    errors.push("接待量必须是非负整数");
  }
  if (importScope === "refund" && unit !== "%") errors.push("退款率 unit 必须为 %");
  if (importScope === "refund" && numericValue !== null && (numericValue < 0 || numericValue > 1)) {
    errors.push("退款率必须在 0% 到 100% 之间");
  }
  if (shopKind === "own" && platform && shopName && !hasImportScope(platform, shopName, importScope)) {
    errors.push(`${platform}/${shopName} 不允许导入 ${importScope} 类型数据`);
  }
  if (targetOperator && !VALID_OPERATORS.has(targetOperator)) errors.push("targetOperator 只能是 ≥、≤、>、<");
  if (targetOperator && targetValue === null) errors.push("设置 targetOperator 时必须同时提供 targetValue");
  if (record.targetValue != null && record.targetValue !== "" && targetValue === null) errors.push("targetValue 必须是有效数值");
  if (errors.length) return { index, errors };

  const metricKey = `${metricCategory}|${metricName}|${unit}`;
  return {
    index,
    value: {
      reportDate,
      platform,
      shopName,
      shopKind,
      metricName,
      metricCategory,
      unit,
      numericValue,
      textValue,
      targetOperator,
      targetValue,
      note: limitedText(record.note, 500),
      source: limitedText(record.source || "自动化API", 80),
      metricCode: metricCodeFor(metricName, metricCategory, unit, metricKey),
      importScope,
    } satisfies NormalizedRecord,
  };
}

export async function GET(request: Request) {
  const url = new URL(request.url);
  return Response.json({
    name: "客服数据台局域网批量导入 API",
    version: "1.2-local",
    endpoint: `${url.origin}/api/import`,
    method: "POST",
    authentication: "Authorization: Bearer <IMPORT_API_KEY>",
    maxBatchSize: MAX_BATCH_SIZE,
    idempotency: "相同日期、店铺和指标会更新，不会重复新增。",
    platformCapabilities: PLATFORM_IMPORT_CAPABILITIES,
    overview: importOverview(),
  });
}

export async function POST(request: Request) {
  const requestId = request.headers.get("x-request-id")?.slice(0, 100) || crypto.randomUUID();
  if (!authorized(request)) return Response.json({ ok: false, requestId, error: "API 密钥无效" }, { status: 401 });

  try {
    const body = await request.json() as { records?: ImportRecord[]; dryRun?: boolean; requestId?: string; source?: string };
    const records = body.records;
    const responseRequestId = limitedText(body.requestId || requestId, 100);
    const source = limitedText(body.source || request.headers.get("x-source") || "HTTP API", 80);
    if (!Array.isArray(records) || records.length === 0) {
      return Response.json({ ok: false, requestId: responseRequestId, error: "records 必须是非空数组" }, { status: 400 });
    }
    if (records.length > MAX_BATCH_SIZE) {
      return Response.json({ ok: false, requestId: responseRequestId, error: `单批最多 ${MAX_BATCH_SIZE} 条，请分批提交` }, { status: 413 });
    }

    const normalizedResults = records.map(normalize);
    const validationErrors = normalizedResults.filter((item) => "errors" in item);
    if (validationErrors.length) {
      try {
        recordImportBatch({
          id: responseRequestId,
          recordCount: records.length,
          successCount: 0,
          failedCount: records.length,
          source,
          note: "数据校验失败",
        });
      } catch {
        /* 批次日志失败不影响导入结果 */
      }
      return Response.json({ ok: false, requestId: responseRequestId, error: "数据校验失败", details: validationErrors }, { status: 422 });
    }

    const normalized = normalizedResults.map((item) => (item as { value: NormalizedRecord }).value);
    const deduplicated = new Map<string, NormalizedRecord>();
    for (const record of normalized) {
      const key = `${record.reportDate}|${record.shopKind}|${record.platform}|${record.shopName}|${record.metricCategory}|${record.metricName}|${record.unit}`;
      deduplicated.set(key, record);
    }
    const finalRecords = [...deduplicated.values()];
    if (body.dryRun) {
      return Response.json({ ok: true, dryRun: true, requestId: responseRequestId, received: records.length, valid: finalRecords.length, deduplicated: records.length - finalRecords.length });
    }

    const database = getLocalDb();
    const uniqueShops = [...new Map(finalRecords.map((record) => [`${record.shopKind}|${record.platform}|${record.shopName}`, record])).values()];
    const uniqueMetrics = [...new Map(finalRecords.map((record) => [`${record.metricCategory}|${record.metricName}|${record.unit}`, record])).values()];
    database.exec("BEGIN IMMEDIATE");
    try {
      const upsertShop = database.prepare(
        `INSERT INTO shops (name, platform, kind, score_enabled, reception_enabled) VALUES (?, ?, ?, ?, ?)
         ON CONFLICT(name, platform, kind) DO UPDATE SET
           score_enabled = excluded.score_enabled,
           reception_enabled = excluded.reception_enabled`,
      );
      const findShop = database.prepare("SELECT id FROM shops WHERE name = ? AND platform = ? AND kind = ?");
      const upsertMetric = database.prepare(
        `INSERT INTO metrics (code, name, category, unit) VALUES (?, ?, ?, ?)
         ON CONFLICT(name, category, unit) DO UPDATE SET name = excluded.name`,
      );
      const findMetric = database.prepare("SELECT id FROM metrics WHERE name = ? AND category = ? AND unit = ?");
      const upsertRecord = database.prepare(
        `INSERT INTO daily_records
          (report_date, shop_id, metric_id, numeric_value, text_value, target_operator, target_value, source_sheet, note)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(report_date, shop_id, metric_id) DO UPDATE SET
           numeric_value = excluded.numeric_value,
           text_value = excluded.text_value,
           target_operator = COALESCE(excluded.target_operator, daily_records.target_operator),
           target_value = COALESCE(excluded.target_value, daily_records.target_value),
           source_sheet = excluded.source_sheet,
           note = excluded.note,
           updated_at = CURRENT_TIMESTAMP`,
      );

      const shopIds = new Map<string, number>();
      for (const shop of uniqueShops) {
        const scoreEnabled = shop.shopKind === "own" && hasReportingScope(shop.platform, shop.shopName, "score");
        const receptionEnabled = shop.shopKind === "own" && hasReportingScope(shop.platform, shop.shopName, "reception");
        upsertShop.run(shop.shopName, shop.platform, shop.shopKind, scoreEnabled ? 1 : 0, receptionEnabled ? 1 : 0);
        const row = findShop.get(shop.shopName, shop.platform, shop.shopKind) as { id: number };
        shopIds.set(`${shop.shopKind}|${shop.platform}|${shop.shopName}`, row.id);
      }
      const metricIds = new Map<string, number>();
      for (const metric of uniqueMetrics) {
        upsertMetric.run(metric.metricCode, metric.metricName, metric.metricCategory, metric.unit);
        const row = findMetric.get(metric.metricName, metric.metricCategory, metric.unit) as { id: number };
        metricIds.set(`${metric.metricCategory}|${metric.metricName}|${metric.unit}`, row.id);
      }
      for (const record of finalRecords) {
        const shopId = shopIds.get(`${record.shopKind}|${record.platform}|${record.shopName}`);
        const metricId = metricIds.get(`${record.metricCategory}|${record.metricName}|${record.unit}`);
        if (!shopId || !metricId) throw new Error("店铺或指标映射失败");
        upsertRecord.run(
          record.reportDate, shopId, metricId, record.numericValue, record.textValue,
          record.targetOperator, record.targetValue, record.source, record.note,
        );
      }
      database.exec("COMMIT");
    } catch (error) {
      database.exec("ROLLBACK");
      throw error;
    }

    try {
      recordImportBatch({
        id: responseRequestId,
        recordCount: records.length,
        successCount: records.length,
        failedCount: 0,
        source,
      });
    } catch {
      /* 批次日志失败不影响导入结果 */
    }

    return Response.json({
      ok: true,
      requestId: responseRequestId,
      received: records.length,
      processed: finalRecords.length,
      deduplicated: records.length - finalRecords.length,
      shops: uniqueShops.length,
      metrics: uniqueMetrics.length,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "批量导入失败";
    return Response.json({ ok: false, requestId, error: message }, { status: 500 });
  }
}
