import type { ReactNode } from "react";

export function Topbar({
  title,
  actions,
}: {
  title: string;
  crumb?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="topbar">
      <div className="topbar-title">
        <h1>{title}</h1>
      </div>
      {actions ? <div className="topbar-actions">{actions}</div> : null}
    </header>
  );
}
