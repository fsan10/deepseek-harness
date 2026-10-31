import { all } from "@/db/local";
import type { SQLInputValue } from "node:sqlite";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Row = Record<string, string | number | null>;

function safeDate(value: string | null, fallback: string) {
  return value && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : fallback;
}

function csvCell(value: unknown) {
  return `"${String(value ?? "").replaceAll('"', '""')}"`;
}

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const type = url.searchParams.get("type") === "scores" ? "scores" : "reception";
    const query = (url.searchParams.get("query") ?? "").trim().slice(0, 80);
    const platform = (url.searchParams.get("platform") ?? "").trim().slice(0, 40);
    const shopId = Math.max(0, Number(url.searchParams.get("shopId") || 0));
    const from = safeDate(url.searchParams.get("from"), "0001-01-01");
    const to = safeDate(url.searchParams.get("to"), "9999-12-31");

    const conditions = ["s.kind = 'own'", "r.report_date BETWEEN ? AND ?"];
    const bindings: SQLInputValue[] = [from, to];
    if (type === "reception") conditions.push("s.reception_enabled = 1", "m.code = 'reception_count'");
    else conditions.push("s.score_enabled = 1", "m.code != 'reception_count'");
    if (platform) {
      conditions.push("s.platform = ?");
      bindings.push(platform);
    }
    if (shopId) {
      conditions.push("s.id = ?");
      bindings.push(shopId);
    }
    if (query) {
      conditions.push("(s.name LIKE ? OR s.platform LIKE ? OR m.name LIKE ?)");
      const like = `%${query}%`;
      bindings.push(like, like, like);
    }

    const rows = all<Row>(
      `SELECT s.platform, s.name AS shop, m.name AS metric, m.category, m.unit,
         r.report_date AS date, r.numeric_value AS value, r.text_value AS textValue,
         r.target_operator AS operator, r.target_value AS target, r.note
       FROM daily_records r
       JOIN shops s ON s.id = r.shop_id
       JOIN metrics m ON m.id = r.metric_id
       WHERE ${conditions.join(" AND ")}
       ORDER BY r.report_date DESC, s.platform, s.name, m.name
       LIMIT 20000`,
      bindings,
    );

    const header = ["平台", "店铺", "指标", "分类", "单位", "数值", "日期", "目标", "备注"];
    const lines = [
      header.map(csvCell).join(","),
      ...rows.map((row) =>
        [
          row.platform,
          row.shop,
          row.metric,
          row.category,
          row.unit,
          row.textValue || row.value,
          row.date,
          row.target === null ? "" : `${row.operator ?? ""}${row.target}`,
          row.note,
        ].map(csvCell).join(","),
      ),
    ];

    return new Response(`\uFEFF${lines.join("\r\n")}`, {
      headers: {
        "content-type": "text/csv; charset=utf-8",
        "content-disposition": `attachment; filename="kefu-${type}-${from}-${to}.csv"`,
        "cache-control": "no-store",
      },
    });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : "导出失败" },
      { status: 500 },
    );
  }
}
