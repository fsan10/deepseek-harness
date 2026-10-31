"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { Icon } from "./Icon";

export function Modal({
  title,
  children,
  footer,
  onClose,
  width = 520,
}: {
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
  width?: number;
}) {
  const dialog = useRef<HTMLElement>(null);
  const close = useRef(onClose);
  useEffect(() => { close.current = onClose; }, [onClose]);
  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    dialog.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close.current();
      if (event.key === "Tab") {
        const elements = dialog.current?.querySelectorAll<HTMLElement>("button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex='0']");
        const first = elements?.[0];
        const last = elements?.[elements.length - 1];
        if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) {
          event.preventDefault(); last?.focus();
        } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialog.current)) {
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
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section ref={dialog} tabIndex={-1} className="modal" role="dialog" aria-modal="true" aria-label={title} style={{ width }}>
        <header className="modal-head">
          <h2>{title}</h2>
          <button type="button" onClick={onClose} aria-label="关闭">
            <Icon name="close" size={17} />
          </button>
        </header>
        <div className="modal-body">{children}</div>
        {footer ? <footer className="modal-foot">{footer}</footer> : null}
      </section>
    </div>
  );
}
