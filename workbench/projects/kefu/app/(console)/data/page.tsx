"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Topbar } from "@/components/shell/Topbar";
import { Button } from "@/components/ui/Button";
import { DateField, DateRangeField } from "@/components/ui/DatePicker";
import { Modal } from "@/components/ui/Modal";
import { Pagination } from "@/components/ui/Pagination";
import { Panel } from "@/components/ui/Panel";
import { SearchField } from "@/components/ui/SearchField";
import { Select } from "@/components/ui/Select";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/States";
import { Toast, useToast } from "@/components/ui/Toast";
import { jsonBody, jsonRequest, queryString } from "@/lib/client";
import { formatDate, todayISO, yesterdayISO } from "@/lib/date";
import { formatValue, type Row } from "@/lib/format";
import type { DataManagementData } from "@/lib/types";

type DataType = "reception" | "scores";
type FormState = { id?: number; shopId: string; metricId: string; value: string; reportDate: string; note: string };

export default function DataPage() {
  const today = todayISO();
  const yesterday = yesterdayISO();
  const [type, setType] = useState<DataType>("reception");
  const [draftQuery, setDraftQuery] = useState("");
  const [query, setQuery] = useState("");
  const [platform, setPlatform] = useState("");
  const [shopId, setShopId] = useState(0);
  const [from, setFrom] = useState(`${yesterday.slice(0, 7)}-01`);
  const [to, setTo] = useState(yesterday);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [data, setData] = useState<DataManagementData>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [modal, setModal] = useState<"new" | "edit" | null>(null);
  const [form, setForm] = useState<FormState>({ shopId: "", metricId: "", value: "", reportDate: today, note: "" });
  const [saving, setSaving] = useState(false);
  const { toast, notify } = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await jsonRequest<DataManagementData>(
        `/api/dashboard?${queryString({
          view: "data-management",
          dataType: type,
          page,
          pageSize,
          query,
          platform,
          shopId: shopId || undefined,
          from,
          to,
        })}`,
      );
      setData(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "数据加载失败");
    } finally {
      setLoading(false);
    }
  }, [type, page, pageSize, query, platform, shopId, from, to]);

  useEffect(() => {
    // 筛选变化后重新取数；loading 状态属于数据请求的一部分。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const shops = useMemo(() => data.filters?.shops ?? [], [data.filters?.shops]);
  const allMetrics = useMemo(() => data.filters?.metrics ?? [], [data.filters?.metrics]);
  const metrics = useMemo(
    () => allMetrics.filter((metric) => (type === "reception" ? metric.code === "reception_count" : metric.code !== "reception_count")),
    [allMetrics, type],
  );
  const platformOptions = useMemo(
    () => [{ value: "", label: "全部平台" }, ...[...new Set(shops.map((shop) => String(shop.platform)))].map((name) => ({ value: name, label: name }))],
    [shops],
  );
  const shopOptions = useMemo(
    () => [
      { value: "", label: "全部店铺" },
      ...shops.filter((shop) => !platform || String(shop.platform) === platform).map((shop) => ({ value: String(shop.id), label: `${shop.platform} · ${shop.name}` })),
    ],
    [shops, platform],
  );
  const formShops = shops.map((shop) => ({ value: String(shop.id), label: `${shop.platform} · ${shop.name}` }));
  const formMetrics = metrics.map((metric) => ({
    value: String(metric.id),
    label: `${metric.category} · ${metric.name}${metric.unit ? `（${metric.unit}）` : ""}`,
  }));

  function switchType(next: DataType) {
    setType(next);
    setPage(1);
    setShopId(0);
    setPlatform("");
  }

  function openNew() {
    setForm({
      shopId: String(shops[0]?.id ?? ""),
      metricId: String(metrics[0]?.id ?? ""),
      value: "",
      reportDate: data.latestDate ?? today,
      note: "",
    });
    setModal("new");
  }

  function openEdit(row: Row) {
    setForm({
      id: Number(row.id),
      shopId: String(row.shopId ?? ""),
      metricId: String(row.metricId ?? ""),
      value: String(row.textValue ?? row.value ?? ""),
      reportDate: String(row.date ?? today),
      note: String(row.note ?? ""),
    });
    setModal("edit");
  }

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const editing = modal === "edit" && form.id;
      await jsonRequest("/api/records", jsonBody(editing ? "PUT" : "POST", {
        id: form.id,
        reportDate: form.reportDate,
        shopId: Number(form.shopId),
        metricId: Number(form.metricId),
        value: form.value,
        note: form.note,
      }));
      setModal(null);
      notify(editing ? "记录已更新" : "记录已新增");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function remove(row: Row) {
    const label = `${row.shop} · ${row.metric} · ${row.date}`;
    if (!window.confirm(`确定删除「${label}」这条记录吗？此操作不可撤销。`)) return;
    setError("");
    try {
      await jsonRequest(`/api/records?id=${row.id}`, { method: "DELETE" });
      notify("记录已删除");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "删除失败");
    }
  }

  function exportRows() {
    const params = queryString({ type, query, platform, shopId: shopId || undefined, from, to });
    window.location.href = `/api/records/export?${params}`;
    notify("正在导出当前筛选的全部记录");
  }

  const pagination = data.pagination ?? { page: 1, pages: 1, total: 0, pageSize: 20 };

  return (
    <>
      <Topbar
        title="数据维护"
        crumb="运营 / 数据维护"
        actions={
          <>
            <Button icon="refresh" onClick={() => void load()}>
              刷新
            </Button>
            <Button variant="primary" icon="download" onClick={exportRows}>导出</Button>
          </>
        }
      />

      <div className="content">
        {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}

        <div className="tabs is-compact">
          <button type="button" className={`tab ${type === "reception" ? "is-active" : ""}`} onClick={() => switchType("reception")}>
            接待量数据
          </button>
          <button type="button" className={`tab ${type === "scores" ? "is-active" : ""}`} onClick={() => switchType("scores")}>
            店铺评分数据
          </button>
        </div>

        <div className="toolbar data-filters">
          <Select
            options={platformOptions}
            value={platform}
            onChange={(value) => {
              setPlatform(value);
              setShopId(0);
              setPage(1);
            }}
            ariaLabel="筛选平台"
            className="w-140"
          />
          <Select
            options={shopOptions}
            value={shopId ? String(shopId) : ""}
            onChange={(value) => {
              setShopId(Number(value));
              setPage(1);
            }}
            ariaLabel="筛选店铺"
            className="shop-filter"
          />
          <DateRangeField
            from={from}
            to={to}
            onChange={(nextFrom, nextTo) => {
              setFrom(nextFrom);
              setTo(nextTo);
              setPage(1);
            }}
            max={today}
            allowClear
            ariaLabel="筛选日期范围"
            className="date-filter"
          />
          <SearchField
            placeholder="搜索店铺、平台或指标"
            value={draftQuery}
            onChange={(event) => setDraftQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                setQuery(draftQuery.trim());
                setPage(1);
              }
            }}
            style={{ width: 220 }}
          />
          <Button
            variant="primary"
            onClick={() => {
              setQuery(draftQuery.trim());
              setPage(1);
            }}
          >
            搜索
          </Button>
          <button
            type="button"
            className="link"
            onClick={() => {
              setDraftQuery("");
              setQuery("");
              setPlatform("");
              setShopId(0);
              setFrom(`${yesterday.slice(0, 7)}-01`);
              setTo(yesterday);
              setPage(1);
            }}
          >
            清空筛选
          </button>
          <span className="toolbar-spacer" />
          <Link className="btn btn-ghost btn-md" href="/data/import">
            批量导入
          </Link>
          <Button variant="primary" icon="plus" onClick={openNew} disabled={!formShops.length || !formMetrics.length}>
            新增记录
          </Button>
        </div>

        <Panel
          title={type === "reception" ? "接待量数据" : "店铺评分数据"}
          subtitle={`共 ${pagination.total.toLocaleString("zh-CN")} 条记录 · 当前筛选 ${from || "全部"} 至 ${to || "全部"}`}
          action={<span className="meta">字段说明见数据接入</span>}
        >
          {loading ? (
            <TableSkeleton rows={6} />
          ) : data.rows?.length ? (
            <>
              <div className="table-wrap table-scroll" style={{ maxHeight: 430 }}>
                <table className="table is-roomy">
                  <thead>
                    <tr>
                      <th>平台</th>
                      <th>店铺名称</th>
                      <th>指标</th>
                      <th className="num">数值</th>
                      <th>日期</th>
                      <th className="num">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data.rows ?? []).map((row) => (
                      <tr key={String(row.id)}>
                        <td><span className="platform-name">{String(row.platform ?? "")}</span></td>
                        <td className="is-strong">{String(row.shop ?? "")}</td>
                        <td className="is-muted">{String(row.metric ?? "")}</td>
                        <td className="num is-strong">{formatValue(row.value ?? row.textValue, String(row.unit ?? ""))}</td>
                        <td className="mono">{formatDate(row.date)}</td>
                        <td>
                          <div className="row-actions">
                            <button type="button" onClick={() => openEdit(row)}>
                              编辑
                            </button>
                            <button type="button" className="is-danger" onClick={() => void remove(row)}>
                              删除
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pagination
                page={pagination.page}
                pages={pagination.pages}
                total={pagination.total}
                onChange={setPage}
                label="条记录"
                pageSize={pagination.pageSize}
                onPageSizeChange={(size) => { setPageSize(size); setPage(1); }}
              />
            </>
          ) : (
            <EmptyState
              title="当前筛选没有记录"
              description="调整平台、店铺或日期范围，或新增一条记录。"
              action={
                <Button variant="primary" size="sm" onClick={openNew} disabled={!formShops.length || !formMetrics.length}>
                  新增记录
                </Button>
              }
              compact
            />
          )}
        </Panel>

        <div className="info-cards">
          <section className="note-card">
            <h3>数据口径</h3>
            <p>
              接待量取店铺当日接待数，来自批量导入或网页录入；同一日期、店铺、指标唯一，重复写入执行更新。
              {"\n"}缺失值保持为空，不按 0 参与均值与环比；日期统一按北京时间计算。
              {"\n"}新增、编辑、删除均走 /api/records，并校验指标单位与数值格式。
            </p>
          </section>
          <section className="note-card">
            <h3>自动化接入</h3>
            <p>
              Python、影刀 RPA 等程序通过 /api/import 写入，单批最多 200 条，使用 Bearer 密钥鉴权。
              {"\n"}同一日期 + 店铺 + 指标的重复记录会更新，不会新增重复行。
              {"\n"}导入失败时整批回滚，并返回具体字段与行号。
            </p>
            <Link className="link" href="/data/import" style={{ display: "inline-block", marginTop: 8 }}>
              查看数据接入说明
            </Link>
          </section>
        </div>
      </div>

      {modal ? (
        <Modal
          title={modal === "new" ? "新增记录" : "编辑记录"}
          onClose={() => setModal(null)}
          footer={
            <>
              <Button onClick={() => setModal(null)}>取消</Button>
              <Button variant="primary" type="submit" form="record-form" disabled={saving}>
                {saving ? "保存中…" : "保存"}
              </Button>
            </>
          }
        >
          <form id="record-form" className="form-grid" onSubmit={(event) => void save(event)}>
            <div className="form-row">
              <label>店铺</label>
              <Select
                options={formShops}
                value={form.shopId}
                onChange={(value) => setForm((old) => ({ ...old, shopId: value }))}
                placeholder="请选择店铺"
                ariaLabel="记录店铺"
                className="grow"
              />
            </div>
            <div className="form-row">
              <label>指标</label>
              <Select
                options={formMetrics}
                value={form.metricId}
                onChange={(value) => setForm((old) => ({ ...old, metricId: value }))}
                placeholder="请选择指标"
                ariaLabel="记录指标"
                className="grow"
              />
            </div>
            <div className="form-row">
              <label htmlFor="record-value">数值</label>
              <input
                id="record-value"
                className="input grow"
                value={form.value}
                onChange={(event) => setForm((old) => ({ ...old, value: event.target.value }))}
                placeholder="例如：128 或 99.5%"
                required
              />
            </div>
            <div className="form-row">
              <label>日期</label>
              <DateField
                value={form.reportDate}
                onChange={(value) => setForm((old) => ({ ...old, reportDate: value }))}
                max={today}
                ariaLabel="记录日期"
                className="grow"
              />
            </div>
            <div className="form-row" style={{ alignItems: "flex-start" }}>
              <label htmlFor="record-note">备注</label>
              <textarea
                id="record-note"
                className="input grow"
                rows={3}
                value={form.note}
                onChange={(event) => setForm((old) => ({ ...old, note: event.target.value }))}
                placeholder="可填写活动、异常或数据来源"
              />
            </div>
          </form>
        </Modal>
      ) : null}

      <Toast message={toast} />
    </>
  );
}
