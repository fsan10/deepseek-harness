import { reviewsDb } from "@/lib/reviews";
import { readReviewLogs } from "@/lib/review-logs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    return Response.json(readReviewLogs(reviewsDb(), new URL(request.url).searchParams), {
      headers: { "cache-control": "no-store" },
    });
  } catch {
    return Response.json({ error: "日志读取失败，请检查采集数据库和日志类型后重试。" }, { status: 400 });
  }
}
