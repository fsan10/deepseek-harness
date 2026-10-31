"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { LineChart } from "@/components/charts/LineChart";
import { Topbar } from "@/components/shell/Topbar";
import { Button } from "@/components/ui/Button";
import { KpiCard } from "@/components/ui/KpiCard";
import { Pagination } from "@/components/ui/Pagination";
import { Panel } from "@/components/ui/Panel";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import { Toast, useToast } from "@/components/ui/Toast";
import { jsonRequest, queryString } from "@/lib/client";
import { formatDate, shiftDays, todayISO } from "@/lib/date";
import { downloadCsv, formatValue, percentage } from "@/lib/format";
import type { ReceptionData } from "@/lib/types";

const PLATFORM_ORDER = ["抖音", "天猫", "拼多多", "京东", "快手", "小红书", "微信小店"];

function Delta({ value }: { value: number | null }) {
  if (value === null) return <span className="kpi-hint">暂无对比</span>;
  return (
    <span className={`kpi-hint ${value >= 0 ? "is-good" : "is-danger"}`}>
      {value >= 0 ? "↑" : "↓"} {Math.abs(value).toFixed(1)}%
    </span>
  );
}

export default function ReceptionPage() {
  const today = todayISO();
  const from = shiftDays(today, -29);
  const to = today;
  const [platform, setPlatform] = useState("");
  const [data, setData] = useState<ReceptionData>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const { toast, notify } = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const query = queryString({ view: "reception", from, to, platform });
      const result = await jsonRequest<ReceptionData>(`/api/dashboard?${query}`);
      setData(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "数据加载失败");
    } finally {
      setLoading(false);
    }
  }, [from, to, platform]);

  useEffect(() => {
    // 平台与日期变化后重新取数。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const rows = useMemo(() => data.rows ?? [], [data.rows]);
  const summary = data.summary ?? {};
  const platforms = useMemo(
    () =>
      [...new Set((data.filters?.shops ?? []).map((shop) => String(shop.platform)))]
        .filter(Boolean)
        .sort((left, right) => {
          const leftIndex = PLATFORM_ORDER.indexOf(left);
          const rightIndex = PLATFORM_ORDER.indexOf(right);
          return (leftIndex < 0 ? 99 : leftIndex) - (rightIndex < 0 ? 99 : rightIndex) || left.localeCompare(right, "zh-CN");
        }),
    [data.filters?.shops],
  );
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  const activePage = Math.min(page, pages);
  const pageRows = rows.slice((activePage - 1) * pageSize, activePage * pageSize);
  const avg = Number(summary.thirtyDayTotal ?? 0) / Math.max(1, Number(summary.activeDays ?? 0));
  const weekDelta = percentage(summary.weekTotal, summary.previousWeekTotal);

  const platformTotals = useMemo(() => {
    const map = new Map<string, number>();
    for (const row of rows) {
      const key = String(row.platform ?? "");
      if (row.todayValue !== null && row.todayValue !== undefined) map.set(key, (map.get(key) ?? 0) + Number(row.todayValue));
    }
    return platforms.filter((name) => !platform || name === platform)
      .map((label) => ({ label, value: map.get(label) ?? null }));
  }, [rows, platforms, platform]);

  const totalTrend = useMemo(() => {
    const map = new Map<string, number>();
    for (const row of data.trend ?? []) {
      const key = String(row.date ?? "");
      map.set(key, (map.get(key) ?? 0) + Number(row.value ?? 0));
    }
    return [...map.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([date, value]) => ({ date, series: "日接待量", value }));
  }, [data.trend]);

  function exportRows() {
    if (!rows.length) {
      notify("当前筛选没有可导出的数据");
      return;
    }
    downloadCsv(
      `客服数据-接待量-${from}-${to}.csv`,
      rows.map((row) => ({
        平台: String(row.platform ?? ""),
        店铺: String(row.shop ?? ""),
        今日接待: row.todayValue ?? "",
        昨日接待: row.yesterdayValue ?? "",
        "7日均值": row.averageValue ?? "",
        周环比: percentage(row.weekValue, row.previousWeekValue) ?? "",
      })),
    );
    notify("接待量明细已导出");
  }

  const dateLabel = data.latestDate ? formatDate(data.latestDate) : "—";

  return (
    <>
      <Topbar
        title="接待量分析"
        crumb="分析 / 接待量分析"
        actions={
          <>
            {data.latestDate ? <span className="date-tag">数据日 {dateLabel}</span> : null}
            <Button icon="refresh" onClick={() => void load()}>
              刷新
            </Button>
            <Button variant="primary" icon="download" onClick={exportRows}>
              导出
            </Button>
          </>
        }
      />

      <div className="content">
        {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}

        <div className="filter-bar">
          <SegmentedControl className="seg-platforms" ariaLabel="接待量平台" value={platform}
            options={[{ value: "", label: "全部平台" }, ...platforms.map((name) => ({ value: name, label: name }))]}
            onChange={(value) => { setPlatform(value); setPage(1); }} />
        </div>

        {loading ? (
          <>
            <div className="kpi-grid">
              {Array.from({ length: 4 }, (_, index) => (
                <div className="kpi" key={index}>
                  <div className="skeleton-line" style={{ width: "45%" }} />
                  <div className="skeleton-line" style={{ width: "62%", height: 22 }} />
                </div>
              ))}
            </div>
            <div className="grid-main">
              <Panel title="近 30 天接待量趋势">
                <Skeleton chart rows={2} />
              </Panel>
              <Panel title="平台合计">
                <Skeleton rows={6} />
              </Panel>
            </div>
          </>
        ) : (
          <>
            <div className="kpi-grid">
              <KpiCard
                label="今日总接待"
                value={formatValue(summary.todayTotal, "单")}
                hint={<Delta value={percentage(summary.todayTotal, summary.yesterdayTotal)} />}
              />
              <KpiCard
                label="本周累计"
                value={formatValue(summary.weekTotal, "单")}
                hint={
                  <span className={`kpi-hint ${weekDelta !== null && weekDelta >= 0 ? "is-good" : "is-danger"}`}>
                    较前 7 天 {weekDelta === null ? "—" : `${weekDelta >= 0 ? "+" : ""}${weekDelta.toFixed(1)}%`}
                  </span>
                }
              />
              <KpiCard label="本月累计" value={formatValue(summary.monthTotal, "单")} hint={`${Number(today.slice(5, 7))} 月 1 日至今`} />
              <KpiCard label="日均接待" value={formatValue(avg, "单")} hint="近 30 个自然日" />
            </div>

            <div className="grid-reception">
              <Panel
                title="近 30 天接待量趋势"
                subtitle={`${platform || "全部平台"}合计 · 单位：单 · 数据日 ${dateLabel}`}
              >
                <LineChart rows={totalTrend} seriesKey="series" unit="单" height={250} />
              </Panel>
              <Panel title="平台合计" subtitle="当前筛选范围">
                {platformTotals.length ? (
                  <div className="info-list">
                    <div className="info-row" style={{ borderBottom: "1px solid var(--border)" }}>
                      <span>平台</span>
                      <span>接待量</span>
                    </div>
                    {platformTotals.map((item) => (
                      <div className="info-row" key={item.label}>
                        <span>{item.label}</span>
                        <span>{formatValue(item.value, "单")}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyState title="暂无平台数据" description="换一个日期范围再试。" compact />
                )}
              </Panel>
            </div>

            <Panel
              title="接待量明细"
              subtitle={`共 ${rows.length} 家店铺 · 按今日接待量排序`}
              action={<button type="button" className="link" onClick={exportRows}>导出当前筛选</button>}
            >
              {pageRows.length ? (
                <>
                  <div className="table-wrap table-scroll">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>平台</th>
                          <th>店铺名称</th>
                          <th className="num">今日</th>
                          <th className="num">昨日</th>
                          <th className="num">7 日均值</th>
                          <th className="num">周环比</th>
                          <th className="num">占平台</th>
                        </tr>
                      </thead>
                      <tbody>
                        {pageRows.map((row) => {
                          const delta = percentage(row.weekValue, row.previousWeekValue);
                          const platformTotal = platformTotals.find((item) => item.label === String(row.platform))?.value ?? 0;
                          const share = platformTotal ? (Number(row.todayValue ?? 0) / platformTotal) * 100 : 0;
                          return (
                            <tr key={String(row.shopId)}>
                              <td>
                                <span className="platform-pill">{String(row.platform)}</span>
                              </td>
                              <td className="is-strong">{String(row.shop)}</td>
                              <td className="num is-strong">{formatValue(row.todayValue, "单")}</td>
                              <td className="num">{formatValue(row.yesterdayValue, "单")}</td>
                              <td className="num">{formatValue(row.averageValue, "单")}</td>
                              <td className={`num ${delta !== null && delta >= 0 ? "is-good" : "is-danger"}`}>
                                {delta === null ? "—" : `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}%`}
                              </td>
                              <td className="num is-muted">{share ? `${share.toFixed(1)}%` : "—"}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <Pagination page={activePage} pages={pages} total={rows.length} onChange={setPage} label="家店铺" pageSize={pageSize}
                    onPageSizeChange={(size) => { setPageSize(size); setPage(1); }} />
                </>
              ) : (
                <EmptyState title="当前筛选没有接待量数据" description="调整日期范围或平台后再试。" compact />
              )}
            </Panel>
          </>
        )}
      </div>
      <Toast message={toast} />
    </>
  );
}
