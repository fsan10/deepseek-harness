"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Topbar } from "@/components/shell/Topbar";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { DateRangeField } from "@/components/ui/DatePicker";
import { Icon } from "@/components/ui/Icon";
import { KpiCard } from "@/components/ui/KpiCard";
import { Modal } from "@/components/ui/Modal";
import { Pagination } from "@/components/ui/Pagination";
import { Panel } from "@/components/ui/Panel";
import { SearchField } from "@/components/ui/SearchField";
import { Select } from "@/components/ui/Select";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import { Toast, useToast } from "@/components/ui/Toast";
import { jsonBody, jsonRequest } from "@/lib/client";
import { daysBetween, formatDateTime, rangePresets, yesterdayISO } from "@/lib/date";
import type { Tone } from "@/lib/format";
import { METRIC_PLATFORM_NAMES, METRIC_STATE_NAMES, type MetricItem, type MetricKind, type MetricSnapshot } from "@/lib/metric-types";
import styles from "./MetricCollection.module.css";

const HISTORY_SIZE = 5;
const complete = (status: string) => ["success", "no_data", "skipped"].includes(status);
const active = (status: string) => ["queued", "running"].includes(status);
function tone(status: string): Tone {
  if (status === "success" || status === "valid") return "good";
  if (status === "running") return "brand";
  if (status === "failed" || status === "error") return "danger";
  if (["partial", "needs_human", "auth_required"].includes(status)) return "warning";
  return "neutral";
}

export function MetricCollection({ kind }: { kind: MetricKind }) {
  const label = kind === "reception" ? "接待量" : "店铺体验分";
  const analysisPath = kind === "reception" ? "/reception" : "/scores";
  const yesterday = yesterdayISO();
  const [snapshot, setSnapshot] = useState<MetricSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [checkedAt, setCheckedAt] = useState(0);
  const [error, setError] = useState("");
  const [platform, setPlatform] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [period, setPeriod] = useState({ from: yesterday, to: yesterday });
  const [busy, setBusy] = useState("");
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [historyPage, setHistoryPage] = useState(1);
  const [shopsOpen, setShopsOpen] = useState(false);
  const [shopQuery, setShopQuery] = useState("");
  const [draftShops, setDraftShops] = useState<string[]>([]);
  const taskPanel = useRef<HTMLDivElement>(null);
  const requestId = useRef(0);
  const { toast, notify } = useToast();

  const load = useCallback(async () => {
    const id = ++requestId.current;
    try {
      const result = await jsonRequest<MetricSnapshot>(`/api/collection?kind=${kind}`);
      if (id !== requestId.current) return;
      setSnapshot(result);
      setCheckedAt(Date.now());
      setError(result.workerError || "");
    } catch (caught) {
      if (id === requestId.current) setError(caught instanceof Error ? caught.message : "读取采集状态失败");
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [kind]);
  useEffect(() => {
    // Initial load and background polling share the same snapshot and preserve form edits.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    const timer = setInterval(() => void load(), 5000);
    return () => { clearInterval(timer); requestId.current += 1; };
  }, [load]);

  const profiles = snapshot?.profiles ?? [];
  const eligible = profiles.filter((profile) => !profile.excluded && !profile.disabled && profile.shop_name && profile[`${kind}_enabled`] && profile[`collect_${kind}`]);
  const available = eligible.filter((profile) => !platform || profile.platform === platform);
  const scope = available.filter((profile) => !selected.length || selected.includes(profile.profile_id));
  const runs = snapshot?.runs ?? [];
  const current = runs.find((run) => active(run.status));
  const focus = runs.find((run) => run.id === selectedRun) ?? current ?? runs[0];
  const items = focus?.items ?? [];
  const setting = snapshot?.settings.find((entry) => entry.kind === kind);
  const byShop = new Map<string, MetricItem[]>();
  items.forEach((item) => byShop.set(item.profile_id, [...(byShop.get(item.profile_id) ?? []), item]));
  const completedShops = [...byShop.values()].filter((shopItems) => shopItems.every((item) => complete(item.status))).length;
  const done = items.filter((item) => complete(item.status)).length;
  const humanCount = new Set(items.filter((item) => ["needs_human", "auth_required"].includes(item.status)).map((item) => item.profile_id)).size;
  const failedCount = new Set(items.filter((item) => ["failed", "error"].includes(item.status)).map((item) => item.profile_id)).size;
  const progress = items.length ? Math.round(done / items.length * 100) : 0;
  const periodValid = Boolean(period.from && period.to && period.from <= period.to && period.to <= yesterday && daysBetween(period.from, period.to) < 31);
  const canCollect = !loading && !busy && !current && scope.length > 0 && (kind === "score" || periodValid);
  const workerOnline = snapshot?.worker?.message === "运行中" && checkedAt - Date.parse(snapshot.worker.heartbeat_at) < 30_000;
  const heartbeatAgo = snapshot?.worker ? Math.max(0, Math.round((checkedAt - Date.parse(snapshot.worker.heartbeat_at)) / 1000)) : null;
  const historyPages = Math.max(1, Math.ceil(runs.length / HISTORY_SIZE));
  const activeHistoryPage = Math.min(historyPage, historyPages);
  const history = runs.slice((activeHistoryPage - 1) * HISTORY_SIZE, activeHistoryPage * HISTORY_SIZE);
  const platformOptions = [{ value: "", label: "全部平台" }, ...Object.entries(METRIC_PLATFORM_NAMES)
    .filter(([key]) => kind === "reception" || ["douyin", "tmall", "pinduoduo"].includes(key))
    .map(([value, name]) => ({ value, label: name }))];
  const visibleShops = available.filter((profile) => `${METRIC_PLATFORM_NAMES[profile.platform]} ${profile.shop_name}`.toLowerCase().includes(shopQuery.trim().toLowerCase()));

  async function refresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }
  async function action(name: "collect" | "retry" | "cancel", runId?: string) {
    setBusy(name + (runId || ""));
    setError("");
    try {
      if (name === "collect" && !scope.length) throw new Error("当前没有可采集的店铺，请先同步并核对映射。");
      if (name === "collect" && kind === "reception" && !periodValid) throw new Error("请选择不晚于昨天、起止顺序正确且不超过 31 天的日期范围。");
      await jsonRequest("/api/collection", jsonBody("POST", {
        action: name, kind, runId, profileIds: scope.map((profile) => profile.profile_id), ...(kind === "reception" ? period : {}),
      }));
      if (name === "collect" || name === "retry") { setSelectedRun(null); setHistoryPage(1); }
      notify(name === "cancel" ? "任务已取消，成功检查点已保留" : name === "retry" ? "已加入队列，仅重试未完成部分" : "采集任务已加入队列");
      await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "操作失败"); }
    finally { setBusy(""); }
  }
  function openShops() {
    setDraftShops(scope.map((profile) => profile.profile_id));
    setShopQuery("");
    setShopsOpen(true);
  }
  function confirmShops() {
    const ids = available.filter((profile) => draftShops.includes(profile.profile_id)).map((profile) => profile.profile_id);
    if (!ids.length) return;
    setSelected(ids.length === available.length ? [] : ids);
    setShopsOpen(false);
  }
  function showRun(id: string) {
    setSelectedRun(id);
    taskPanel.current?.scrollIntoView({ block: "start" });
  }

  return (
    <>
      <Topbar title={`${label}采集`} crumb={`运营 / ${label}采集`} actions={
        <>
          <Link className="btn btn-ghost" href={analysisPath} aria-label={`查看${label}分析`}><Icon name="chart" size={16} /><span>查看分析</span></Link>
          <Button icon="refresh" disabled={refreshing} onClick={() => void refresh()}>{refreshing ? "刷新中…" : "刷新状态"}</Button>
          <Button variant="primary" icon="play" disabled={!canCollect} onClick={() => void action("collect")}>{current ? "任务进行中" : "立即采集"}</Button>
        </>
      } />
      <div className="content">
        {error ? <ErrorState message={error} onRetry={() => void refresh()} /> : null}
        <div className="kpi-grid">
          <KpiCard label="本批已采店铺" value={focus ? `${completedShops} / ${byShop.size}` : "—"} hint={focus ? `${done} / ${items.length} 项完成 · ${byShop.size} 家店铺` : "开始采集后展示本批进度"} />
          <KpiCard label="入库指标" value={focus ? focus.collected_count : "—"} hint={focus ? `任务 ${formatDateTime(focus.created_at)}` : "等待首次采集"} />
          <KpiCard label="待人工处理" value={focus ? humanCount : "—"} hint="登录失效或需要验证的店铺" tone={humanCount ? "warning" : "muted"} />
          <KpiCard label="失败店铺" value={focus ? failedCount : "—"} hint="接口异常或数据尚未更新" tone={failedCount ? "danger" : "muted"} />
        </div>
        <div className="grid-collection">
          <div className="stack">
            <div ref={taskPanel} className={styles.taskAnchor}>
              <Panel title={focus && active(focus.status) ? "进行中的任务" : selectedRun ? "任务详情" : "最近一次任务"}
                subtitle={focus ? `${focus.start_date === "latest" ? "平台最新快照" : `${focus.start_date} ~ ${focus.end_date}`} · ${focus.trigger_type === "scheduled" ? "定时" : "手动"} · ${formatDateTime(focus.created_at)}` : "采集进度与逐店结果会显示在这里"}
                action={focus ? <Chip tone={tone(focus.status)}>{METRIC_STATE_NAMES[focus.status] || focus.status}</Chip> : undefined}>
                {loading ? <Skeleton rows={4} /> : focus ? (
                  <>
                    <div className="progress-meta"><span>{done} / {items.length} 项完成 · {byShop.size} 家店铺</span><span>{progress}%</span></div>
                    <div className={`progress ${styles.progress}`} role="progressbar" aria-label="采集进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><b style={{ width: `${progress}%` }} /></div>
                    <div className={styles.runItems}>
                      {items.map((item) => (
                        <div className={styles.runItem} key={`${item.profile_id}-${item.requested_date}`}>
                          <div className={styles.itemIdentity}><strong>{item.shop_name || item.profile_name}</strong>
                            <span>{METRIC_PLATFORM_NAMES[item.platform]} · {item.requested_date === "latest" ? "最新快照" : `请求 ${item.requested_date}`}{item.report_date ? ` · 数据日 ${item.report_date}` : ""}</span>
                          </div>
                          <Chip tone={tone(item.status)}>{METRIC_STATE_NAMES[item.status] || item.status}</Chip>
                          <span className={styles.itemCount}>{item.record_count} 项</span>
                          {item.source_metric || item.message || item.error_code ? <p className={styles.itemMessage}>{[item.source_metric, item.message, item.error_code].filter(Boolean).join(" · ")}</p> : null}
                        </div>
                      ))}
                    </div>
                    {focus.message ? <p className={styles.runMessage}>{focus.message}</p> : null}
                    <div className={styles.taskFooter}>
                      <span className="meta">成功检查点会保留，重试只处理未完成部分。</span>
                      {active(focus.status) ? <Button size="sm" disabled={Boolean(busy)} onClick={() => void action("cancel", focus.id)}>取消任务</Button> : ["failed", "partial", "needs_human", "cancelled"].includes(focus.status) ? <Button size="sm" disabled={Boolean(busy) || Boolean(current)} onClick={() => void action("retry", focus.id)}>重试未完成</Button> : null}
                    </div>
                  </>
                ) : <EmptyState title="当前没有采集任务" description="选择平台、店铺和采集范围，开始第一次采集。" compact action={<Button variant="primary" disabled={!canCollect} onClick={() => void action("collect")}>开始采集</Button>} />}
              </Panel>
            </div>
            <Panel title="最近采集任务" subtitle="最近 20 次 · 每 5 秒自动更新" action={<Link className="link" href={analysisPath}>查看{label}分析</Link>}>
              {runs.length ? <>
                <div className={styles.historyList}>
                  {history.map((run) => {
                    const good = run.items.filter((item) => complete(item.status)).length;
                    return <div className={styles.historyRow} key={run.id}>
                      <div className={styles.historyIdentity}><strong>{formatDateTime(run.created_at)}</strong><span>{run.start_date === "latest" ? "最新体验分快照" : `${run.start_date} ~ ${run.end_date}`}</span></div>
                      <span className={styles.historyTrigger}>{run.trigger_type === "scheduled" ? "定时" : "手动"}</span>
                      <div className={styles.historyState}><Chip tone={tone(run.status)}>{METRIC_STATE_NAMES[run.status] || run.status}</Chip><span>{good}/{run.items.length} 项 · {run.collected_count} 项入库</span></div>
                      <button type="button" className="link" aria-label={`查看任务 ${formatDateTime(run.created_at)} 详情`} onClick={() => showRun(run.id)}>详情</button>
                    </div>;
                  })}
                </div>
                {runs.length > HISTORY_SIZE ? <Pagination page={activeHistoryPage} pages={historyPages} total={runs.length} pageSize={HISTORY_SIZE} label="次任务" onChange={setHistoryPage} /> : null}
              </> : <EmptyState title="暂无采集任务" description="每次采集的进度和结果会保留在这里。" compact />}
            </Panel>
          </div>
          <div className={`rail ${styles.controls}`}>
            <Panel title="立即采集" subtitle={kind === "reception" ? "北京时间 · 默认采集昨天" : "平台最新快照 · 按业务日期入库"} action={<Link className="link" href={`/collection/settings?tab=${kind}`}>采集设置</Link>}>
              <div className={styles.controlForm}>
                <label className={styles.field}><span>采集平台</span><Select options={platformOptions} value={platform} onChange={(value) => { setPlatform(value); setSelected([]); }} ariaLabel="采集平台" /></label>
                <div className={styles.field}><span>采集店铺</span><button type="button" className={styles.scopeTrigger} onClick={openShops} disabled={!available.length} aria-label="选择采集店铺"><span>{selected.length ? `已选 ${scope.length} 家店铺` : `全部 ${available.length} 家店铺`}</span><Icon name="chevron" size={14} /></button></div>
                {kind === "reception" ? <div className={styles.field}><span>采集日期</span><DateRangeField from={period.from} to={period.to} onChange={(from, to) => setPeriod({ from, to })} max={yesterday} presets={rangePresets(yesterday)} ariaLabel="采集日期范围" /><small className="meta">单次最多 31 天，缺失数据会保留原因。</small></div> : <div className={styles.snapshotNote}><Icon name="calendar" size={18} /><div><strong>采集最新体验分</strong><p>总分与分项按平台返回的业务日期保存。</p></div></div>}
                <Button variant="primary" icon="play" disabled={!canCollect} onClick={() => void action("collect")}>{busy === "collect" ? "创建任务中…" : current ? "采集任务进行中" : "开始采集"}</Button>
                <Link className="btn btn-ghost" href="/collection/settings/shops">店铺配置</Link>
                <p className="meta">{scope.length} 家店铺参与本次采集，已关店自动跳过。</p>
              </div>
            </Panel>
            <Panel title="运行环境" subtitle="采集服务与定时计划">
              <div className="info-list">
                <div className="info-row"><span>采集服务</span><span className={workerOnline ? "is-good" : "is-warning"}>{workerOnline ? `运行中 · 心跳 ${heartbeatAgo ?? 0} 秒前` : "等待采集服务"}</span></div>
                <div className="info-row"><span>已同步店铺</span><span>{eligible.length} 家可采集</span></div>
                <div className="info-row"><span>定时采集</span><span>{setting?.enabled ? `每 ${setting.frequency_days} 天 ${setting.run_at}` : "未启用"}</span></div>
                <div className="info-row"><span>下次执行</span><span>{setting?.enabled ? formatDateTime(setting.next_run_at) : "—"}</span></div>
              </div>
              <Link className={`link ${styles.settingsLink}`} href="/collection/settings/shops">打开店铺配置</Link>
            </Panel>
            <section className="note-card"><h3>采集前确认</h3><p>采集时登录失效会自动登录并继续，遇验证码、滑块等验证时通知人工。保存会话后使用独立 HTTP 采集，请保持客服网页服务运行。</p></section>
          </div>
        </div>
      </div>
      {shopsOpen ? <Modal title="选择采集店铺" width={760} onClose={() => setShopsOpen(false)} footer={<><span className={`meta ${styles.selectionCount}`}>已选择 {draftShops.filter((id) => available.some((profile) => profile.profile_id === id)).length} / {available.length} 家</span><Button onClick={() => setShopsOpen(false)}>取消</Button><Button variant="primary" disabled={!available.some((profile) => draftShops.includes(profile.profile_id))} onClick={confirmShops}>确认选择</Button></>}>
        <div className={styles.shopToolbar}><SearchField value={shopQuery} onChange={(event) => setShopQuery(event.target.value)} placeholder="搜索平台或店铺名称" aria-label="搜索采集店铺" /><button type="button" className="link" onClick={() => setDraftShops([...new Set([...draftShops, ...visibleShops.map((profile) => profile.profile_id)])])}>全选当前结果</button><button type="button" className="link" onClick={() => setDraftShops([])}>清空选择</button></div>
        <div className={styles.shopList}>{visibleShops.length ? visibleShops.map((profile) => <label className={styles.shopOption} key={profile.profile_id}>
          <input type="checkbox" checked={draftShops.includes(profile.profile_id)} onChange={(event) => setDraftShops((old) => event.target.checked ? [...old, profile.profile_id] : old.filter((id) => id !== profile.profile_id))} />
          <span className={styles.shopIdentity}><strong>{profile.shop_name}</strong><span>{METRIC_PLATFORM_NAMES[profile.platform]}{profile.company ? ` · ${profile.company}` : ""}</span></span>
          <Chip tone={tone(profile.auth_state || "unknown")}>{METRIC_STATE_NAMES[profile.auth_state || ""] || "未登录"}</Chip>
        </label>) : <EmptyState title="没有匹配的店铺" description="尝试其他平台或店铺名称。" compact />}</div>
        <p className={styles.scopeHint}>登录状态为最近检查结果；采集时发现失效会自动登录，完成验证后继续任务。</p>
      </Modal> : null}
      <Toast message={toast} />
    </>
  );
}
