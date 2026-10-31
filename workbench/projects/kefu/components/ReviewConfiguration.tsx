"use client";

import { useCallback, useEffect, useState } from "react";
import { ReviewLogs } from "@/components/ReviewLogs";
import { Button } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Panel";
import { ErrorState } from "@/components/ui/States";
import { ToggleSetting } from "@/components/ui/ToggleSetting";
import { jsonBody, jsonRequest } from "@/lib/client";
import { formatDateTime } from "@/lib/date";
import type { ReviewRunsResponse, ReviewSettings } from "@/lib/types";
import styles from "./MetricCollection.module.css";

export function ReviewConfiguration({ authPoll, onSaved }: { authPoll: number; onSaved: () => void }) {
  const [settings, setSettings] = useState<ReviewSettings | null>(null);
  const [form, setForm] = useState({ enabled: false, frequency_days: 1, lookback_days: 1, run_at: "09:00" });
  const [runs, setRuns] = useState<ReviewRunsResponse | null>(null);
  const [logs, setLogs] = useState<"service" | "scheduled" | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [checkedAt, setCheckedAt] = useState(0);

  const loadRuns = useCallback(async () => {
    setRuns(await jsonRequest<ReviewRunsResponse>("/api/reviews/runs"));
    setCheckedAt(Date.now());
  }, []);
  useEffect(() => {
    let alive = true;
    void Promise.resolve().then(() => Promise.all([jsonRequest<{ settings: ReviewSettings; workerError: string }>("/api/reviews/settings"), loadRuns()])).then(([result]) => {
      if (!alive) return;
      setSettings(result.settings);
      setForm({ enabled: Boolean(result.settings.enabled), frequency_days: result.settings.frequency_days, lookback_days: result.settings.lookback_days, run_at: result.settings.run_at });
      if (result.workerError) setError(result.workerError);
    }).catch((caught: Error) => { if (alive) setError(caught.message); });
    const timer = setInterval(() => void loadRuns().catch(() => {}), 5000);
    return () => { alive = false; clearInterval(timer); };
  }, [loadRuns]);

  async function save() {
    setSaving(true); setError("");
    try {
      const result = await jsonRequest<{ settings: ReviewSettings }>("/api/reviews/settings", jsonBody("PUT", { ...form, auth_poll_minutes: authPoll }));
      setSettings(result.settings); onSaved();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "保存失败"); }
    finally { setSaving(false); }
  }
  const workerOnline = runs?.worker?.message === "运行中" && Date.parse(runs.worker.heartbeat_at) > checkedAt - 90_000;
  const lastRun = runs?.runs.find((run) => run.trigger_type === "scheduled");

  return <>
    {error ? <ErrorState message={error} onRetry={() => void loadRuns().catch((caught: Error) => setError(caught.message))} /> : null}
    <div className="grid-settings">
      <Panel title="评论定时采集" subtitle="按北京时间执行 · 仅采集抖音中评与差评" action={<button className="link" type="button" onClick={() => setLogs("scheduled")}>查看运行日志</button>}>
        <ToggleSetting label="启用定时采集" ariaLabel="启用评论定时采集" checked={form.enabled} description={form.enabled ? "按下方计划自动采集启用中的店铺" : "当前未启用"} onChange={(enabled) => setForm((old) => ({ ...old, enabled }))} />
        <div className={styles.formGrid} style={{ marginTop: 22 }}>
          <div className="form-row"><label htmlFor="review-frequency">间隔天数</label><input id="review-frequency" className="input" type="number" min={1} max={365} value={form.frequency_days} onChange={(e) => setForm((old) => ({ ...old, frequency_days: Number(e.target.value) }))} /></div>
          <div className="form-row"><label htmlFor="review-lookback">默认回溯天数</label><input id="review-lookback" className="input" type="number" min={1} max={365} value={form.lookback_days} onChange={(e) => setForm((old) => ({ ...old, lookback_days: Number(e.target.value) }))} /></div>
          <div className="form-row"><label htmlFor="review-run-time">执行时间</label><input id="review-run-time" className="input" type="time" value={form.run_at} onChange={(e) => setForm((old) => ({ ...old, run_at: e.target.value }))} /></div>
        </div>
        <div className="collection-schedule-footer"><span className="meta">下次执行：{settings?.enabled ? formatDateTime(settings.next_run_at) : "未启用"}</span><Button variant="primary" disabled={saving || !settings} onClick={() => void save()}>{saving ? "保存中…" : "保存计划"}</Button></div>
      </Panel>
      <Panel title="服务状态" subtitle="评论采集服务">
        <div className="info-list"><div className="info-row"><span>采集服务</span><span className={workerOnline ? "is-good" : "is-warning"}>{workerOnline ? "运行中" : "等待启动"}</span></div>
          <div className="info-row"><span>采集队列</span><span>{runs?.runs.some((run) => ["queued", "running"].includes(run.status)) ? "任务进行中" : "队列空闲"}</span></div>
          <div className="info-row"><span>最近定时采集</span><span>{formatDateTime(lastRun?.created_at)}</span></div></div>
        <button className="link" type="button" style={{ marginTop: 16 }} onClick={() => setLogs("service")}>查看采集服务日志</button>
      </Panel>
    </div>
    {logs ? <ReviewLogs kind={logs} onClose={() => setLogs(null)} /> : null}
  </>;
}
