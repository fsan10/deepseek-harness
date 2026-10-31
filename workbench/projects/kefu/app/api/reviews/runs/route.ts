import { reviewsDb } from "@/lib/reviews";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const db = reviewsDb();
  const runs = db.prepare("SELECT * FROM review_runs ORDER BY created_at DESC LIMIT 10").all();
  const shops = db.prepare("SELECT * FROM review_run_shops WHERE run_id IN (SELECT id FROM review_runs ORDER BY created_at DESC LIMIT 10) ORDER BY shop_name").all();
  const worker = db.prepare("SELECT heartbeat_at,message FROM review_worker_state WHERE id=1").get();
  const settings = db.prepare("SELECT s.next_run_at,a.check_interval_minutes AS auth_poll_minutes FROM review_settings s CROSS JOIN review_auth_settings a WHERE s.id=1 AND a.id=1").get();
  const auth = db.prepare("SELECT p.profile_id,p.shop_name,a.state,a.message,a.error_code,a.checked_at FROM review_profiles p LEFT JOIN review_auth_status a ON a.profile_id=p.profile_id WHERE p.excluded=0 ORDER BY p.shop_name").all();
  return Response.json({ runs: runs.map((run) => ({ ...run, shops: shops.filter((shop) => shop.run_id === run.id) })), worker: worker || null, settings, auth });
}
