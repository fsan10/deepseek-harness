"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Icon } from "./Icon";

export type SelectOption = { value: string; label: string };

export function Select({
  options,
  value,
  onChange,
  placeholder = "请选择",
  ariaLabel,
  disabled = false,
  className = "",
}: {
  options: SelectOption[];
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  ariaLabel?: string;
  disabled?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const id = useId();
  const selectedIndex = useMemo(() => options.findIndex((option) => option.value === value), [options, value]);
  const selected = selectedIndex >= 0 ? options[selectedIndex] : undefined;

  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open, selectedIndex]);

  useEffect(() => {
    if (!open) return;
    const node = list.current?.querySelector<HTMLElement>(`[data-index="${active}"]`);
    node?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  function choose(next: string) {
    onChange(next);
    setOpen(false);
  }

  function toggle() {
    if (!open) setActive(Math.max(0, selectedIndex));
    setOpen(!open);
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLElement>) {
    if (disabled) return;
    if (!open && (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      setActive(Math.max(0, selectedIndex));
      setOpen(true);
      return;
    }
    if (!open) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((index) => Math.min(options.length - 1, index + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => Math.max(0, index - 1));
    } else if (event.key === "Home") {
      event.preventDefault();
      setActive(0);
    } else if (event.key === "End") {
      event.preventDefault();
      setActive(options.length - 1);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (options[active]) choose(options[active].value);
    } else if (event.key === "Escape" || event.key === "Tab") {
      setOpen(false);
    }
  }

  return (
    <div ref={root} className={`select ${open ? "is-open" : ""} ${disabled ? "is-disabled" : ""} ${className}`.trim()}>
      <button
        type="button"
        className="select-trigger"
        role="combobox"
        aria-label={ariaLabel}
        aria-controls={id}
        aria-expanded={open}
        aria-haspopup="listbox"
        disabled={disabled}
        onClick={toggle}
        onKeyDown={onKeyDown}
      >
        <span className={`select-value ${selected ? "" : "is-placeholder"}`.trim()}>
          {selected?.label ?? placeholder}
        </span>
        <Icon name="chevron" size={13} className="select-caret" />
      </button>
      {open ? (
        <div
          ref={list}
          id={id}
          className="select-menu"
          role="listbox"
          tabIndex={-1}
          onKeyDown={onKeyDown}
          aria-activedescendant={`${id}-${active}`}
        >
          {options.map((option, index) => (
            <button
              key={option.value}
              id={`${id}-${index}`}
              data-index={index}
              type="button"
              role="option"
              aria-selected={option.value === value}
              className={`select-option ${option.value === value ? "is-selected" : ""} ${index === active ? "is-active" : ""}`.trim()}
              onPointerEnter={() => setActive(index)}
              onClick={() => choose(option.value)}
            >
              <span>{option.label}</span>
              {option.value === value ? <Icon name="check" size={13} /> : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
