import type { ReactNode } from "react";

export function Panel({
  title,
  subtitle,
  action,
  children,
  className = "",
  bodyClassName = "",
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={`panel ${className}`.trim()}>
      {title ? (
        <header className="panel-head">
          <div className="panel-title">
            <h2>{title}</h2>
            {subtitle ? <p>{subtitle}</p> : null}
          </div>
          {action ? <div className="panel-action">{action}</div> : null}
        </header>
      ) : null}
      <div className={`panel-body ${bodyClassName}`.trim()}>{children}</div>
    </section>
  );
}
