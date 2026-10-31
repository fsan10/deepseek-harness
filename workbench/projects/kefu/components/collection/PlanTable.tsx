"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { ErrorState } from "@/components/ui/States";
import { jsonBody, jsonRequest, queryString } from "@/lib/client";
import { formatDateTime } from "@/lib/date";
import { type MetricSnapshot, type PlanKind } from "@/lib/metric-types";
import { runStatus } from "@/lib/review-status";
import type { ReviewSettings } from "@/lib/types";
import type { RunLogData, UnifiedRun } from "@/lib/collection-meta";
import styles from "./Collection.module.css";

type PlanForm = { enabled: boolean; frequency_days: number; lookback_days: number; run_at: string };
type PlanItem = (typeof KINDS)[number];
/** 拖拽中渲染用的快照：拖动行的原始位置、尺寸以及各列宽度。 */
type DragView = {
  kind: PlanKind; from: number; target: number; height: number;
  left: number; top: number; width: number; colWidths: number[];
};
/** 一次拖拽的运行时数据，放在 ref 中避免每次指针移动都触发渲染。 */
type DragSession = {
  from: number; target: number; delta: number; started: boolean;
  rows: { top: number; height: number }[];
};
type RowShift = -1 | 0 | 1;

const DEFAULT_FORM: PlanForm = { enabled: false, frequency_days: 1, lookback_days: 1, run_at: "09:00" };
const DEFAULT_ORDER: PlanKind[] = ["score", "reviews", "reception"];
const KINDS: { kind: PlanKind; label: string; platform: string; extra: string; lookback: boolean; lookbackMax: number }[] = [
  { kind: "score", label: "店铺体验分采集", platform: "三平台", extra: "不支持回溯", lookback: false, lookbackMax: 1 },
  { kind: "reviews", label: "评论采集", platform: "仅抖音", extra: "中评与差评", lookback: true, lookbackMax: 365 },
  { kind: "reception", label: "接待量采集", platform: "六平台", extra: "按日汇总", lookback: true, lookbackMax: 31 },
];
/** 拖动起手阈值（像素）：小于该位移视为点击，不进入拖拽。 */
const DRAG_THRESHOLD = 4;
/** 归位动画时长，需与 CSS 中的 .planDragActive 过渡时长一致。 */
const SETTLE_MS = 190;

function sameForm(left: PlanForm, right: PlanForm) {
  return left.enabled === right.enabled && left.frequency_days === right.frequency_days
    && left.lookback_days === right.lookback_days && left.run_at === right.run_at;
}

function clamp(value: string, max: number) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 1;
  return Math.min(max, Math.max(1, Math.trunc(number)));
}

function shortTime(iso: string) {
  const date = new Date(iso);
  if (!Number.isFinite(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(date).replace(/\//g, "-");
}

/** 取出 from 位置的行，插入到 to 位置；结果与原有 moveBefore 语义一致。 */
function reorder(list: PlanKind[], from: number, to: number) {
  const next = list.slice();
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
}

export function PlanTable({ snapshot, onSaved, onDirtyChange, onOpenRuntime }: {
  snapshot: MetricSnapshot | null;
  onSaved: () => void;
  onDirtyChange: (count: number) => void;
  onOpenRuntime: () => void;
}) {
  const [reviews, setReviews] = useState<ReviewSettings | null>(null);
  const [draft, setDraft] = useState<Record<PlanKind, PlanForm> | null>(null);
  const [latest, setLatest] = useState<Partial<Record<PlanKind, UnifiedRun>>>({});
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [orderDraft, setOrderDraft] = useState<PlanKind[] | null>(null);
  const [drag, setDrag] = useState<DragView | null>(null);
  const sessionRef = useRef<DragSession | null>(null);
  const rowRefs = useRef(new Map<PlanKind, HTMLTableRowElement>());
  const layerRef = useRef<HTMLDivElement | null>(null);
  const teardownRef = useRef<(() => void) | null>(null);
  const settleRef = useRef<number | null>(null);
  const savedOrder = snapshot?.plan_order ?? DEFAULT_ORDER;
  const order = orderDraft ?? savedOrder;
  const orderDirty = order.join(",") !== savedOrder.join(",");
  const orderedKinds = order.map((kind) => KINDS.find((item) => item.kind === kind)!);

  const source = useMemo(() => {
    const metric = (kind: "reception" | "score") => snapshot?.settings.find((item) => item.kind === kind);
    const reception = metric("reception");
    const score = metric("score");
    return {
      reviews: reviews
        ? { enabled: Boolean(reviews.enabled), frequency_days: reviews.frequency_days, lookback_days: reviews.lookback_days, run_at: reviews.run_at }
        : DEFAULT_FORM,
      reception: reception
        ? { enabled: Boolean(reception.enabled), frequency_days: reception.frequency_days, lookback_days: reception.lookback_days, run_at: reception.run_at }
        : DEFAULT_FORM,
      score: score
        ? { enabled: Boolean(score.enabled), frequency_days: score.frequency_days, lookback_days: score.lookback_days, run_at: score.run_at }
        : DEFAULT_FORM,
    } satisfies Record<PlanKind, PlanForm>;
  }, [reviews, snapshot]);

  // 草稿只在用户编辑时创建；保存成功后置空，回落到最新快照。
  const current = draft ?? source;

  const load = useCallback(async () => {
    const [settings, logs] = await Promise.all([
      jsonRequest<{ settings: ReviewSettings }>("/api/reviews/settings"),
      jsonRequest<RunLogData>(`/api/collection/logs?${queryString({ view: "runs", page: 1 })}`),
    ]);
    setReviews(settings.settings);
    const next: Partial<Record<PlanKind, UnifiedRun>> = {};
    for (const run of logs.runs) {
      if (!next[run.source]) next[run.source] = run;
    }
    setLatest(next);
  }, []);

  useEffect(() => {
    let alive = true;
    void Promise.resolve()
      .then(load)
      .then(() => { if (alive) setError(""); })
      .catch((caught: unknown) => { if (alive) setError(caught instanceof Error ? caught.message : "读取采集计划失败"); });
    return () => { alive = false; };
  }, [load]);

  const dirty = useMemo(() => draft
    ? KINDS.filter((item) => !sameForm(draft[item.kind], source[item.kind])).map((item) => item.kind)
    : [], [draft, source]);
  const dirtyCount = dirty.length + Number(orderDirty);
  useEffect(() => { onDirtyChange(dirtyCount); }, [dirtyCount, onDirtyChange]);
  useEffect(() => () => onDirtyChange(0), [onDirtyChange]);

  // 拖拽中途卸载时收尾：撤销监听、恢复页面光标与选中状态。
  useEffect(() => () => {
    teardownRef.current?.();
    if (settleRef.current !== null) window.clearTimeout(settleRef.current);
  }, []);

  function patch(kind: PlanKind, value: Partial<PlanForm>) {
    setDraft((old) => {
      const base = old ?? source;
      return { ...base, [kind]: { ...base[kind], ...value } };
    });
  }

  async function save() {
    if (!dirtyCount) return;
    setSaving(true); setError("");
    try {
      for (const kind of dirty) {
        const form = {
          ...current[kind],
          frequency_days: clamp(String(current[kind].frequency_days), 365),
          lookback_days: clamp(String(current[kind].lookback_days), kind === "reception" ? 31 : 365),
        };
        if (kind === "reviews") await jsonRequest("/api/reviews/settings", jsonBody("PUT", form));
        else await jsonRequest("/api/collection", jsonBody("PUT", { kind, ...form }));
      }
      if (orderDirty) await jsonRequest("/api/collection", jsonBody("PUT", { plan_order: order }));
      setDraft(null);
      await load();
      onSaved();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "保存计划失败");
    } finally {
      setSaving(false);
    }
  }

  function moveBefore(from: PlanKind, to: PlanKind) {
    if (saving || from === to) return;
    setOrderDraft(reorder(order, order.indexOf(from), order.indexOf(to)));
  }

  // 浮动层与表格行保持同一套列宽/结构，拖动时整行跟着指针走。
  const attachLayer = useCallback((node: HTMLDivElement | null) => {
    layerRef.current = node;
    const session = sessionRef.current;
    if (node && session) node.style.transform = `translate3d(0, ${session.delta}px, 0)`;
  }, []);

  function beginDrag(event: React.PointerEvent<HTMLButtonElement>, kind: PlanKind) {
    if (saving || event.button !== 0 || sessionRef.current || settleRef.current !== null) return;
    const sourceRow = rowRefs.current.get(kind);
    if (!sourceRow) return;
    const handle = event.currentTarget;
    const box = sourceRow.getBoundingClientRect();
    const base = order.slice();
    const from = base.indexOf(kind);
    const rows = base.map((key) => {
      const rect = rowRefs.current.get(key)?.getBoundingClientRect();
      return { top: rect?.top ?? box.top, height: rect?.height ?? box.height };
    });
    const colWidths = Array.from(sourceRow.cells).map((cell) => cell.getBoundingClientRect().width);
    const session: DragSession = { from, target: from, delta: 0, started: false, rows };
    sessionRef.current = session;

    const startY = event.clientY;
    // 起止留出约半行余量，避免整行被拖到视野外。
    const minDelta = -box.height * (from + 0.6);
    const maxDelta = box.height * (base.length - 1 - from + 0.6);

    const teardown = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onCancel);
      window.removeEventListener("keydown", onKey);
      try {
        if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
      } catch { /* 元素已卸载时忽略 */ }
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
      sessionRef.current = null;
      teardownRef.current = null;
    };

    const settle = (commit: boolean) => {
      if (teardownRef.current !== teardown) return;
      teardown();
      if (!session.started) return;
      const target = commit ? session.target : session.from;
      const layer = layerRef.current;
      if (layer) {
        layer.style.transition = `transform ${SETTLE_MS}ms cubic-bezier(.22,.75,.28,1)`;
        layer.style.transform = `translate3d(0, ${(target - from) * box.height}px, 0)`;
      }
      setDrag((old) => (old && old.target !== target ? { ...old, target } : old));
      // 归位动画结束后再落库顺序，DOM 重排与 transform 复位同帧完成，避免闪烁。
      settleRef.current = window.setTimeout(() => {
        settleRef.current = null;
        if (target !== from) setOrderDraft(reorder(base, from, target));
        setDrag(null);
      }, SETTLE_MS);
    };

    function onMove(move: PointerEvent) {
      if (move.pointerId !== event.pointerId || sessionRef.current !== session) return;
      const delta = Math.min(maxDelta, Math.max(minDelta, move.clientY - startY));
      if (!session.started) {
        if (Math.abs(move.clientY - startY) < DRAG_THRESHOLD) return;
        session.started = true;
        session.delta = delta;
        setDrag({
          kind, from, target: from, height: box.height,
          left: box.left, top: box.top, width: box.width, colWidths,
        });
        document.body.style.userSelect = "none";
        document.body.style.cursor = "grabbing";
        return;
      }
      session.delta = delta;
      if (layerRef.current) layerRef.current.style.transform = `translate3d(0, ${delta}px, 0)`;
      // 拖动行中心越过相邻行上边界即换位：等行高时正好是“超过相邻行一半高度”。
      const center = box.top + delta + box.height / 2;
      let target = 0;
      for (let index = 0; index < rows.length; index += 1) {
        if (rows[index].top <= center) target = index;
      }
      if (target !== session.target) {
        session.target = target;
        setDrag((old) => (old ? { ...old, target } : old));
      }
    }

    function onUp(up: PointerEvent) {
      if (up.pointerId === event.pointerId) settle(true);
    }

    function onCancel(cancel: PointerEvent) {
      if (cancel.pointerId === event.pointerId) settle(false);
    }

    function onKey(key: KeyboardEvent) {
      if (key.key !== "Escape") return;
      key.preventDefault();
      settle(false);
    }

    teardownRef.current = teardown;
    // 捕获指针：拖出窗口再松手也能收到 pointerup，避免浮层卡住。
    try { handle.setPointerCapture(event.pointerId); } catch { /* 不支持时退回全局监听 */ }
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onCancel);
    window.addEventListener("keydown", onKey);
  }

  const counts = useMemo(() => {
    const profiles = snapshot?.profiles ?? [];
    const usable = profiles.filter((profile) => !profile.excluded && !profile.disabled && profile.shop_name);
    return {
      reviews: usable.filter((profile) => profile.review_enabled && profile.collect_reviews).length,
      reception: usable.filter((profile) => profile.reception_enabled && profile.collect_reception).length,
      score: usable.filter((profile) => profile.score_enabled && profile.collect_score).length,
    };
  }, [snapshot]);

  const nextRunOf = useCallback((kind: PlanKind) => {
    const value = kind === "reviews" ? reviews?.next_run_at : snapshot?.settings.find((entry) => entry.kind === kind)?.next_run_at;
    return value ?? null;
  }, [reviews, snapshot]);

  // 接下来 3 次执行：按各计划的下次执行时间与间隔推演，同一时刻合并成一行。
  const upcoming = useMemo(() => {
    const points: { at: number; label: string }[] = [];
    for (const kind of order) {
      const item = KINDS.find((entry) => entry.kind === kind)!;
      const plan = current[item.kind];
      const next = nextRunOf(item.kind);
      if (!plan.enabled || !next) continue;
      const base = Date.parse(next);
      if (!Number.isFinite(base)) continue;
      for (let index = 0; index < 3; index += 1) {
        points.push({ at: base + index * Math.max(1, plan.frequency_days) * 86_400_000, label: item.label });
      }
    }
    const groups = new Map<number, string[]>();
    for (const point of points) {
      groups.set(point.at, [...(groups.get(point.at) ?? []), point.label]);
    }
    const idle = KINDS.filter((item) => !current[item.kind].enabled).map((item) => item.label);
    return {
      idle,
      rows: [...groups.entries()].sort((left, right) => left[0] - right[0]).slice(0, 3)
        .map(([at, labels]) => ({ at, labels })),
    };
  }, [current, nextRunOf, order]);

  const dirtyLabel = [...dirty.map((kind) => KINDS.find((item) => item.kind === kind)?.label), ...(orderDirty ? ["执行顺序"] : [])].join("、");
  const dragItem = drag ? KINDS.find((item) => item.kind === drag.kind) ?? null : null;

  // 拖拽中行的让位方向：拖动行下方的内容整体上移，上方内容整体下移。
  const shiftOf = (index: number): RowShift => {
    if (!drag) return 0;
    if (index > drag.from && index <= drag.target) return -1;
    if (index < drag.from && index >= drag.target) return 1;
    return 0;
  };

  function renderCells(item: PlanItem) {
    const form = current[item.kind];
    const result = latest[item.kind];
    const state = result ? runStatus(result.status) : null;
    const next = nextRunOf(item.kind);
    return <>
      <td>
        <div className={styles.planIdentity}>
          <button type="button" className={styles.planDragHandle} disabled={saving}
            aria-label={`拖动排序：${item.label}`} aria-describedby="plan-order-help" title="拖动排序；也可用上下方向键调整"
            onPointerDown={(event) => beginDrag(event, item.kind)}
            onKeyDown={(event) => {
              if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
              event.preventDefault();
              if (sessionRef.current) return;
              const index = order.indexOf(item.kind);
              const target = order[index + (event.key === "ArrowUp" ? -1 : 1)];
              if (target) moveBefore(item.kind, target);
            }}>⠿</button>
          <div className={styles.planType}>
            <strong>{item.label}</strong>
            <span>{item.platform} · {counts[item.kind]} 家店铺 · {item.extra}</span>
          </div>
        </div>
      </td>
      <td>
        <label className={styles.cellInput}>
          <input className={styles.cellValue} type="number" min={1} max={365} aria-label={`${item.label}间隔天数`}
            value={form.frequency_days} onChange={(event) => patch(item.kind, { frequency_days: Number(event.target.value) })}
            onBlur={(event) => patch(item.kind, { frequency_days: clamp(event.target.value, 365) })} />
          <span>天</span>
        </label>
      </td>
      <td>
        {item.lookback ? <label className={styles.cellInput}>
          <input className={styles.cellValue} type="number" min={1} max={item.lookbackMax} aria-label={`${item.label}回溯天数`}
            value={form.lookback_days} onChange={(event) => patch(item.kind, { lookback_days: Number(event.target.value) })}
            onBlur={(event) => patch(item.kind, { lookback_days: clamp(event.target.value, item.lookbackMax) })} />
          <span>天</span>
        </label> : <span className={styles.planNote}>—</span>}
      </td>
      <td>
        <input className={`input ${styles.cellTime}`} type="time" aria-label={`${item.label}执行时间`}
          value={form.run_at} onChange={(event) => patch(item.kind, { run_at: event.target.value })} />
      </td>
      <td className={styles.runMeta}>{form.enabled ? formatDateTime(next) : "未启用"}</td>
      <td>{state ? <Chip tone={state.tone}>{state.label}</Chip> : <span className={styles.planNote}>—</span>}</td>
      <td>
        <div className={styles.planActions}>
          <button type="button" className="link" onClick={onOpenRuntime}>查看详情</button>
          <button type="button" className={`switch ${form.enabled ? "is-on" : ""}`} role="switch"
            aria-checked={form.enabled} aria-label={`启用${item.label}`}
            onClick={() => patch(item.kind, { enabled: !form.enabled })} />
        </div>
      </td>
    </>;
  }

  return <>
    {error ? <ErrorState message={error} onRetry={() => void load().catch((caught: Error) => setError(caught.message))} /> : null}
    <section className="panel">
      <header className="panel-head">
        <div className="panel-title">
          <h2>三类采集的计划</h2>
          <p id="plan-order-help">拖动左侧手柄调整顺序后保存；任务串行执行，当前任务结束后继续下一项</p>
        </div>
        <div className="panel-action">
          <button type="button" className="link" onClick={onOpenRuntime}>运行日志</button>
        </div>
      </header>
      <div className="panel-body">
        <div className="table-wrap table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>采集类型</th>
                <th style={{ width: 72 }}>间隔</th>
                <th style={{ width: 72 }}>回溯</th>
                <th style={{ width: 88 }}>执行时间</th>
                <th style={{ width: 168 }}>下次执行</th>
                <th style={{ width: 88 }}>最近结果</th>
                <th style={{ width: 132 }}>操作</th>
              </tr>
            </thead>
            <tbody className={drag ? styles.planDragActive : undefined}>
              {orderedKinds.map((item, index) => {
                const shift = shiftOf(index);
                return (
                  <tr key={item.kind}
                    ref={(node) => {
                      if (node) rowRefs.current.set(item.kind, node);
                      else rowRefs.current.delete(item.kind);
                    }}
                    className={drag && drag.kind === item.kind ? styles.planDragSource : undefined}
                    style={shift ? { transform: `translateY(${shift * (drag?.height ?? 0)}px)` } : undefined}>
                    {renderCells(item)}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      {dirtyCount ? (
        <div className={styles.planSaveBar}>
          <span>{dirtyCount} 项未保存：{dirtyLabel}</span>
          <button type="button" className="link" disabled={saving} onClick={() => { setDraft(null); setOrderDraft(null); }}>放弃</button>
          <Button variant="primary" disabled={saving} onClick={() => void save()}>{saving ? "保存中…" : "保存计划"}</Button>
        </div>
      ) : null}
    </section>

    <div className={styles.planBottom}>
      <section className="panel">
        <div className="panel-title"><h2 className={styles.planCardTitle}>接下来 3 次执行</h2></div>
        <div className={styles.planRuns}>
          {upcoming.rows.length ? upcoming.rows.map((row) => (
            <div className={styles.planRunRow} key={row.at}>
              <span>{shortTime(new Date(row.at).toISOString())}</span>
              <span>{row.labels.join(" → ")}{upcoming.idle.length ? `（${upcoming.idle.join("、")}未启用，跳过）` : ""}</span>
            </div>
          )) : <p className="meta">全部计划未启用，不会产生自动执行。</p>}
        </div>
      </section>
      <section className={`panel ${styles.planRulesCard}`}>
        <div className="panel-title"><h2 className={styles.planCardTitle}>规则边界</h2></div>
        <div className={styles.planRules}>
          <p>接待量回溯 1–31 天，评论 1–365 天；体验分使用最新快照。</p>
          <p>到点任务按表格顺序依次执行，当前任务不会被抢占。</p>
          <p>保存计划和顺序不改店铺范围与登录检查间隔。</p>
          <p>未启用的计划不写下次执行时间；立即采集不在此页。</p>
        </div>
      </section>
    </div>

    {drag && dragItem && typeof document !== "undefined" ? createPortal(
      <div ref={attachLayer} className={styles.planDragLayer} inert
        style={{ left: drag.left, top: drag.top, width: drag.width }}>
        <table className={`table ${styles.planDragTable}`}>
          <colgroup>
            {drag.colWidths.map((width, index) => <col key={index} style={{ width }} />)}
          </colgroup>
          <tbody><tr>{renderCells(dragItem)}</tr></tbody>
        </table>
      </div>,
      document.body,
    ) : null}
  </>;
}
