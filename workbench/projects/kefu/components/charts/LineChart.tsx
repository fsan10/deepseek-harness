"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { formatShortDate } from "@/lib/date";
import { formatValue, type Row } from "@/lib/format";
import { EmptyState } from "@/components/ui/States";

const PALETTE = ["#4F46E5", "#0E9384", "#DC6803", "#7A5AF8", "#667085", "#C11574", "#94A3B8"];

export function LineChart({
  rows,
  seriesKey = "series",
  unit = "",
  score = false,
  height = 250,
  colors = PALETTE,
}: {
  rows: Row[];
  seriesKey?: string;
  unit?: string;
  score?: boolean;
  height?: number;
  colors?: string[];
}) {
  const [active, setActive] = useState<number | null>(null);
  const gradientId = useId().replaceAll(":", "");
  const canvas = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(900);
  const hasRows = rows.length > 0;
  useEffect(() => {
    if (!canvas.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(240, entry.contentRect.width)));
    observer.observe(canvas.current);
    return () => observer.disconnect();
  }, [hasRows]);
  const pad = { left: 64, right: 16, top: 14, bottom: 24 };

  const dates = useMemo(() => [...new Set(rows.map((row) => String(row.date ?? "")))].filter(Boolean).sort(), [rows]);
  const series = useMemo(
    () => [...new Set(rows.map((row) => String(row[seriesKey] ?? "总量")))].filter(Boolean),
    [rows, seriesKey],
  );

  if (!rows.length || !dates.length) {
    return <EmptyState title="当前筛选范围暂无趋势数据" description="换一个日期范围或平台再试。" compact />;
  }

  const values = rows.map((row) => Number(row.value)).filter((value) => Number.isFinite(value));
  if (!values.length) return <EmptyState title="当前筛选范围暂无有效趋势数据" compact />;
  const rawMax = Math.max(...values, 1);
  const rawMin = Math.min(...values);
  const scorePadding = Math.max((rawMax - rawMin) * 0.12, rawMax * 0.02, 0.1);
  const max = score ? Math.ceil((rawMax + scorePadding) * 10) / 10 : rawMax * 1.12;
  const min = score ? Math.max(0, Math.floor((rawMin - scorePadding) * 10) / 10) : 0;
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;
  const x = (date: string) => pad.left + Math.max(0, dates.indexOf(date)) * (plotWidth / Math.max(1, dates.length - 1));
  const y = (value: number) => pad.top + (1 - (value - min) / Math.max(0.0001, max - min)) * plotHeight;
  const ticks = Array.from({ length: 5 }, (_, index) => max - (index * (max - min)) / 4);

  const activeDate = active === null ? null : dates[active];
  const activeRows = activeDate ? rows.filter((row) => String(row.date) === activeDate) : [];
  const tooltipLeft = activeDate ? Math.min(86, Math.max(10, (x(activeDate) / width) * 100)) : 50;

  return (
    <div className="chart">
      <div ref={canvas} className="chart-canvas" style={{ height }}>
        <svg
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label="数据趋势折线图"
          onPointerMove={(event) => {
            const bounds = event.currentTarget.getBoundingClientRect();
            const pointer = ((event.clientX - bounds.left) / bounds.width) * width;
            const ratio = (pointer - pad.left) / Math.max(1, plotWidth);
            setActive(Math.max(0, Math.min(dates.length - 1, Math.round(ratio * Math.max(0, dates.length - 1)))));
          }}
          onPointerLeave={() => setActive(null)}
        >
          {series.length === 1 ? (
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={colors[0]} stopOpacity="0.16" />
                <stop offset="100%" stopColor={colors[0]} stopOpacity="0.01" />
              </linearGradient>
            </defs>
          ) : null}

          {ticks.map((tick, index) => {
            const gy = y(tick);
            return (
              <g key={index}>
                <line x1={pad.left} x2={width - pad.right} y1={gy} y2={gy} className="grid-line" />
                <text x={pad.left - 10} y={gy + 3} textAnchor="end" className="axis-text">
                  {score ? tick.toFixed(1) : tick >= 1000 ? Math.round(tick).toLocaleString("zh-CN") : Math.round(tick)}
                </text>
              </g>
            );
          })}

          {series.map((name, seriesIndex) => {
            const points = rows
              .filter((row) => String(row[seriesKey] ?? "总量") === name)
              .sort((left, right) => String(left.date).localeCompare(String(right.date)));
            const path = points
              .map((row, index) => `${index ? "L" : "M"}${x(String(row.date)).toFixed(1)},${y(Number(row.value)).toFixed(1)}`)
              .join(" ");
            const color = colors[seriesIndex % colors.length];
            return (
              <g key={name}>
                {series.length === 1 && points.length > 1 ? (
                  <path
                    d={`${path} L${x(String(points[points.length - 1].date)).toFixed(1)},${y(min).toFixed(1)} L${x(String(points[0].date)).toFixed(1)},${y(min).toFixed(1)} Z`}
                    fill={`url(#${gradientId})`}
                  />
                ) : null}
                <path d={path} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
                {points.map((row) => (
                  <circle
                    key={`${name}-${row.date}`}
                    cx={x(String(row.date))}
                    cy={y(Number(row.value))}
                    r={activeDate === String(row.date) ? 4 : 2.4}
                    fill={color}
                    stroke="#fff"
                    strokeWidth={1.4}
                  />
                ))}
              </g>
            );
          })}

          {activeDate ? (
            <line x1={x(activeDate)} x2={x(activeDate)} y1={pad.top} y2={height - pad.bottom} className="hover-line" />
          ) : null}
        </svg>

        {activeDate ? (
          <div className="chart-tooltip" style={{ left: `${tooltipLeft}%` }}>
            <strong>{activeDate}</strong>
            {series.map((name, index) => {
              const row = activeRows.find((item) => String(item[seriesKey] ?? "总量") === name);
              if (!row) return null;
              return (
                <div key={name}>
                  <span>
                    <i style={{ background: colors[index % colors.length] }} />
                    {name}
                  </span>
                  <b>{formatValue(row.value, unit)}</b>
                </div>
              );
            })}
          </div>
        ) : null}
      </div>

      <div className="chart-axis chart-axis-positioned">
        {dates
          .filter((_, index) => {
            const step = Math.max(1, Math.ceil((dates.length - 1) / Math.max(1, Math.floor(plotWidth / 76))));
            return index === dates.length - 1 || (index % step === 0 && (index === 0 || dates.length - 1 - index >= step * 0.6));
          })
          .map((date) => (
            <span key={date} style={{ left: `${(x(date) / width) * 100}%` }}>{formatShortDate(date)}</span>
          ))}
      </div>

      <div className="chart-legend">
        {series.map((name, index) => (
          <span key={name}>
            <i style={{ background: colors[index % colors.length] }} />
            {name}
          </span>
        ))}
      </div>
    </div>
  );
}
