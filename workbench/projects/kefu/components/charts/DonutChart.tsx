"use client";

import { formatValue } from "@/lib/format";
import { EmptyState } from "@/components/ui/States";

const PALETTE = ["#4F46E5", "#7A5AF8", "#0E9384", "#DC6803", "#667085", "#C11574", "#94A3B8"];

export type DonutItem = { label: string; value: number; color?: string };

export function DonutChart({ items, unit = "单" }: { items: DonutItem[]; unit?: string }) {
  const list = items.filter((item) => Number(item.value) > 0);
  const total = list.reduce((sum, item) => sum + Number(item.value), 0);
  if (!list.length || !total) {
    return <EmptyState title="当前范围暂无结构数据" description="数据导入后这里会显示平台占比。" compact />;
  }

  const radius = 58;
  const circumference = 2 * Math.PI * radius;
  const lengths = list.map((item) => (Number(item.value) / total) * circumference);
  const offsets = lengths.map((_, index) => lengths.slice(0, index).reduce((sum, value) => sum + value, 0));

  return (
    <div className="donut">
      <div className="donut-ring">
        <svg viewBox="0 0 176 176" role="img" aria-label="平台占比环形图">
          {list.map((item, index) => {
            const length = lengths[index];
            const dash = `${Math.max(0, length - 1.5)} ${circumference - Math.max(0, length - 1.5)}`;
            return (
              <circle
                key={item.label}
                cx="88"
                cy="88"
                r={radius}
                fill="none"
                stroke={item.color ?? PALETTE[index % PALETTE.length]}
                strokeWidth="20"
                strokeDasharray={dash}
                strokeDashoffset={-offsets[index]}
                transform="rotate(-90 88 88)"
              />
            );
          })}
        </svg>
        <div className="donut-center">
          <span>总计</span>
          <strong>{formatValue(total, unit)}</strong>
        </div>
      </div>
      <div className="donut-legend">
        {list.map((item, index) => (
          <div key={item.label}>
            <span>
              <i style={{ background: item.color ?? PALETTE[index % PALETTE.length] }} />
              {item.label}
            </span>
            <strong>{((Number(item.value) / total) * 100).toFixed(1)}%</strong>
          </div>
        ))}
      </div>
    </div>
  );
}
