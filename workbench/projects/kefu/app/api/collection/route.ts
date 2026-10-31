import { checkReviewMutation } from "@/lib/review-request";
import { collectionKind, ensureMetricWorker, metricCommand, metricSnapshot } from "@/lib/metrics-collection";
import { REPORTING_SHOPS } from "@/db/reporting-config";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 360;

export async function GET(request: Request) {
  try {
    const value = new URL(request.url).searchParams.get("kind");
    const kind = value ? collectionKind(value) : undefined;
    let workerError = "";
    try { ensureMetricWorker(request); } catch (error) { workerError = error instanceof Error ? error.message : "采集服务不可用"; }
    return Response.json({ ...metricSnapshot(kind), workerError });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "读取采集信息失败" }, { status: 400 });
  }
}

export async function POST(request: Request) {
  try {
    checkReviewMutation(request);
    const body = await request.json();
    if (typeof body !== "object" || !body || Array.isArray(body)) throw new Error("请求需要 JSON 对象。");
    const { action } = body;
    let result;
    if (action === "sync") result = await metricCommand(["profiles", "--refresh", "--input-stdin"], { shops: REPORTING_SHOPS });
    else if (action === "mapping" || action === "configure") result = await metricCommand([action, "--input-stdin"], { ...body, shops: REPORTING_SHOPS });
    else if (action === "batch-configure") result = await metricCommand(["batch-configure", "--input-stdin"], { ...body, shops: REPORTING_SHOPS });
    else if (action === "availability") result = await metricCommand(["availability", "--input-stdin"], body);
    else if (action === "login" || action === "status") {
      if (typeof body.profileId !== "string" || !/^[A-Za-z0-9_-]{1,100}$/.test(body.profileId)) throw new Error("请先选择店铺。");
      result = await metricCommand(["auth", action, "--profile", body.profileId], undefined, action === "login" ? 330_000 : 65_000);
    } else if (action === "collect" || action === "retry" || action === "cancel") {
      collectionKind(body.kind);
      result = await metricCommand(["collect", "--input-stdin"], body);
    } else throw new Error("采集操作无效。");
    ensureMetricWorker(request);
    return Response.json(result, { status: action === "collect" || action === "retry" ? 202 : 200 });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "采集操作失败" }, { status: 400 });
  }
}

export async function PUT(request: Request) {
  try {
    checkReviewMutation(request);
    const body = await request.json();
    const result = await metricCommand([body.plan_order !== undefined ? "plan-order" : body.kind ? "settings" : "service", "--input-stdin"], body);
    ensureMetricWorker(request);
    return Response.json(result);
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "保存设置失败" }, { status: 400 });
  }
}
