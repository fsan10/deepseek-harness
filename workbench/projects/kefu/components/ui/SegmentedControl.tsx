"use client";

import { useLayoutEffect, useRef } from "react";

type Option = { value: string; label: string };

export function SegmentedControl({ options, value, onChange, ariaLabel, className = "" }: {
  options: readonly Option[];
  value: string;
  onChange: (value: string) => void;
  ariaLabel: string;
  className?: string;
}) {
  const root = useRef<HTMLDivElement>(null);
  const indicator = useRef<HTMLSpanElement>(null);

  useLayoutEffect(() => {
    const container = root.current;
    const marker = indicator.current;
    if (!container || !marker) return;
    const update = () => {
      const selected = container.querySelector<HTMLButtonElement>('button[aria-pressed="true"]');
      if (!selected) { marker.style.opacity = "0"; return; }
      marker.style.transform = `translate(${selected.offsetLeft}px, ${selected.offsetTop}px)`;
      marker.style.width = `${selected.offsetWidth}px`;
      marker.style.height = `${selected.offsetHeight}px`;
      marker.style.opacity = "1";
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(container);
    container.querySelectorAll("button").forEach((button) => observer.observe(button));
    return () => observer.disconnect();
  }, [value, options]);

  return <div ref={root} className={`seg seg-sliding ${className}`} role="group" aria-label={ariaLabel}>
    <span ref={indicator} className="seg-indicator" aria-hidden="true" />
    {options.map((option) => <button key={option.value} type="button" aria-pressed={value === option.value}
      className={value === option.value ? "is-active" : ""} onClick={() => onChange(option.value)}>{option.label}</button>)}
  </div>;
}
