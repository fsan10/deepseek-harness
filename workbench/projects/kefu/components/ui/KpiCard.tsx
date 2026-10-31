import type { ReactNode } from "react";

export function KpiCard({
  label,
  value,
  hint,
  tone,
  progress,
  className = "",
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "good" | "danger" | "warning" | "muted";
  progress?: number;
  className?: string;
}) {
  return (
    <article className={`kpi ${className}`.trim()}>
      <span className="kpi-label">{label}</span>
      <strong className="kpi-value">{value}</strong>
      {hint ? <small className={`kpi-hint ${tone ? `is-${tone}` : ""}`.trim()}>{hint}</small> : null}
      {typeof progress === "number" ? (
        <i className="kpi-track" aria-hidden="true">
          <b style={{ width: `${Math.max(0, Math.min(100, progress))}%` }} />
        </i>
      ) : null}
    </article>
  );
}
