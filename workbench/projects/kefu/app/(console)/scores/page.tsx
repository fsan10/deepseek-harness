"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { LineChart } from "@/components/charts/LineChart";
import { Topbar } from "@/components/shell/Topbar";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { KpiCard } from "@/components/ui/KpiCard";
import { Panel } from "@/components/ui/Panel";
import { Select } from "@/components/ui/Select";
import { EmptyState, ErrorState, Skeleton, TableSkeleton } from "@/components/ui/States";
import { Toast, useToast } from "@/components/ui/Toast";
import { jsonRequest, queryString } from "@/lib/client";
import { formatDate } from "@/lib/date";
import { downloadCsv, formatValue, statusOf } from "@/lib/format";
import type { ScoreData } from "@/lib/types";

export default function ScoresPage() {
  const [shopId, setShopId] = useState(0);
  const [data, setData] = useState<ScoreData>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const { toast, notify } = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await jsonRequest<ScoreData>(`/api/dashboard?${queryString({ view: "store-score", shopId: shopId || undefined })}`);
      setData(result);
      if (!shopId && result.selectedShop) setShopId(Number(result.selectedShop));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "数据加载失败");
    } finally {
      setLoading(false);
    }
  }, [shopId]);

  useEffect(() => {
    // 店铺切换后重新读取该店铺的评分与趋势。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const shops = useMemo(() => data.filters?.shops ?? [], [data.filters?.shops]);
  const cards = data.scoreCards ?? [];
  const detail = data.detailValues ?? [];
  const comparison = (data.comparison ?? []).slice(0, 8);
  const selected = data.selectedShopInfo;
  const date = data.latestDate;

  const shopOptions = useMemo(
    () => shops.map((shop) => ({ value: String(shop.id), label: `${shop.platform} · ${shop.name}` })),
    [shops],
  );

  function exportScores() {
    if (!cards.length && !detail.length) {
      notify("当前没有可导出的数据");
      return;
    }
    const rows = [
      ...cards.map((card) => ({
        类型: "评分卡",
        指标: card.label,
        数值: card.value ?? card.textValue ?? "",
        单位: card.unit ?? "",
        数据日: card.date ?? date ?? "",
      })),
      ...detail.map((row) => ({
        类型: String(row.category ?? ""),
        指标: String(row.metric ?? ""),
        数值: row.value ?? row.textValue ?? "",
        单位: String(row.unit ?? ""),
        数据日: String(row.date ?? ""),
      })),
    ];
    downloadCsv(`客服数据-体验分-${selected?.name ?? shopId}-${date ?? "最新"}.csv`, rows);
    notify("体验分数据已导出");
  }

  return (
    <>
      <Topbar
        title="店铺体验分"
        crumb="分析 / 店铺体验分"
        actions={
          <>
            {date ? <span className="date-tag">数据日 {formatDate(date)}</span> : null}
            <Button icon="refresh" onClick={() => void load()}>
              刷新
            </Button>
            <Button variant="primary" icon="download" onClick={exportScores}>
              导出
            </Button>
          </>
        }
      />

      <div className="content">
        {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}

        <div className="store-bar">
          <div className="store-left">
            <span>当前店铺</span>
            <Select
              options={shopOptions}
              value={shopId ? String(shopId) : ""}
              onChange={(value) => setShopId(Number(value))}
              placeholder="请选择店铺"
              ariaLabel="选择店铺"
            />
          </div>
        </div>

        {loading ? (
          <>
            <div className="score-grid">
              {Array.from({ length: 5 }, (_, index) => (
                <div className="kpi" key={index}>
                  <div className="skeleton-line" style={{ width: "55%" }} />
                  <div className="skeleton-line" style={{ width: "45%", height: 22 }} />
                </div>
              ))}
            </div>
            <div className="score-layout">
              <Panel title="其他指标明细">
                <TableSkeleton rows={4} />
              </Panel>
              <Panel title="体验分历史趋势">
                <Skeleton chart rows={2} />
              </Panel>
            </div>
          </>
        ) : (
          <>
            <div className="score-grid">
              {cards.map((card) => {
                const unit = String(card.unit ?? "");
                const value = card.value ?? card.textValue ?? null;
                const risk = unit === "分" && Number(card.value) > 0 && Number(card.value) < 4.7;
                return (
                  <KpiCard
                    key={card.label}
                    label={card.label}
                    value={formatValue(value, unit)}
                    hint={card.date ? `数据日 ${formatDate(card.date)}` : "暂无数据"}
                    tone={risk ? "danger" : "muted"}
                  />
                );
              })}
            </div>

            <div className="score-layout">
              <Panel title="其他指标明细" subtitle="评分外指标 · 最新数据">
                {detail.length ? (
                  <div className="table-wrap metric-table">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>维度</th>
                          <th>指标名称</th>
                          <th className="num">当前值</th>
                          <th className="num">目标值</th>
                          <th className="num">状态</th>
                        </tr>
                      </thead>
                      <tbody>
                        {detail.map((row) => {
                          const status = statusOf(row);
                          return (
                            <tr key={String(row.metricId)}>
                              <td className="is-muted">{String(row.category ?? "")}</td>
                              <td className="is-strong">{String(row.metric ?? "")}</td>
                              <td className="num is-strong">{formatValue(row.value ?? row.textValue, String(row.unit ?? ""))}</td>
                              <td className="num">
                                {row.target === null || row.target === undefined
                                  ? "—"
                                  : `${row.operator ?? ""}${formatValue(row.target, String(row.unit ?? ""))}`}
                              </td>
                              <td className="num">
                                <Chip tone={status.tone}>{status.label}</Chip>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <EmptyState title="该店铺暂无其他指标" description="评分卡之外的指标会显示在这里。" compact />
                )}
              </Panel>

              <Panel title="体验分历史趋势" subtitle="最近 30 个数据日" action={<span className="meta">按数据日</span>}>
                <LineChart rows={data.scoreTrend ?? []} seriesKey="series" unit="分" score height={250} />
              </Panel>
            </div>

            <Panel
              title="各店铺体验分对比"
              subtitle={`全部有评分店铺 · 数据日 ${formatDate(date)}`}
              action={<Link className="link" href="/data">查看完整清单</Link>}
            >
              {comparison.length ? (
                <div className="compare-list">
                  {comparison.map((row) => (
                    <div className="compare-row" key={`${row.shopId}-${row.shop}`}>
                      <span>{String(row.shop)}</span>
                      <strong className={Number(row.value) < 4.7 ? "is-danger" : ""}>{formatValue(row.value)}</strong>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="当前范围没有店铺评分" description="换一家店铺或检查体验分是否已导入。" compact />
              )}
              <p className="meta" style={{ marginTop: 10 }}>
                仅展示有评分的店铺，低于 4.70 的分数标红，完整清单可在数据维护中筛选。
              </p>
            </Panel>
          </>
        )}
      </div>
      <Toast message={toast} />
    </>
  );
}
