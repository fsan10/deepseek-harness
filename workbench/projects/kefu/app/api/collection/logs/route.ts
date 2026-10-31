import { metricsDb } from "@/lib/metrics-collection";
import { readCollectionLogs } from "@/lib/collection-logs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    return Response.json(readCollectionLogs(metricsDb(), new URL(request.url).searchParams), {
      headers: { "cache-control": "no-store" },
    });
  } catch {
    return Response.json({ error: "日志读取失败，请检查采集数据库后重试。" }, { status: 400 });
  }
}
