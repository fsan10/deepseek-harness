"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Topbar } from "@/components/shell/Topbar";
import { ReviewLogs } from "@/components/ReviewLogs";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { DateRangeField } from "@/components/ui/DatePicker";
import { KpiCard } from "@/components/ui/KpiCard";
import { Icon } from "@/components/ui/Icon";
import { Panel } from "@/components/ui/Panel";
import { Select } from "@/components/ui/Select";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import { Toast, useToast } from "@/components/ui/Toast";
import { jsonBody, jsonRequest } from "@/lib/client";
import { formatDateTime, rangePresets, shiftDays, yesterdayISO } from "@/lib/date";
import { runStatus } from "@/lib/review-status";
import type { ReviewProfile, ReviewRunsResponse, ReviewSettings } from "@/lib/types";

const ACTIVE = new Set(["queued", "running"]);

export default function CollectionPage() {
  const [logsOpen, setLogsOpen] = useState(false);
  const yesterday = yesterdayISO();
  const [profiles, setProfiles] = useState<ReviewProfile[]>([]);
  const [runsData, setRunsData] = useState<ReviewRunsResponse>({ runs: [], worker: null, settings: null });
  const [polledAt, setPolledAt] = useState(0);
  const [from, setFrom] = useState(yesterday);
  const [to, setTo] = useState(yesterday);
  const [profileId, setProfileId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const { toast, notify } = useToast();

  const refreshRuns = useCallback(async () => {
    const result = await jsonRequest<ReviewRunsResponse>("/api/reviews/runs");
    setRunsData(result);
    setPolledAt(Date.now());
  }, []);

  const loadAll = useCallback(async () => {
    setError("");
    try {
      const [profileResult, settingsResult] = await Promise.all([
        jsonRequest<{ profiles: ReviewProfile[] }>("/api/reviews/profiles"),
        jsonRequest<{ settings: ReviewSettings; workerError: string }>("/api/reviews/settings"),
      ]);
      setProfiles(profileResult.profiles);
      if (settingsResult.workerError) setError(settingsResult.workerError);
      const end = yesterdayISO();
      setTo(end);
      setFrom(shiftDays(end, -Math.max(0, Number(settingsResult.settings.lookback_days ?? 1) - 1)));
      await refreshRuns();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "采集数据加载失败");
    } finally {
      setLoading(false);
    }
  }, [refreshRuns]);

  useEffect(() => {
    // 首次进入读取店铺、配置与队列状态；后续由轮询更新。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadAll();
  }, [loadAll]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      refreshRuns().catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [refreshRuns]);

  const activeRun = runsData.runs.find((run) => ACTIVE.has(run.status));
  const focusRun = activeRun ?? runsData.runs[0];
  const workerOnline =
    Boolean(runsData.worker) &&
    polledAt > 0 &&
    polledAt - Date.parse(runsData.worker!.heartbeat_at) < 90_000 &&
    runsData.worker!.message === "运行中";
  const activeShops = focusRun?.shops ?? [];
  const doneCount = activeShops.filter((shop) => ["success", "no_data"].includes(shop.status)).length;
  const collected = activeShops.reduce((sum, shop) => sum + Number(shop.collected_count ?? 0), 0);
  const humanCount = activeShops.filter((shop) => shop.status === "needs_human").length;
  const failedCount = activeShops.filter((shop) => shop.status === "failed").length;
  const progress = activeShops.length ? Math.round((doneCount / activeShops.length) * 100) : 0;
  const heartbeatAgo = runsData.worker ? Math.max(0, Math.round((polledAt - Date.parse(runsData.worker.heartbeat_at)) / 1000)) : null;
  const onlineProfiles = profiles.filter((profile) => !profile.excluded);
  const lastSeen = onlineProfiles
    .map((profile) => profile.last_seen_at)
    .filter(Boolean)
    .sort()
    .slice(-1)[0];
  const profileOptions = [
    { value: "", label: "全部在营抖音店铺" },
    ...onlineProfiles.map((profile) => ({ value: profile.profile_id, label: profile.shop_name || profile.profile_name })),
  ];

  async function action(label: string, run: () => Promise<string>) {
    setBusy(label);
    setError("");
    try {
      const message = await run();
      await refreshRuns();
      notify(message);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "操作失败");
    } finally {
      setBusy("");
    }
  }

  async function startCollect() {
    if (activeRun) {
      notify("已有采集任务在进行中");
      return;
    }
    await action("collect", async () => {
      await jsonRequest("/api/reviews/collect", jsonBody("POST", { from, to, profileIds: profileId ? [profileId] : [] }));
      return "采集任务已加入队列，可在左侧查看店铺进度";
    });
  }

  async function retryRun() {
    if (!focusRun) return;
    await action("retry", async () => {
      await jsonRequest("/api/reviews/collect", jsonBody("POST", { retryId: focusRun.id }));
      return "已安排重试未完成店铺，已成功店铺会保留";
    });
  }

  async function syncProfiles() {
    await action("sync", async () => {
      const result = await jsonRequest<{ profiles: ReviewProfile[] }>("/api/reviews/profiles", jsonBody("POST", {}));
      setProfiles(result.profiles);
      return `已同步 ${result.profiles.filter((profile) => !profile.excluded).length} 家在营店铺`;
    });
  }

  return (
    <>
      <Topbar
        title="评价采集"
        crumb="运营 / 评价采集"
        actions={
          <>
            <Link className="btn btn-ghost" href="/reviews" aria-label="查看差评分析"><Icon name="chart" size={14} /><span>查看分析</span></Link>
            <Button icon="refresh" onClick={() => void refreshRuns().catch((caught) => setError(caught instanceof Error ? caught.message : "刷新失败"))}>
              刷新状态
            </Button>
            <Button variant="primary" icon="play" onClick={() => void startCollect()} disabled={Boolean(busy) || Boolean(activeRun)}>
              {activeRun ? "任务进行中" : "立即采集"}
            </Button>
          </>
        }
      />

      <div className="content">
        {error ? <ErrorState message={error} onRetry={() => void loadAll()} /> : null}

        <div className="kpi-grid">
          <KpiCard
            label="本批已采店铺"
            value={activeShops.length ? `${doneCount} / ${activeShops.length}` : "—"}
            hint={
              activeRun
                ? `采集中 ${activeShops.filter((shop) => shop.status === "running").length} 家 · 已完成 ${doneCount} 家`
                : `已完成 ${doneCount} 家 · 待处理 ${humanCount + failedCount} 家`
            }
          />
          <KpiCard label="新增中差评" value={focusRun ? collected : "—"} hint={focusRun ? `任务 ${formatDateTime(focusRun.created_at)}` : "等待采集"} />
          <KpiCard label="待人工处理" value={humanCount} hint="登录失效或需要验证码" tone={humanCount ? "warning" : "muted"} />
          <KpiCard label="失败店铺" value={failedCount} hint="接口异常或结构变化" tone={failedCount ? "danger" : "muted"} />
        </div>

        <div className="grid-collection">
          <div className="stack">
            <Panel
              title={activeRun ? "进行中的任务" : focusRun ? "最近一次任务" : "采集任务"}
              subtitle={
                focusRun
                  ? `${focusRun.start_date} ~ ${focusRun.end_date} · ${focusRun.trigger_type === "scheduled" ? "定时" : "手动"} · ${formatDateTime(focusRun.created_at)}`
                  : "还没有采集记录"
              }
              action={
                focusRun && !activeRun ? <span className="meta">已结束</span> : focusRun ? <Chip tone="brand">采集中</Chip> : undefined
              }
            >
              {focusRun ? (
                <>
                  <div className="progress-meta">
                    <span>
                      {doneCount} / {activeShops.length} 家已完成
                    </span>
                    <span>{progress}%</span>
                  </div>
                  <div className="progress" style={{ marginTop: 6 }}>
                    <b style={{ width: `${progress}%` }} />
                  </div>
                  <div className="task-list" style={{ marginTop: 8, maxHeight: 208, overflowY: "auto" }}>
                    {activeShops.map((shop) => {
                      const state = runStatus(shop.status);
                      return (
                        <div className="task-row" key={shop.profile_id}>
                          <span className="task-name">{shop.shop_name}</span>
                          <span className={`task-state tone-${state.tone}`}>{state.label}</span>
                          <span className="task-count">{shop.collected_count} 条</span>
                          <span className="task-note">{shop.status === "failed" || shop.status === "needs_human" ? shop.message : ""}</span>
                        </div>
                      );
                    })}
                  </div>
                  <div style={{ marginTop: 10, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                    <span className="meta">已成功店铺会保留，重试仅处理未完成店铺</span>
                    <Button size="sm" onClick={() => void retryRun()} disabled={Boolean(busy) || Boolean(activeRun) || !["failed", "partial", "needs_human"].includes(focusRun.status)}>
                      重试未完成店铺
                    </Button>
                  </div>
                </>
              ) : loading ? (
                <Skeleton rows={4} />
              ) : (
                <EmptyState
                  title="当前没有采集任务"
                  description="选择日期范围后开始采集，进度会在这里实时更新。"
                  action={
                    <Button variant="primary" onClick={() => void startCollect()}>
                      开始采集
                    </Button>
                  }
                  compact
                />
              )}
            </Panel>

            <Panel title="最近采集任务" subtitle="最近 5 次 · 保留每次店铺进度" action={<Link className="link" href="/reviews">查看评价分析</Link>}>
              {runsData.runs.length ? (
                <div className="task-list">
                  {runsData.runs.slice(0, 5).map((run) => {
                    const state = runStatus(run.status);
                    const totalShops = run.shops.length;
                    const doneShops = run.shops.filter((shop) => ["success", "no_data"].includes(shop.status)).length;
                    return (
                      <div className="task-item" key={run.id}>
                        <span className="task-time">
                          {formatDateTime(run.created_at)}
                          <small>
                            {run.start_date} ~ {run.end_date}
                          </small>
                        </span>
                        <span className="task-trigger">{run.trigger_type === "scheduled" ? "定时" : "手动"}</span>
                        <span className={`task-status tone-${state.tone}`}>
                          {state.label}
                          {totalShops ? ` ${doneShops}/${totalShops}` : ""}
                        </span>
                        <span className="task-total">{run.collected_count} 条</span>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <EmptyState title="暂无采集任务" description="首次采集后，这里会保留每次的店铺进度。" compact />
              )}
              <p className="meta" style={{ marginTop: 10 }}>
                失败与待人工任务可在对应 profile 处理登录后重试；已完成店铺不会重复采集。
              </p>
            </Panel>
          </div>

          <div className="rail">
            <Panel title="立即采集" subtitle="北京时间 · 仅抖音在营店铺" action={<Link className="link" href="/collection/settings?tab=reviews">采集设置</Link>}>
              <div className="form-grid">
                <Select options={profileOptions} value={profileId} onChange={setProfileId} ariaLabel="采集店铺范围" />
                <DateRangeField
                  from={from}
                  to={to}
                  onChange={(nextFrom, nextTo) => {
                    setFrom(nextFrom);
                    setTo(nextTo);
                  }}
                  max={yesterday}
                  presets={rangePresets(yesterday)}
                  ariaLabel="采集日期范围"
                  className="dp-centered"
                />
                <p className="meta" style={{ lineHeight: 1.7 }}>
                  采集所选日期 00:00:00 至 23:59:59 的评价；无中差评时记录并进入下一店铺。
                </p>
                <Button variant="primary" onClick={() => void startCollect()} disabled={Boolean(busy) || Boolean(activeRun)}>
                  {busy === "collect" ? "正在创建任务…" : activeRun ? "采集任务进行中" : "开始采集"}
                </Button>
                <Button onClick={() => void syncProfiles()} disabled={Boolean(busy)}>
                  {busy === "sync" ? "同步中…" : "同步 Cloak 店铺"}
                </Button>
                <p className="meta">已同步 {onlineProfiles.length} 家在营店铺 · 已关店自动跳过</p>
              </div>
            </Panel>

            <Panel title="运行环境" subtitle="采集服务与依赖状态">
              <div className="info-list">
                <div className="info-row">
                  <span>采集服务</span>
                  <span className={workerOnline ? "is-good" : "is-warning"}>
                    {workerOnline ? `运行中 · 心跳 ${heartbeatAgo ?? 0} 秒前` : "等待采集服务"}
                  </span>
                </div>
                <div className="info-row">
                  <span>Cloak 店铺清单</span>
                  <span className={onlineProfiles.length ? "is-good" : "is-warning"}>
                    {onlineProfiles.length ? `已同步 ${onlineProfiles.length} 家` : "等待同步"}
                  </span>
                </div>
                <div className="info-row">
                  <span>业务采集方式</span>
                  <span>独立 HTTP · 无需浏览器</span>
                </div>
                <div className="info-row">
                  <span>最近同步</span>
                  <span>
                    {lastSeen ? `${lastSeen.slice(5, 16).replace("T", " ")} · ${onlineProfiles.length} 家店铺` : "尚未同步"}
                  </span>
                </div>
              </div>
              <Link className="link" href="/collection/settings?tab=reviews" style={{ display: "inline-block", marginTop: 10 }}>
                打开采集设置
              </Link>
              <button type="button" className="link" style={{ display: "block", marginTop: 10 }} onClick={() => setLogsOpen(true)}>查看采集服务日志</button>
            </Panel>

          </div>
        </div>
      </div>
      {logsOpen ? <ReviewLogs kind="service" onClose={() => setLogsOpen(false)} /> : null}
      <Toast message={toast} />
    </>
  );
}
