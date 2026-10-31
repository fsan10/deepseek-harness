"use client";

import { useState } from "react";
import { Chip } from "@/components/ui/Chip";
import { EmptyState } from "@/components/ui/States";
import { formatDateTime } from "@/lib/date";
import { authStatus, runStatus } from "@/lib/review-status";
import { EVENT_SOURCE, RUN_TRIGGER_LABEL, eventCategory, eventStatus, type ServiceLogData, type UnifiedRun } from "@/lib/collection-meta";
import styles from "./Collection.module.css";

export function formatDuration(start?: string | null, end?: string | null) {
  if (!start || !end) return "—";
  const delta = Date.parse(end) - Date.parse(start);
  if (!Number.isFinite(delta) || delta < 0) return "—";
  const seconds = Math.round(delta / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m${String(seconds % 60).padStart(2, "0")}s`;
  return `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, "0")}m`;
}

export function RunDetailList({ runs }: { runs: UnifiedRun[] }) {
  const [open, setOpen] = useState<string[]>([]);
  if (!runs.length) return <EmptyState title="暂无采集任务" description="手动或定时任务开始后会出现在这里。" compact />;
  return <div className={styles.runList}>{runs.map((run) => {
    const key = `${run.source}-${run.id}`;
    const expanded = open.includes(key);
    const state = runStatus(run.status);
    return <div className={styles.runRow} key={key}>
      <button type="button" className={styles.runSummary} aria-expanded={expanded}
        onClick={() => setOpen((old) => old.includes(key) ? old.filter((item) => item !== key) : [...old, key])}>
        <Chip tone={state.tone}>{state.label}</Chip>
        <span className={styles.grow}>
          <span className={styles.runTitle}>
            <strong>{run.label}</strong>
            <span className={styles.runMeta}>{formatDateTime(run.created_at)} · {RUN_TRIGGER_LABEL[run.trigger_type] ?? run.trigger_type}</span>
          </span>
          <span className={styles.runMeta}>
            {run.start_date === run.end_date ? run.start_date : `${run.start_date} ~ ${run.end_date}`} · {run.items.length} 家 · {run.collected_count} 条 · {formatDuration(run.started_at, run.finished_at)}
          </span>
        </span>
        <span className={styles.runMeta}>{expanded ? "收起" : "详情"}</span>
      </button>
      {expanded ? <div className={styles.runBody}>
        <p className="meta" style={{ marginBottom: 10 }}>{run.message || "任务未记录额外说明"} · 任务 {run.id}</p>
        {run.items.length ? <div className="table-wrap table-scroll">
          <table className="table">
            <thead><tr><th>店铺</th><th>日期</th><th>状态</th><th>条数</th><th>说明</th></tr></thead>
            <tbody>{run.items.map((item) => {
              const itemState = runStatus(item.status);
              return <tr key={`${item.profile_id}-${item.span}`}>
                <td className={styles.runShopName}>{item.shop_name}</td>
                <td>{item.span}</td>
                <td><Chip tone={itemState.tone}>{itemState.label}</Chip></td>
                <td>{item.count}</td>
                <td className={styles.eventMessage}>{item.message || "—"}</td>
              </tr>;
            })}</tbody>
          </table>
        </div> : <p className="meta">尚无店铺执行记录</p>}
      </div> : null}
    </div>;
  })}</div>;
}

export function ServiceBlock({ data, compact = false }: { data: ServiceLogData; compact?: boolean }) {
  const auth = compact ? data.auth.slice(0, 8) : data.auth;
  const events = compact ? data.events.slice(0, 5) : data.events;
  const counts = data.auth.reduce((acc, item) => {
    const key = item.state === "valid" ? "valid" : item.state === "auth_required" ? "auth" : item.state === "needs_human" ? "human" : "other";
    return { ...acc, [key]: acc[key] + 1 };
  }, { valid: 0, auth: 0, human: 0, other: 0 });
  return <>
    <div className="notice" role="status">
      {data.worker
        ? `${data.worker.message || "未记录状态"} · 心跳 ${formatDateTime(data.worker.heartbeat_at)} · 进行中任务 ${data.running} 个`
        : "尚无采集服务心跳记录"}
    </div>
    <p className="meta" style={{ marginTop: 8 }}>
      登录有效 {counts.valid} 家 · 需重新登录 {counts.auth} 家 · 待人工处理 {counts.human} 家
    </p>
    {auth.length ? <div className="table-wrap table-scroll" style={{ marginTop: 10 }}>
      <table className="table">
        <thead><tr><th>店铺</th><th>平台</th><th>登录状态</th><th>检查时间</th><th>说明</th></tr></thead>
        <tbody>{auth.map((item) => {
          const state = authStatus(item.state);
          return <tr key={item.profile_id}>
            <td>{item.shop_name}{item.disabled ? <div className="meta">已停用</div> : null}</td>
            <td>{item.platform_name}</td>
            <td><Chip tone={state.tone}>{state.label}</Chip></td>
            <td>{formatDateTime(item.checked_at)}</td>
            <td className={styles.eventMessage}>{item.message || "—"}</td>
          </tr>;
        })}</tbody>
      </table>
    </div> : <EmptyState title="尚无登录检查记录" description="采集服务会按检查间隔逐店核对登录状态。" compact />}
    <h3 className="meta" style={{ marginTop: 16, marginBottom: 6 }}>登录检查事件</h3>
    {events.length ? <div className="table-wrap table-scroll">
      <table className="table">
        <thead><tr><th>最近发生</th><th>类别</th><th>店铺</th><th>说明</th><th>状态</th></tr></thead>
        <tbody>{events.map((event) => {
          const category = eventCategory(event.category);
          return <tr key={event.id}>
            <td>{formatDateTime(event.last_seen_at)}</td>
            <td><Chip tone={category.tone}>{category.label}</Chip></td>
            <td>{event.shop_name || "—"}</td>
            <td className={styles.eventMessage}>{event.message || "—"}</td>
            <td><Chip tone={eventStatus(event.status).tone}>{eventStatus(event.status).label}</Chip></td>
          </tr>;
        })}</tbody>
      </table>
    </div> : <EmptyState title="暂无登录检查事件" description="登录失效、检查异常与恢复会记录在这里。" compact />}
  </>;
}

export function EventSourceLabel({ event }: { event: { sources: string[] } }) {
  return <>{event.sources.map((source) => EVENT_SOURCE[source as "service" | "run"] ?? source).join(" · ")}</>;
}
