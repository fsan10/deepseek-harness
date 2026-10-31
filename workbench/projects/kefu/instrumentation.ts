export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs" && process.env.NEXT_PHASE !== "phase-production-build") {
    const { ensureReviewWorker } = await import("./lib/reviews");
    try { ensureReviewWorker(); } catch { console.error("差评采集进程未启动，请在差评汇总分析页检查运行环境。"); }
    const supervisor = setInterval(() => { try { ensureReviewWorker(); } catch { /* 页面显示运行环境诊断。 */ } }, 30_000);
    supervisor.unref();
  }
}
