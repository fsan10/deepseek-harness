import { ensureReviewWorker, reviewsDb } from "@/lib/reviews";
import { checkReviewMutation } from "@/lib/review-request";
import { ensureMetricWorker } from "@/lib/metrics-collection";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function settings() {
  return reviewsDb().prepare("SELECT s.*,a.check_interval_minutes AS auth_poll_minutes FROM review_settings s CROSS JOIN review_auth_settings a WHERE s.id=1 AND a.id=1").get();
}

export async function GET(request: Request) {
  let workerError = "";
  try { ensureReviewWorker(request); ensureMetricWorker(request); } catch (error) { workerError = error instanceof Error ? error.message : "采集进程启动失败"; }
  return Response.json({ settings: settings(), workerError });
}

export async function PUT(request: Request) {
  try {
    checkReviewMutation(request);
    const body = await request.json();
    const frequency = Number(body.frequency_days);
    const lookback = Number(body.lookback_days);
    const authPollValue = body.auth_poll_minutes;
    const authPoll = authPollValue === undefined ? null : Number(authPollValue);
    if (!Number.isInteger(frequency) || frequency < 1 || frequency > 365 || !Number.isInteger(lookback) || lookback < 1 || lookback > 365) throw new Error("频率和回溯天数需为 1 至 365 的整数。");
    if (authPoll !== null && (!Number.isInteger(authPoll) || authPoll < 1 || authPoll > 1440)) throw new Error("登录检查间隔需为 1 至 1440 分钟的整数。");
    if (typeof body.enabled !== "boolean" || typeof body.run_at !== "string" || !/^([01]\d|2[0-3]):[0-5]\d$/.test(body.run_at)) throw new Error("定时配置无效。");
    ensureReviewWorker(request);
    const db = reviewsDb();
    const old = db.prepare("SELECT * FROM review_settings WHERE id=1").get() as { enabled: number; frequency_days: number; run_at: string; next_run_at: string | null };
    // 只修改回溯天数时保留下一次执行时间。
    const keepNext = Boolean(old.enabled) === body.enabled && old.frequency_days === frequency && old.run_at === body.run_at;
    db.exec("BEGIN IMMEDIATE");
    try {
      db.prepare("UPDATE review_settings SET enabled=?,frequency_days=?,lookback_days=?,run_at=?,next_run_at=?,updated_at=? WHERE id=1")
        .run(body.enabled ? 1 : 0, frequency, lookback, body.run_at, keepNext ? old.next_run_at : null, new Date().toISOString());
      // 登录检查间隔已归属「运行与环境」，保存计划时不再顺带改写。
      if (authPoll !== null) db.prepare("UPDATE review_auth_settings SET check_interval_minutes=? WHERE id=1").run(authPoll);
      db.exec("COMMIT");
    } catch (error) { db.exec("ROLLBACK"); throw error; }
    return Response.json({ settings: settings() });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "保存配置失败" }, { status: 400 });
  }
}
