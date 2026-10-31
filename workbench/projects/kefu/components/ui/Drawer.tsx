"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { Icon } from "./Icon";

export function Drawer({
  title,
  subtitle,
  children,
  footer,
  onClose,
  width = 520,
}: {
  title: string;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
  width?: number;
}) {
  const panel = useRef<HTMLElement>(null);
  const close = useRef(onClose);
  useEffect(() => { close.current = onClose; }, [onClose]);
  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close.current();
      if (event.key === "Tab") {
        const elements = panel.current?.querySelectorAll<HTMLElement>("button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex='0']");
        const first = elements?.[0];
        const last = elements?.[elements.length - 1];
        if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) {
          event.preventDefault(); last?.focus();
        } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === panel.current)) {
          event.preventDefault(); first?.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
      previousFocus?.focus();
    };
  }, []);

  return (
    <div
      className="drawer-backdrop"
      onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}
    >
      <section ref={panel} tabIndex={-1} className="drawer" role="dialog" aria-modal="true" aria-label={title} style={{ width }}>
        <header className="drawer-head">
          <div>
            <h2>{title}</h2>
            {subtitle ? <p className="meta">{subtitle}</p> : null}
          </div>
          <button type="button" onClick={onClose} aria-label="关闭">
            <Icon name="close" size={17} />
          </button>
        </header>
        <div className="drawer-body">{children}</div>
        {footer ? <footer className="drawer-foot">{footer}</footer> : null}
      </section>
    </div>
  );
}
