"use client";

import { scorePercent } from "@/lib/format";

export function BarList({
  items,
  columns = 1,
  scoreScale = false,
  valueLabel,
}: {
  items: { label: string; value: number | string; hint?: string; tone?: "danger" }[];
  columns?: 1 | 2;
  scoreScale?: boolean;
  valueLabel?: (value: number | string) => string;
}) {
  const numeric = items.map((item) => Number(item.value)).filter((value) => Number.isFinite(value));
  const max = Math.max(1, ...numeric);
  return (
    <div className={`bar-list ${columns === 2 ? "is-two" : ""}`.trim()}>
      {items.map((item, index) => {
        const value = Number(item.value);
        const width = scoreScale ? scorePercent(value) : (value / max) * 100;
        return (
          <div className="bar-item" key={`${item.label}-${index}`}>
            <div className="bar-top">
              <span>{item.label}</span>
              <strong className={item.tone === "danger" ? "is-danger" : ""}>
                {valueLabel ? valueLabel(item.value) : Number.isFinite(value) ? value.toFixed(2) : String(item.value)}
              </strong>
            </div>
            <i className="bar-track">
              <b style={{ width: `${Math.max(2, Math.min(100, width))}%` }} />
            </i>
            {item.hint ? <small>{item.hint}</small> : null}
          </div>
        );
      })}
    </div>
  );
}
