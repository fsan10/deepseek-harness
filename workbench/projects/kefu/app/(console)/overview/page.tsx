"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { BarList } from "@/components/charts/BarList";
import { DonutChart } from "@/components/charts/DonutChart";
import { LineChart } from "@/components/charts/LineChart";
import { Topbar } from "@/components/shell/Topbar";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { KpiCard } from "@/components/ui/KpiCard";
import { Panel } from "@/components/ui/Panel";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import { Toast, useToast } from "@/components/ui/Toast";
import { jsonRequest } from "@/lib/client";
import { formatDate } from "@/lib/date";
import { downloadCsv, formatValue, percentage, statusOf, type Row } from "@/lib/format";
import type { OverviewData } from "@/lib/types";

function Delta({ value, suffix = "较上个数据日" }: { value: number | null; suffix?: string }) {
  if (value === null) return <span className="kpi-hint">暂无对比</span>;
  return (
    <span className={`kpi-hint ${value >= 0 ? "is-good" : "is-danger"}`}>
      {value >= 0 ? "↑" : "↓"} {Math.abs(value).toFixed(1)}% · {suffix}
    </span>
  );
}

export default function OverviewPage() {
  const [data, setData] = useState<OverviewData>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const { toast, notify } = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await jsonRequest<OverviewData>("/api/dashboard?view=overview");
      setData(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "数据加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // 首次进入时加载数据；加载状态由请求生命周期驱动。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const date = data.latestDate ?? "";
  const receptionDelta = percentage(data.stats?.receptionTotal, data.stats?.previousTotal);
  const riskCount = Number(data.stats?.abnormalShopCount ?? 0);
  const shops = data.filters?.shops ?? [];
  const platforms = data.platforms ?? [];
  const ranking = (data.ranking ?? []).slice(0, 6);
  const risks = (data.risks ?? []).slice(0, 5);

  const summary = useMemo(() => {
    if (!date) return "当前还没有接待量数据，请先在数据接入中导入或检查数据日期。";
    const total = formatValue(data.stats?.receptionTotal, "单");
    const deltaText = receptionDelta === null ? "" : `，较上个数据日 ${receptionDelta >= 0 ? "+" : ""}${receptionDelta.toFixed(1)}%`;
    const topMetrics = [...new Set(risks.map((row) => String(row.metric ?? "")).filter(Boolean))].slice(0, 2);
    const focus = topMetrics.length ? `，集中在${topMetrics.join("、")}` : "";
    return `整体接待 ${total}${deltaText}；${riskCount} 项指标未达标${focus}`;
  }, [date, data.stats?.receptionTotal, receptionDelta, riskCount, risks]);

  function exportSummary() {
    if (!date) {
      notify("当前没有可导出的数据");
      return;
    }
    const rows: Row[] = [
      { 指标: "数据日", 数值: date },
      { 指标: "今日总接待量", 数值: formatValue(data.stats?.receptionTotal, "单") },
      { 指标: "上个数据日接待量", 数值: formatValue(data.stats?.previousTotal, "单") },
      { 指标: "活跃店铺数", 数值: formatValue(data.stats?.activeShopCount) },
      { 指标: "未达标指标", 数值: formatValue(riskCount) },
      ...platforms.map((row) => ({ 指标: `平台接待量 · ${row.platform}`, 数值: formatValue(row.value, "单") })),
    ];
    downloadCsv(`客服数据-总览-${date}.csv`, rows);
    notify("摘要已导出");
  }

  return (
    <>
      <Topbar
        title="经营总览"
        crumb="分析 / 经营总览"
        actions={
          <>
            {date ? <span className="date-tag">数据日 {formatDate(date)}</span> : null}
            <Button icon="refresh" onClick={() => void load()}>
              刷新
            </Button>
            <Button variant="primary" icon="download" onClick={exportSummary}>
              导出
            </Button>
          </>
        }
      />

      <div className="content">
        {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}

        {loading ? (
          <>
            <div className="summary-bar">
              <div className="skeleton-line" style={{ width: 420 }} />
            </div>
            <div className="kpi-grid">
              {Array.from({ length: 4 }, (_, index) => (
                <div className="kpi" key={index}>
                  <div className="skeleton-line" style={{ width: "45%" }} />
                  <div className="skeleton-line" style={{ width: "60%", height: 22 }} />
                </div>
              ))}
            </div>
            <div className="grid-main">
              <Panel title="近 7 天接待量趋势">
                <Skeleton chart rows={2} />
              </Panel>
              <Panel title="各平台接待占比">
                <Skeleton chart rows={3} />
              </Panel>
            </div>
          </>
        ) : (
          <>
            <div className="summary-bar">
              <div className="summary-left">
                <span className="summary-tag">昨日摘要</span>
                <span className="summary-text">{summary}</span>
              </div>
              <Link className="link" href="/scores">
                查看异常 {riskCount} 项
              </Link>
            </div>

            <div className="kpi-grid">
              <KpiCard
                label="今日总接待量"
                value={formatValue(data.stats?.receptionTotal, "单")}
                hint={<Delta value={receptionDelta} />}
              />
              <KpiCard
                label="店铺体验分最高"
                value={formatValue(ranking[0]?.value)}
                hint={String(ranking[0]?.shop ?? "暂无评分")}
              />
              <KpiCard
                label="活跃店铺数"
                value={formatValue(data.stats?.activeShopCount)}
                hint={`覆盖 ${platforms.length} 个平台 · 共 ${shops.length} 家店铺`}
              />
              <KpiCard
                label="未达标指标"
                value={formatValue(riskCount)}
                hint={riskCount ? "需优先关注服务体验与退款率" : "当前没有异常指标"}
                tone={riskCount > 0 ? "warning" : "good"}
              />
            </div>

            <div className="grid-main">
              <Panel
                title="近 7 天接待量趋势"
                subtitle="按平台拆分 · 单位：单 · 北京时间"
                action={
                  <Link className="link" href="/reception">
                    查看接待量分析
                  </Link>
                }
              >
                <LineChart rows={data.trend ?? []} seriesKey="platform" unit="单" height={238} />
              </Panel>
              <Panel
                title="各平台接待占比"
                subtitle={date ? `数据日 ${formatDate(date)} · 共 ${formatValue(data.stats?.receptionTotal, "单")} 单` : "最新数据日"}
                action={
                  <Link className="link" href="/reception">
                    口径说明
                  </Link>
                }
              >
                <DonutChart items={platforms.map((row) => ({ label: String(row.platform), value: Number(row.value ?? 0) }))} />
              </Panel>
            </div>

            <div className="grid-main">
              <Panel
                title="异常指标"
                subtitle={`指标数据更新至 ${formatDate(data.metricDate ?? date)} · 按偏差排序`}
                action={
                  <Link className="link" href="/scores">
                    查看全部 {riskCount} 项
                  </Link>
                }
                bodyClassName="table-wrap"
              >
                {risks.length ? (
                  <table className="table">
                    <thead>
                      <tr>
                        <th>店铺</th>
                        <th>指标</th>
                        <th className="num">当前 / 目标</th>
                        <th className="num">状态</th>
                      </tr>
                    </thead>
                    <tbody>
                      {risks.map((row, index) => {
                        const status = statusOf(row);
                        return (
                          <tr key={`${row.shop}-${row.metric}-${index}`}>
                            <td className="is-strong">{String(row.shop)}</td>
                            <td>{String(row.metric)}</td>
                            <td className="num">
                              {formatValue(row.value, String(row.unit ?? ""))} / {row.operator}
                              {formatValue(row.target, String(row.unit ?? ""))}
                            </td>
                            <td className="num">
                              <Chip tone={status.tone}>{status.label}</Chip>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                ) : (
                  <EmptyState title="当前没有触发阈值的异常指标" description="目标值设置后，这里会显示未达标的店铺与指标。" compact />
                )}
              </Panel>

              <Panel
                title="店铺体验分排行"
                subtitle="全部有评分店铺 · TOP 6"
                action={
                  <Link className="link" href="/scores">
                    进入体验分
                  </Link>
                }
              >
                {ranking.length ? (
                  <BarList
                    items={ranking.map((row) => ({
                      label: String(row.shop),
                      value: Number(row.value ?? 0),
                      tone: Number(row.value) < 4.7 ? "danger" : undefined,
                    }))}
                    scoreScale
                    valueLabel={(value) => formatValue(value)}
                  />
                ) : (
                  <EmptyState title="暂无店铺评分" description="体验分导入后这里会显示排行。" compact />
                )}
              </Panel>
            </div>
          </>
        )}
      </div>
      <Toast message={toast} />
    </>
  );
}
