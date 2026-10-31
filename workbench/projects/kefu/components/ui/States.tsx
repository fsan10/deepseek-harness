import type { ReactNode } from "react";
import { Icon } from "./Icon";

export function EmptyState({
  title,
  description,
  action,
  compact = false,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={`empty ${compact ? "is-compact" : ""}`.trim()}>
      <strong>{title}</strong>
      {description ? <p>{description}</p> : null}
      {action}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="error-inline" role="alert">
      <Icon name="alert" size={15} />
      <span>{message}</span>
      {onRetry ? (
        <button type="button" onClick={onRetry}>
          重试
        </button>
      ) : null}
    </div>
  );
}

export function Skeleton({ rows = 4, chart = false }: { rows?: number; chart?: boolean }) {
  return (
    <div className="skeleton" aria-hidden="true">
      {chart ? <div className="skeleton-chart" /> : null}
      {Array.from({ length: rows }, (_, index) => (
        <div className="skeleton-line" key={index} style={{ width: `${92 - index * 7}%` }} />
      ))}
    </div>
  );
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="skeleton-table" aria-hidden="true">
      <div className="skeleton-row is-head" />
      {Array.from({ length: rows }, (_, index) => (
        <div className="skeleton-row" key={index} />
      ))}
    </div>
  );
}
