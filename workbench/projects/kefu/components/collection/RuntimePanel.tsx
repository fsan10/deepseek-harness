"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { Panel } from "@/components/ui/Panel";
import { ErrorState, Skeleton } from "@/components/ui/States";
import { jsonRequest, queryString } from "@/lib/client";
import { formatDateTime } from "@/lib/date";
import { runStatus } from "@/lib/review-status";
import type { MetricSnapshot } from "@/lib/metric-types";
import type { RunLogData } from "@/lib/collection-meta";
import { LogDrawer } from "./LogDrawer";
import { formatDuration } from "./LogViews";
import styles from "./Collection.module.css";

function resultClass(status: string) {
  if (status === "success") return styles.loginGood;
  if (status === "failed") return styles.loginDanger;
  if (status === "partial" || status === "needs_human") return styles.loginWarn;
  return styles.loginIdle;
}

function shortStamp(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(date).replace(/\//g, "-");
}

export function RuntimePanel({ snapshot, workerError, busy, checkedAt, refreshKey, onSaveAuthPoll }: {
  snapshot: MetricSnapshot | null;
  workerError: string;
  busy: boolean;
  checkedAt: number;
  refreshKey: string;
  onSaveAuthPoll: (minutes: number) => Promise<void>;
}) {
  const [authDraft, setAuthDraft] = useState<number | null>(null);
  const [runs, setRuns] = useState<RunLogData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [drawer, setDrawer] = useState(false);

  const authPoll = authDraft ?? snapshot?.service.auth_poll_minutes ?? 15;

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      setRuns(await jsonRequest<RunLogData>(`/api/collection/logs?${queryString({ view: "runs", page: 1 })}`));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "读取运行日志失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // 日志只在进入分区或手动刷新时读取一次，不跟随 5 秒快照轮询。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load, refreshKey]);

  const worker = snapshot?.worker ?? null;
  const heartbeatAge = worker && checkedAt ? Math.max(0, Math.round((checkedAt - Date.parse(worker.heartbeat_at)) / 1000)) : null;
  const online = Boolean(worker && worker.message === "运行中" && heartbeatAge !== null && heartbeatAge < 45);
  const activeRuns = (snapshot?.runs ?? []).filter((run) => ["queued", "running"].includes(run.status)).length;
  const rows = (runs?.runs ?? []).slice(0, 5);

  return <>
    {workerError ? <ErrorState message={workerError} /> : null}
    <div className={styles.serviceGrid}>
      <Panel title="采集服务" subtitle="只读诊断 · 心跳与队列状态"
        action={<Chip tone={online ? "good" : "neutral"}>{online ? "运行中" : "等待启动"}</Chip>}>
        <div className={styles.infoRows}>
          <div><span>最近心跳</span><span>{worker ? `${formatDateTime(worker.heartbeat_at)}（${heartbeatAge} 秒前）` : "—"}</span></div>
          <div><span>采集队列</span><span>{activeRuns ? `${activeRuns} 个任务进行中` : "空闲 · 无进行中任务"}</span></div>
          <div><span>Worker 进程</span><span>{worker?.pid ? `PID ${worker.pid}` : "—"}</span></div>
          <div><span>数据库</span><span>data/kefu.sqlite · WAL</span></div>
          <div><span>本机时间</span><span>{checkedAt ? `${formatDateTime(new Date(checkedAt).toISOString())} · Asia/Shanghai` : "—"}</span></div>
        </div>
      </Panel>
      <Panel title="登录状态检查" subtitle="三类采集共用一次检查，同一店铺只查一次。">
        <div className="form-row">
          <label htmlFor="collection-auth-poll">检查间隔（分钟）</label>
          <div className={styles.inlineControl}>
            <input id="collection-auth-poll" className="input" type="number" min={1} max={1440}
              value={authPoll} onChange={(event) => setAuthDraft(Number(event.target.value))} />
            <Button disabled={busy} onClick={() => { void onSaveAuthPoll(authPoll).then(() => setAuthDraft(null)); }}>
              {busy ? "保存中…" : "保存"}
            </Button>
          </div>
        </div>
        <p className="meta" style={{ marginTop: 12, lineHeight: 1.7 }}>
          仅检查启用且打开「自动检查登录状态」的店铺，可在店铺配置抽屉关闭。采集时发现会话失效会自动登录并继续任务，遇验证码、滑块等验证时通知人工。
        </p>
      </Panel>
    </div>

    <Panel title="运行日志" subtitle="最近 20 次任务 · 只读；点开可见每家店铺的结果与失败原因"
      action={<button type="button" className="link" onClick={() => setDrawer(true)}>打开日志抽屉</button>}>
      {error ? <ErrorState message={error} onRetry={() => void load()} /> : loading ? <Skeleton rows={4} /> : rows.length ? (
        <div className="table-wrap table-scroll">
          <table className="table">
            <thead><tr>
              <th style={{ width: 110 }}>开始时间</th>
              <th style={{ width: 110 }}>类型</th>
              <th style={{ width: 80 }}>触发</th>
              <th>结果</th>
              <th style={{ width: 64 }}>店铺</th>
              <th style={{ width: 64 }}>耗时</th>
            </tr></thead>
            <tbody>{rows.map((run) => {
              const state = runStatus(run.status);
              const done = run.items.filter((item) => ["success", "no_data", "skipped"].includes(item.status)).length;
              return <tr key={`${run.source}-${run.id}`}>
                <td style={{ whiteSpace: "nowrap" }}>{shortStamp(run.created_at)}</td>
                <td>{run.label}</td>
                <td>{run.trigger_type === "scheduled" ? "定时" : "手动"}</td>
                <td>
                  <span className={resultClass(run.status)}>{state.label}{run.items.length ? ` · ${done}/${run.items.length}` : ""}</span>
                  {run.status !== "success" && run.message ? <div className="meta">{run.message}</div> : null}
                </td>
                <td>{run.items.length} 家</td>
                <td>{formatDuration(run.started_at, run.finished_at)}</td>
              </tr>;
            })}</tbody>
          </table>
        </div>
      ) : <p className="meta">还没有采集任务记录。</p>}
    </Panel>

    {drawer ? <LogDrawer view="runs" switchable onClose={() => setDrawer(false)} /> : null}
  </>;
}
