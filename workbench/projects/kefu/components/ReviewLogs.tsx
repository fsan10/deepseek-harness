"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { Modal } from "@/components/ui/Modal";
import { Pagination } from "@/components/ui/Pagination";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import { jsonRequest, queryString } from "@/lib/client";
import { formatDateTime } from "@/lib/date";
import { authStatus, runStatus } from "@/lib/review-status";
import type { ReviewLogsData } from "@/lib/review-logs";

export function ReviewLogs({ kind, onClose }: { kind: "service" | "scheduled"; onClose: () => void }) {
  const [data, setData] = useState<ReviewLogsData | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const requestId = useRef(0);
  const load = useCallback(async () => {
    const id = ++requestId.current;
    setLoading(true);
    setError("");
    try {
      const result = await jsonRequest<ReviewLogsData>(`/api/reviews/logs?${queryString({ kind, page })}`);
      if (id === requestId.current) setData(result);
    } catch (caught) {
      if (id === requestId.current) setError(caught instanceof Error ? caught.message : "日志读取失败");
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [kind, page]);
  useEffect(() => {
    // Opening or paging the viewer only reads saved records.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    return () => { requestId.current += 1; };
  }, [load]);

  return (
    <Modal title={kind === "service" ? "采集服务日志" : "定时采集运行日志"} width={960} onClose={onClose}
      footer={<><Button icon="refresh" onClick={() => void load()} disabled={loading}>刷新日志</Button><Button onClick={onClose}>关闭</Button></>}>
      <div className="review-logs">
        <p className="meta">{kind === "service" ? "当前服务状态、最近登录检查与采集任务记录。" : "仅展示定时采集任务；展开任务可查看各店铺结果。"} 时间按北京时间显示。</p>
        {error ? <ErrorState message={error} onRetry={() => void load()} /> : loading ? <Skeleton rows={5} /> : data ? (
          <>
            {kind === "service" ? (
              <div className="notice" role="status">
                {data.worker ? `最近服务状态：${data.worker.message || "未记录状态"} · 心跳 ${formatDateTime(data.worker.heartbeat_at)}` : "尚无采集服务心跳记录"}
              </div>
            ) : null}
            {data.runs.length ? data.runs.map((run) => {
              const state = runStatus(run.status);
              return (
                <details className="log-run" key={run.id}>
                  <summary><Chip tone={state.tone}>{state.label}</Chip><strong>{formatDateTime(run.created_at)}</strong>
                    <span>{run.trigger_type === "scheduled" ? "定时" : "手动"} · {run.start_date} ~ {run.end_date} · {run.collected_count} 条</span></summary>
                  <div className="log-run-body">
                    <p className="meta">任务 {run.id} · 开始 {formatDateTime(run.started_at)} · 结束 {formatDateTime(run.finished_at)}</p>
                    <p className="log-message">{run.message || "任务未记录额外说明"}</p>
                    {run.shops.length ? <div className="table-wrap table-scroll"><table className="table">
                      <thead><tr><th>店铺</th><th>状态</th><th>条数</th><th>完成时间</th><th>运行说明</th></tr></thead>
                      <tbody>{run.shops.map((shop) => {
                        const status = runStatus(shop.status);
                        return <tr key={shop.profile_id}><td>{shop.shop_name}</td><td className={`tone-${status.tone}`}>{status.label}</td><td>{shop.collected_count}</td><td>{formatDateTime(shop.finished_at)}</td><td className="log-message">{shop.message || "—"}</td></tr>;
                      })}</tbody>
                    </table></div> : <p className="meta">尚无店铺执行记录</p>}
                  </div>
                </details>
              );
            }) : <EmptyState title={kind === "scheduled" ? "暂无定时采集运行日志" : "暂无采集任务记录"} description="任务执行后会显示对应的进度与结果。" compact />}
            {data.pagination.total > 0 ? <Pagination {...data.pagination} label="次任务" onChange={setPage} /> : null}
            {data.auth.length ? <details className="log-run"><summary>最近登录检查 · {data.auth.length} 家店铺</summary>
              <div className="table-wrap table-scroll"><table className="table"><thead><tr><th>店铺</th><th>状态</th><th>检查时间</th><th>说明</th></tr></thead>
                <tbody>{data.auth.map((auth) => <tr key={auth.profile_id}><td>{auth.shop_name}</td><td>{authStatus(auth.state).label}</td><td>{formatDateTime(auth.checked_at)}</td><td className="log-message">{auth.message || "—"}</td></tr>)}</tbody></table></div>
            </details> : null}
          </>
        ) : null}
      </div>
    </Modal>
  );
}
