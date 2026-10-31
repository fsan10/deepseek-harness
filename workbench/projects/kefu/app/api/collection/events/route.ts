import { metricsDb } from "@/lib/metrics-collection";
import { readCollectionEvents } from "@/lib/collection-events";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    return Response.json(readCollectionEvents(metricsDb(), new URL(request.url).searchParams), {
      headers: { "cache-control": "no-store" },
    });
  } catch {
    return Response.json({ error: "异常记录读取失败，请检查采集数据库后重试。" }, { status: 400 });
  }
}
