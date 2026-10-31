import fs from "node:fs";
import path from "node:path";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const file = path.join(process.cwd(), "automation", "import_template.csv");
  try {
    const content = fs.readFileSync(file, "utf8").replace(/^\uFEFF/, "");
    return new Response(`\uFEFF${content}`, {
      headers: {
        "content-type": "text/csv; charset=utf-8",
        "content-disposition": 'attachment; filename="kefu-import-template.csv"',
        "cache-control": "no-store",
      },
    });
  } catch {
    return Response.json({ error: "导入模板不存在，请检查 automation/import_template.csv" }, { status: 404 });
  }
}
