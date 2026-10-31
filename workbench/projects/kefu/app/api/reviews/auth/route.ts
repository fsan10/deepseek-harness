import { ensureReviewWorker, runCommerceCli } from "@/lib/reviews";
import { checkReviewMutation } from "@/lib/review-request";

export const runtime = "nodejs";
export const maxDuration = 360;

export async function POST(request: Request) {
  try {
    checkReviewMutation(request);
    const body = await request.json();
    if (!["login", "status"].includes(body.action)) throw new Error("认证操作无效。");
    if (typeof body.profileId !== "string" || !body.profileId || body.profileId.length > 100) throw new Error("请先选择一家店铺。");
    const data = await runCommerceCli(["auth", body.action, "--profile", body.profileId], undefined, body.action === "login" ? 360_000 : 60_000);
    ensureReviewWorker(request);
    return Response.json(data);
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "认证操作失败" }, { status: 400 });
  }
}
