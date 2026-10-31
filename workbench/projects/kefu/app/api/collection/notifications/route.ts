import { checkReviewMutation } from "@/lib/review-request";
import { metricCommand } from "@/lib/metrics-collection";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  try { return Response.json(await metricCommand(["notifications", "get"])); }
  catch (error) { return Response.json({ error: error instanceof Error ? error.message : "读取配置失败" }, { status: 400 }); }
}

export async function PUT(request: Request) {
  try {
    checkReviewMutation(request);
    return Response.json(await metricCommand(["notifications", "save", "--input-stdin"], await request.json()));
  } catch (error) { return Response.json({ error: error instanceof Error ? error.message : "保存配置失败" }, { status: 400 }); }
}
