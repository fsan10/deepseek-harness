"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { Panel } from "@/components/ui/Panel";
import { Pagination } from "@/components/ui/Pagination";
import { SearchField } from "@/components/ui/SearchField";
import { Select } from "@/components/ui/Select";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import type { Tone } from "@/lib/format";
import { jsonRequest, queryString } from "@/lib/client";
import { formatDateTime } from "@/lib/date";
import { EVENT_SOURCE, eventCategory, eventStatus, type CollectionEvent } from "@/lib/collection-meta";
import { LogDrawer } from "./LogDrawer";
import styles from "./Collection.module.css";

type EventsData = {
  events: CollectionEvent[];
  summary: { open: number; recovered: number; shops: number };
  pagination: { page: number; pages: number; total: number; pageSize: number };
};

const STATUS_OPTIONS = [{ value: "open", label: "待处理" }, { value: "recovered", label: "已恢复" }, { value: "all", label: "全部状态" }];
const SOURCE_OPTIONS = [{ value: "", label: "全部来源" }, { value: "service", label: "登录检查" }, { value: "run", label: "采集任务" }];
const ALERT_STATUS: Record<string, { label: string; tone: Tone }> = {
  sent: { label: "已发送", tone: "good" },
  failed: { label: "发送失败", tone: "danger" },
  pending: { label: "等待发送", tone: "warning" },
  disabled: { label: "提醒未启用", tone: "neutral" },
  sending: { label: "发送中", tone: "neutral" },
};

export function EventPanel() {
  const [status, setStatus] = useState("open");
  const [source, setSource] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<EventsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [drawer, setDrawer] = useState<{ view: "runs" | "service"; runId?: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      setData(await jsonRequest<EventsData>(`/api/collection/events?${queryString({ status, source, q: query.trim(), page })}`));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "读取异常记录失败");
    } finally {
      setLoading(false);
    }
  }, [status, source, query, page]);

  useEffect(() => {
    // 只有筛选变化才重新读取，避免与快照轮询叠加。
    const timer = setTimeout(() => { void load(); }, query ? 260 : 0);
    return () => clearTimeout(timer);
  }, [load, query]);

  const summary = data?.summary;

  return <>
    <Panel
      title="异常记录"
      subtitle="服务登录检查与采集任务的统一汇总；同一店铺持续失效合并为一条并关联失败任务，飞书提醒发送结果记在同一条里"
      action={<Button size="sm" icon="refresh" disabled={loading} onClick={() => void load()}>刷新</Button>}
    >
      <div className={styles.logTabs}>
        <div className={styles.logToolbar}>
          <Select className={styles.toolbarSelect} ariaLabel="处理状态" options={STATUS_OPTIONS} value={status}
            onChange={(value) => { setStatus(value); setPage(1); }} />
          <Select className={styles.toolbarSelect} ariaLabel="异常来源" options={SOURCE_OPTIONS} value={source}
            onChange={(value) => { setSource(value); setPage(1); }} />
          <SearchField className={styles.toolbarSearch} placeholder="搜索店铺或原因" value={query}
            onChange={(event) => { setQuery(event.target.value); setPage(1); }} />
        </div>
        <span className={styles.toolbarMeta}>
          待处理 {summary?.open ?? 0} · 已恢复 {summary?.recovered ?? 0} · 受影响店铺 {summary?.shops ?? 0}
        </span>
      </div>
      {error ? <ErrorState message={error} onRetry={() => void load()} /> : loading ? <Skeleton rows={5} /> : data?.events.length ? <>
        <div className="table-wrap table-scroll">
          <table className="table">
            <thead><tr>
              <th style={{ width: 110 }}>来源</th>
              <th style={{ width: 150 }}>最近发生</th>
              <th style={{ width: 170 }}>平台 / 店铺</th>
              <th style={{ width: 130 }}>关联任务</th>
              <th>原因</th>
              <th style={{ width: 96 }}>状态</th>
              <th style={{ width: 120 }}>提醒</th>
            </tr></thead>
            <tbody>{data.events.map((event) => {
              const category = eventCategory(event.category);
              const state = eventStatus(event.status);
              const lastRun = event.run_ids[event.run_ids.length - 1];
              const alert = ALERT_STATUS[event.alert_status];
              const open = expanded === event.id;
              return <Fragment key={event.id}>
                <tr>
                  <td><Chip tone="neutral">{event.sources.map((item) => EVENT_SOURCE[item] ?? item).join(" · ")}</Chip></td>
                  <td>
                    {formatDateTime(event.last_seen_at)}
                    {event.first_seen_at !== event.last_seen_at ? <div className="meta">首次 {formatDateTime(event.first_seen_at)}</div> : null}
                  </td>
                  <td>
                    <div className={styles.eventShop}>
                      <strong>{event.shop_name || "服务级"}</strong>
                      <span>{event.platform_name}</span>
                    </div>
                  </td>
                  <td>
                    {lastRun
                      ? <button type="button" className={styles.checkLink} onClick={() => setDrawer({ view: "runs", runId: lastRun })}>
                          {event.task_count > 1 ? `查看任务（${event.task_count}）` : "查看任务"}
                        </button>
                      : <button type="button" className={styles.checkLink} onClick={() => setDrawer({ view: "service" })}>查看服务日志</button>}
                  </td>
                  <td>
                    <Chip tone={category.tone}>{category.label}</Chip>
                    <div className={styles.eventMessage}>{event.message || "—"}</div>
                  </td>
                  <td>
                    <Chip tone={state.tone}>{state.label}</Chip>
                    {event.recovered_at ? <div className="meta">{formatDateTime(event.recovered_at)}</div> : null}
                  </td>
                  <td>
                    <button type="button" className={styles.checkLink} aria-expanded={open}
                      onClick={() => setExpanded(open ? null : event.id)}>
                      {alert ? `${alert.label}${event.alerts.length > 1 ? ` · ${event.alerts.length} 条` : ""}` : "无提醒记录"}
                    </button>
                  </td>
                </tr>
                {open ? <tr>
                  <td colSpan={7} style={{ background: "var(--surface-2)" }}>
                    {event.alerts.length ? <table className="table" style={{ background: "transparent" }}>
                      <thead><tr><th style={{ width: 160 }}>发送时间</th><th style={{ width: 110 }}>结果</th><th>提醒内容</th><th style={{ width: 220 }}>失败原因</th></tr></thead>
                      <tbody>{event.alerts.map((item) => (
                        <tr key={`${item.created_at}-${item.status}-${item.message.slice(0, 12)}`}>
                          <td>{formatDateTime(item.created_at)}</td>
                          <td><Chip tone={(ALERT_STATUS[item.status] ?? { tone: "neutral" as Tone }).tone}>{(ALERT_STATUS[item.status] ?? { label: item.status }).label}</Chip></td>
                          <td className={styles.eventMessage}>{item.message || "—"}</td>
                          <td className={styles.eventMessage}>{item.error_summary || "—"}</td>
                        </tr>
                      ))}</tbody>
                    </table> : <p className="meta">这条异常没有对应的飞书提醒记录（提醒未启用或未达到发送条件）。</p>}
                  </td>
                </tr> : null}
              </Fragment>;
            })}</tbody>
          </table>
        </div>
        {data.pagination.total > data.pagination.pageSize ? <Pagination {...data.pagination} label="条异常" onChange={setPage} /> : null}
      </> : <EmptyState title={status === "open" ? "当前没有待处理异常" : "没有匹配的异常记录"}
        description={status === "open" ? "登录失效、检查异常与采集失败会汇总到这里，提醒发送结果一并显示。" : "调整状态或搜索条件后再试。"} compact />}
    </Panel>

    {drawer ? <LogDrawer view={drawer.view} runId={drawer.runId} switchable onClose={() => setDrawer(null)} /> : null}
  </>;
}
