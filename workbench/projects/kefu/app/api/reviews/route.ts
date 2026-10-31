import { reviewWhere, reviewsDb } from "@/lib/reviews";
import { reviewOrder } from "@/lib/review-order";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    const params = new URL(request.url).searchParams;
    const { clause, bindings } = reviewWhere(params);
    const db = reviewsDb();
    const pageInput = Number(params.get("page") || 1);
    const page = Number.isFinite(pageInput) ? Math.max(1, Math.trunc(pageInput)) : 1;
    const sizeInput = Number(params.get("pageSize") || 20);
    const pageSize = Number.isFinite(sizeInput) ? Math.min(100, Math.max(10, Math.trunc(sizeInput))) : 20;
    const order = reviewOrder(params);
    const summary = db.prepare(`SELECT COUNT(*) AS total,
      COALESCE(SUM(review_level='差评'),0) AS negative,
      COALESCE(SUM(review_level='中评'),0) AS neutral,
      COUNT(DISTINCT profile_id) AS shops,
      COALESCE(SUM(product_code=''),0) AS missingCodes
      FROM negative_reviews WHERE ${clause}`).get(...bindings) as { total: number };
    const pages = Math.max(1, Math.ceil(summary.total / pageSize));
    const activePage = Math.min(page, pages);
    const rows = db.prepare(`SELECT * FROM negative_reviews WHERE ${clause} ORDER BY ${order} LIMIT ? OFFSET ?`).all(...bindings, pageSize, (activePage - 1) * pageSize);
    const keywords = ["口感", "宣传不符", "赠品", "客服服务", "退款售后", "物流发货", "包装品质", "价格", "回购意愿"]
      .map((name) => ({ name, count: (db.prepare(`SELECT COUNT(*) AS count FROM negative_reviews WHERE ${clause} AND keywords LIKE ?`).get(...bindings, `%${name}%`) as { count: number }).count }))
      .filter((item) => item.count > 0).sort((a, b) => b.count - a.count);
    const products = db.prepare(`SELECT product_id,product_name,COUNT(*) AS count FROM negative_reviews WHERE ${clause} GROUP BY product_id ORDER BY count DESC,product_id LIMIT 5`).all(...bindings);
    const shops = db.prepare("SELECT DISTINCT shop_name FROM negative_reviews UNION SELECT shop_name FROM review_profiles WHERE excluded=0 AND shop_name<>'' ORDER BY shop_name").all();
    const collectionActivity = db.prepare("SELECT start_date,end_date,status,created_at FROM review_runs ORDER BY created_at DESC LIMIT 1").get() ?? null;
    return Response.json({ rows, summary, keywords, products, shops, collectionActivity, pagination: { page: activePage, pageSize, total: summary.total, pages } });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "评价数据读取失败" }, { status: 400 });
  }
}
