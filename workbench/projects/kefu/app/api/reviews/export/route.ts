import { reviewWhere, reviewsDb, runReviewPython } from "@/lib/reviews";
import { reviewOrder } from "@/lib/review-order";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    const params = new URL(request.url).searchParams;
    const { clause, bindings } = reviewWhere(params);
    const db = reviewsDb();
    const total = (db.prepare(`SELECT COUNT(*) AS count FROM negative_reviews WHERE ${clause}`).get(...bindings) as { count: number }).count;
    if (total > 50_000) return Response.json({ error: "超过 50000 条，请缩小筛选范围后导出。" }, { status: 400 });
    const rows = db.prepare(`SELECT * FROM negative_reviews WHERE ${clause} ORDER BY ${reviewOrder(params)}`).all(...bindings);
    const buffer = await runReviewPython(["--export"], JSON.stringify(rows));
    return new Response(new Uint8Array(buffer), { headers: {
      "content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      "content-disposition": `attachment; filename*=UTF-8''${encodeURIComponent(`差评汇总-${params.get("from") || "全部"}-${params.get("to") || "全部"}.xlsx`)}`,
      "cache-control": "no-store",
    } });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "导出失败" }, { status: 400 });
  }
}
