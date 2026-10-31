import { runCommerceCli, ensureReviewWorker } from "@/lib/reviews";
import { checkReviewMutation } from "@/lib/review-request";

export const runtime = "nodejs";

export async function POST(request: Request) {
  try {
    checkReviewMutation(request);
    const body = await request.json();
    ensureReviewWorker(request);
    const result = await runCommerceCli(["reviews", "collect", "--input-stdin"], JSON.stringify(body));
    return Response.json(result, { status: 202 });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "创建采集任务失败" }, { status: 400 });
  }
}
