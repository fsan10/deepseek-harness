import { readFile } from "node:fs/promises";
import path from "node:path";

export const runtime = "nodejs";

export async function GET() {
  try {
    const content = await readFile(path.join(process.cwd(), "API_IMPORT.md"), "utf8");
    return new Response(content, { headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-cache" } });
  } catch {
    return Response.json({ error: "接口说明暂时无法读取。" }, { status: 500 });
  }
}
