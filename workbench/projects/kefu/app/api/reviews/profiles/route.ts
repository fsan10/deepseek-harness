import { ensureReviewWorker, reviewsDb } from "@/lib/reviews";
import { checkReviewMutation } from "@/lib/review-request";
import { metricCommand } from "@/lib/metrics-collection";
import { REPORTING_SHOPS } from "@/db/reporting-config";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  return Response.json({ profiles: reviewsDb().prepare("SELECT * FROM review_profiles ORDER BY excluded,shop_name,profile_name").all() });
}

export async function POST(request: Request) {
  try {
    checkReviewMutation(request);
    await metricCommand(["profiles", "--refresh", "--input-stdin"], { shops: REPORTING_SHOPS });
    ensureReviewWorker(request);
    return GET();
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "无法连接 Cloak Login" }, { status: 400 });
  }
}
