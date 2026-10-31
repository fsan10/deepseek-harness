"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Topbar } from "@/components/shell/Topbar";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { DateRangeField } from "@/components/ui/DatePicker";
import { KpiCard } from "@/components/ui/KpiCard";
import { Pagination } from "@/components/ui/Pagination";
import { Panel } from "@/components/ui/Panel";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { SearchField } from "@/components/ui/SearchField";
import { Select } from "@/components/ui/Select";
import { EmptyState, ErrorState, Skeleton, TableSkeleton } from "@/components/ui/States";
import { Toast, useToast } from "@/components/ui/Toast";
import { jsonRequest, queryString } from "@/lib/client";
import { formatDateTime, rangePresets, todayISO, yesterdayISO } from "@/lib/date";
import { runStatus } from "@/lib/review-status";
import type { ReviewData } from "@/lib/types";
import type { ReviewSort } from "@/lib/review-order";

const EMPTY: ReviewData = {
  rows: [],
  summary: { total: 0, negative: 0, neutral: 0, shops: 0, missingCodes: 0 },
  keywords: [],
  products: [],
  shops: [],
  collectionActivity: null,
  pagination: { page: 1, pageSize: 20, total: 0, pages: 1 },
};

const LEVELS = [
  { value: "", label: "全部" },
  { value: "差评", label: "差评" },
  { value: "中评", label: "中评" },
];

const FIELDS = [
  { value: "", label: "全部字段" },
  { value: "productName", label: "商品名称" },
  { value: "productCode", label: "商品编码" },
  { value: "content", label: "评价内容" },
  { value: "orderId", label: "订单号" },
  { value: "keyword", label: "关键词" },
  { value: "productId", label: "产品 ID" },
];

type Filters = {
  from: string;
  to: string;
  shop: string;
  level: string;
  field: string;
  query: string;
  page: number;
  pageSize: number;
  sort: ReviewSort;
};

export default function ReviewsPage() {
  const [filters, setFilters] = useState<Filters>({
    from: yesterdayISO(),
    to: yesterdayISO(),
    shop: "",
    level: "",
    field: "",
    query: "",
    page: 1,
    pageSize: 20,
    sort: "latest",
  });
  const [draftQuery, setDraftQuery] = useState("");
  const [data, setData] = useState<ReviewData>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState(false);
  const requestId = useRef(0);
  const { toast, notify } = useToast();

  const load = useCallback(async () => {
    const id = ++requestId.current;
    setLoading(true);
    setError("");
    try {
      const result = await jsonRequest<ReviewData>(`/api/reviews?${queryString(filters)}`);
      if (id === requestId.current) setData(result);
    } catch (caught) {
      if (id === requestId.current) setError(caught instanceof Error ? caught.message : "评价数据读取失败");
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    // 筛选条件变化后重新读取评价列表。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    return () => { requestId.current += 1; };
  }, [load]);

  const shopOptions = useMemo(
    () => [{ value: "", label: "全部店铺" }, ...data.shops.map((shop) => ({ value: shop.shop_name, label: shop.shop_name }))],
    [data.shops],
  );

  function patch(next: Partial<Filters>) {
    setFilters((old) => ({ ...old, ...next, page: next.page ?? 1 }));
  }

  async function exportExcel() {
    setExporting(true);
    try {
      const params = queryString({ ...filters, page: undefined });
      const response = await fetch(`/api/reviews/export?${params}`);
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { error?: string } | null;
        throw new Error(body?.error || "导出失败");
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `差评汇总-${filters.from || "全部"}-${filters.to || "全部"}.xlsx`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      notify(`已导出当前筛选的全部 ${data.summary.total} 条评价`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "导出失败");
    } finally {
      setExporting(false);
    }
  }

  const lastRun = data.collectionActivity;
  const total = data.summary.total;

  return (
    <>
      <Topbar
        title="差评分析"
        crumb="分析 / 差评分析"
        actions={
          <>
            <Button icon="refresh" onClick={() => void load()}>
              刷新
            </Button>
            <Button variant="primary" icon="download" onClick={() => void exportExcel()} disabled={exporting || !total}>
              {exporting ? "正在导出…" : "导出 Excel"}
            </Button>
          </>
        }
      />

      <div className="content">
        {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}

        <section className="filter-card is-single">
          <div className="filter-row">
            <Select
              options={shopOptions}
              value={filters.shop}
              onChange={(value) => patch({ shop: value })}
              ariaLabel="筛选店铺"
              className="shop-filter"
            />
            <DateRangeField
              from={filters.from}
              to={filters.to}
              onChange={(from, to) => patch({ from, to })}
              max={todayISO()}
              presets={rangePresets(yesterdayISO())}
              ariaLabel="评价日期范围"
              className="date-filter"
            />
            <SegmentedControl className="is-wide" ariaLabel="评价等级" options={LEVELS}
              value={filters.level} onChange={(value) => patch({ level: value })} />
            <Select
              options={FIELDS}
              value={filters.field}
              onChange={(value) => patch({ field: value })}
              ariaLabel="搜索字段"
              className="w-130"
            />
            <SearchField
              placeholder="搜索商品、订单号…"
              value={draftQuery}
              onChange={(event) => setDraftQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") patch({ query: draftQuery.trim() });
              }}
              style={{ width: 190 }}
            />
            <Button variant="primary" onClick={() => patch({ query: draftQuery.trim() })}>
              搜索
            </Button>
            <button
              type="button"
              className="link"
              onClick={() => {
                setDraftQuery("");
                patch({ from: yesterdayISO(), to: yesterdayISO(), shop: "", level: "", field: "", query: "" });
              }}
            >
              清空筛选
            </button>
          </div>
        </section>

        <div className="summary-bar">
          <div className="summary-left">
            <span className="summary-tag">采集动态</span>
            <span className="summary-text">
              {lastRun
                ? `最近一次采集 ${lastRun.start_date} 至 ${lastRun.end_date} · ${runStatus(lastRun.status).label} · ${formatDateTime(lastRun.created_at)}`
                : "还没有采集记录，请先前往评价采集。"}
            </span>
          </div>
          <Link className="link" href="/reviews/collection">前往评价采集</Link>
        </div>

        {loading ? (
          <>
            <div className="kpi-grid">
              {Array.from({ length: 4 }, (_, index) => (
                <div className="kpi" key={index}>
                  <div className="skeleton-line" style={{ width: "50%" }} />
                  <div className="skeleton-line" style={{ width: "38%", height: 22 }} />
                </div>
              ))}
            </div>
            <div className="grid-rail">
              <Panel title="评价明细">
                <TableSkeleton rows={5} />
              </Panel>
              <div className="rail">
                <Panel title="问题关键词">
                  <Skeleton rows={4} />
                </Panel>
              </div>
            </div>
          </>
        ) : (
          <>
            <div className="kpi-grid">
              <KpiCard label="中差评总数" value={total} hint="当前筛选范围" />
              <KpiCard label="差评" value={data.summary.negative} hint={`占中差评 ${total ? ((data.summary.negative / total) * 100).toFixed(1) : "0.0"}%`} />
              <KpiCard label="中评" value={data.summary.neutral} hint={`占中差评 ${total ? ((data.summary.neutral / total) * 100).toFixed(1) : "0.0"}%`} />
              <KpiCard
                label="涉及店铺"
                value={data.summary.shops}
                hint={data.summary.missingCodes ? `${data.summary.missingCodes} 条商品编码待核对` : "已采集的店铺反馈"}
                tone={data.summary.missingCodes ? "warning" : "muted"}
              />
            </div>

            <div className="grid-rail">
              <Panel
                title="评价明细"
                subtitle={`${total} 条 · 日期与导出均按当前筛选范围`}
                action={<button type="button" className="link" aria-pressed={filters.sort === "negative_first"}
                  onClick={() => patch({ sort: filters.sort === "negative_first" ? "latest" : "negative_first" })}>
                  {filters.sort === "negative_first" ? "差评优先 · 切换为时间排序" : "按差评优先"}
                </button>}
              >
                {data.rows.length ? (
                  <>
                    <div className="table-wrap review-table table-scroll">
                      <table className="table">
                        <thead>
                          <tr>
                            <th>店铺 / 评价时间</th>
                            <th>等级</th>
                            <th>评价详情 / 标签</th>
                            <th>商品 / 产品 ID</th>
                            <th>编码 / 规格</th>
                            <th className="num">订单号</th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.rows.map((row) => (
                            <tr key={row.id}>
                              <td>
                                <strong>{row.shop_name}</strong>
                                <small>{row.reviewed_at}</small>
                                <small>{row.company}</small>
                              </td>
                              <td>
                                <span className={`review-level ${row.review_level === "差评" ? "is-negative" : ""}`.trim()}>{row.review_level}</span>
                              </td>
                              <td className="content-cell">
                                <p>{row.content}</p>
                                <div className="review-tags">
                                  {row.keywords
                                    .split("、")
                                    .filter(Boolean)
                                    .map((keyword) => (
                                      <span key={keyword}>{keyword}</span>
                                    ))}
                                </div>
                              </td>
                              <td>
                                <strong>{row.product_name}</strong>
                                <small>产品 ID：{row.product_id}</small>
                              </td>
                              <td>
                                <strong>{row.product_code || (row.enrichment_status === "not_set" ? "商家未设置" : "待核对")}</strong>
                                <small>{row.sku_name}</small>
                                <small>{row.code_source}</small>
                              </td>
                              <td className="num">
                                <a
                                  className="link mono"
                                  href={`https://fxg.jinritemai.com/ffa/morder/order/detail?id=${encodeURIComponent(row.order_id)}`}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  {row.order_id}
                                </a>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <Pagination
                      page={data.pagination.page}
                      pages={data.pagination.pages}
                      total={data.pagination.total}
                      onChange={(next) => setFilters((old) => ({ ...old, page: next }))}
                      label="条评价"
                      pageSize={data.pagination.pageSize}
                      onPageSizeChange={(pageSize) => patch({ pageSize })}
                    />
                  </>
                ) : (
                  <EmptyState
                    title="当前范围暂无中差评"
                    description="可调整日期与店铺，或前往评价采集获取最新评价。"
                    action={
                      <Link className="link" href="/reviews/collection">
                        前往评价采集
                      </Link>
                    }
                  />
                )}
              </Panel>

              <div className="rail">
                <Panel title="问题关键词" subtitle="当前筛选范围 · 出现次数">
                  <div className="keyword-row">
                    {data.keywords.length ? (
                      data.keywords.map((keyword) => (
                        <button
                          type="button"
                          className="keyword-chip"
                          key={keyword.name}
                          onClick={() => {
                            setDraftQuery(keyword.name);
                            patch({ field: "keyword", query: keyword.name });
                          }}
                        >
                          {keyword.name}
                          <b>{keyword.count}</b>
                        </button>
                      ))
                    ) : (
                      <span className="meta">暂无标签</span>
                    )}
                  </div>
                  <p className="meta" style={{ marginTop: 10, lineHeight: 1.7 }}>
                    按评价文本与平台标签匹配，一条评价可含多个标签。
                  </p>
                </Panel>

                <Panel title="反馈集中的商品" subtitle="当前筛选范围 · TOP 5">
                  {data.products.length ? (
                    <div className="info-list">
                      {data.products.map((product) => (
                        <button
                          type="button"
                          key={product.product_id}
                          className="task-row is-button"
                          onClick={() => {
                            setDraftQuery(product.product_id);
                            patch({ field: "productId", query: product.product_id });
                          }}
                        >
                          <span className="task-name">
                            {product.product_name}
                            <small>
                              {product.count} 条中差评 · 占 {total ? ((product.count / total) * 100).toFixed(1) : "0.0"}%
                            </small>
                          </span>
                          <Icon name="chevron" size={12} className="task-chevron" />
                        </button>
                      ))}
                    </div>
                  ) : (
                    <EmptyState title="暂无集中商品" description="当前范围没有可归集的商品。" compact />
                  )}
                </Panel>
              </div>
            </div>
          </>
        )}
      </div>
      <Toast message={toast} />
    </>
  );
}
