"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Drawer } from "@/components/ui/Drawer";
import { Pagination } from "@/components/ui/Pagination";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { ErrorState, Skeleton } from "@/components/ui/States";
import { jsonRequest, queryString } from "@/lib/client";
import { RUN_TRIGGER_LABEL, type CollectionLogsData, type RunLogData, type ServiceLogData } from "@/lib/collection-meta";
import { RunDetailList, ServiceBlock } from "./LogViews";
import styles from "./Collection.module.css";

export function LogDrawer({ view, trigger = "", runId = "", switchable = false, onClose }: {
  view: "runs" | "service";
  trigger?: string;
  runId?: string;
  switchable?: boolean;
  onClose: () => void;
}) {
  const [current, setCurrent] = useState<"runs" | "service">(view);
  const [data, setData] = useState<CollectionLogsData | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const requestId = useRef(0);

  const load = useCallback(async () => {
    const id = ++requestId.current;
    setLoading(true);
    setError("");
    try {
      const result = await jsonRequest<CollectionLogsData>(`/api/collection/logs?${queryString({
        view: current,
        trigger: current === "runs" ? trigger : "",
        run: current === "runs" ? runId : "",
        page,
      })}`);
      if (id === requestId.current) setData(result);
    } catch (caught) {
      if (id === requestId.current) setError(caught instanceof Error ? caught.message : "日志读取失败");
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [current, trigger, runId, page]);

  useEffect(() => {
    // 打开抽屉只读取已保存的记录，不触发采集。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    return () => { requestId.current += 1; };
  }, [load]);

  const runs = data?.view === "runs" ? (data as RunLogData) : null;
  const service = data?.view === "service" ? (data as ServiceLogData) : null;

  return <Drawer
    width={960}
    title={current === "service" ? "服务日志" : "运行日志"}
    subtitle={current === "service"
      ? "服务心跳、登录状态检查，以及登录失效、检查异常与恢复记录"
      : `全部手动与定时采集任务，含采集范围、店铺结果与失败原因${trigger ? ` · 仅看${RUN_TRIGGER_LABEL[trigger] ?? trigger}` : ""}`}
    onClose={onClose}
    footer={<>
      <Button icon="refresh" disabled={loading} onClick={() => void load()}>刷新</Button>
      <Button onClick={onClose}>关闭</Button>
    </>}
  >
    {switchable ? <div className={styles.logTabs}>
      <SegmentedControl ariaLabel="日志类型" value={current} onChange={(value) => { setCurrent(value as "runs" | "service"); setPage(1); }}
        options={[{ value: "runs", label: "运行日志" }, { value: "service", label: "服务日志" }]} />
    </div> : null}
    {error ? <ErrorState message={error} onRetry={() => void load()} /> : loading ? <Skeleton rows={6} /> : service ? <ServiceBlock data={service} /> : runs ? <>
      <RunDetailList runs={runs.runs} />
      {runs.pagination.total > runs.pagination.pageSize ? <Pagination {...runs.pagination} label="次任务" onChange={setPage} /> : null}
    </> : null}
  </Drawer>;
}
