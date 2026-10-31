import { getLocalDb } from "@/db/local";

export const runtime = "nodejs";

type RecordInput = {
  id?: number;
  reportDate?: string;
  shopId?: number;
  metricId?: number;
  value?: string | number;
  note?: string;
};

function parseNumeric(input: unknown) {
  const raw = String(input ?? "").trim();
  const value = Number(raw.replaceAll(",", "").replace(/小时|秒|%/g, ""));
  if (!Number.isFinite(value)) return null;
  return raw.includes("%") ? value / 100 : value;
}

function normalize(body: RecordInput) {
  const reportDate = body.reportDate?.trim() ?? "";
  const shopId = Number(body.shopId);
  const metricId = Number(body.metricId);
  const rawValue = String(body.value ?? "").trim();
  const numericValue = parseNumeric(body.value);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(reportDate) || !shopId || !metricId || !rawValue) return null;
  return { reportDate, shopId, metricId, rawValue, numericValue, note: body.note?.trim().slice(0, 500) ?? "" };
}

function validValueForMetric(metricId: number, rawValue: string, numericValue: number | null) {
  if (numericValue !== null) return true;
  const metric = getLocalDb().prepare("SELECT unit FROM metrics WHERE id = ?").get(metricId) as { unit?: string } | undefined;
  if (metric?.unit !== "区间") return false;
  const match = rawValue.match(/^(\d+(?:\.\d+)?)%\s*(?:-|~|～|—|至)\s*(\d+(?:\.\d+)?)%$/);
  return Boolean(match && Number(match[1]) >= 0 && Number(match[2]) <= 100 && Number(match[1]) <= Number(match[2]));
}

export async function POST(request: Request) {
  try {
    const normalized = normalize(await request.json() as RecordInput);
    if (!normalized) return Response.json({ error: "请完整填写日期、店铺、指标和有效数值。" }, { status: 400 });
    if (!validValueForMetric(normalized.metricId, normalized.rawValue, normalized.numericValue)) {
      return Response.json({ error: "数值格式与指标单位不匹配。" }, { status: 400 });
    }
    getLocalDb().prepare(
      `INSERT INTO daily_records
        (report_date, shop_id, metric_id, numeric_value, text_value, source_sheet, note)
       VALUES (?, ?, ?, ?, ?, '网页录入', ?)
       ON CONFLICT(report_date, shop_id, metric_id) DO UPDATE SET
         numeric_value = excluded.numeric_value, text_value = excluded.text_value,
         source_sheet = '网页录入', note = excluded.note, updated_at = CURRENT_TIMESTAMP`,
    ).run(
      normalized.reportDate, normalized.shopId, normalized.metricId,
      normalized.numericValue, normalized.rawValue, normalized.note,
    );
    return Response.json({ ok: true });
  } catch (error) {
    const message = error instanceof Error ? error.message : "保存失败";
    return Response.json({ error: message }, { status: 500 });
  }
}

export async function PUT(request: Request) {
  try {
    const body = await request.json() as RecordInput;
    const id = Number(body.id);
    const normalized = normalize(body);
    if (!id || !normalized) return Response.json({ error: "记录或表单内容无效。" }, { status: 400 });
    if (!validValueForMetric(normalized.metricId, normalized.rawValue, normalized.numericValue)) {
      return Response.json({ error: "数值格式与指标单位不匹配。" }, { status: 400 });
    }
    const result = getLocalDb().prepare(
      `UPDATE daily_records SET report_date = ?, shop_id = ?, metric_id = ?,
       numeric_value = ?, text_value = ?, source_sheet = '网页编辑', note = ?,
       updated_at = CURRENT_TIMESTAMP WHERE id = ?`,
    ).run(
      normalized.reportDate, normalized.shopId, normalized.metricId,
      normalized.numericValue, normalized.rawValue, normalized.note, id,
    );
    if (!result.changes) return Response.json({ error: "找不到这条记录。" }, { status: 404 });
    return Response.json({ ok: true });
  } catch (error) {
    const message = error instanceof Error && error.message.includes("UNIQUE")
      ? "相同日期、店铺和指标的记录已存在。"
      : error instanceof Error ? error.message : "更新失败";
    return Response.json({ error: message }, { status: 500 });
  }
}

export async function DELETE(request: Request) {
  try {
    const id = Number(new URL(request.url).searchParams.get("id"));
    if (!id) return Response.json({ error: "记录编号无效。" }, { status: 400 });
    const result = getLocalDb().prepare("DELETE FROM daily_records WHERE id = ?").run(id);
    if (!result.changes) return Response.json({ error: "找不到这条记录。" }, { status: 404 });
    return Response.json({ ok: true });
  } catch (error) {
    const message = error instanceof Error ? error.message : "删除失败";
    return Response.json({ error: message }, { status: 500 });
  }
}
