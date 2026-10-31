"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "./Icon";
import { isValidDay, rangePresets, todayISO, type RangePreset } from "@/lib/date";

const WEEK = ["一", "二", "三", "四", "五", "六", "日"];

function parseDay(value: string): Date {
  return new Date(`${value}T00:00:00Z`);
}
function iso(date: Date): string {
  return date.toISOString().slice(0, 10);
}
function monthStart(date: Date): Date {
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1));
}
function addMonths(date: Date, amount: number): Date {
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + amount, 1));
}
function calendarDays(month: Date): Date[] {
  const first = monthStart(month);
  const offset = (first.getUTCDay() + 6) % 7;
  const start = new Date(first);
  start.setUTCDate(first.getUTCDate() - offset);
  return Array.from({ length: 42 }, (_, index) => {
    const day = new Date(start);
    day.setUTCDate(start.getUTCDate() + index);
    return day;
  });
}

function monthLabel(month: Date): string {
  return `${month.getUTCFullYear()}年 ${month.getUTCMonth() + 1}月`;
}

type CalendarProps = {
  months: Date[];
  from: string;
  to: string;
  hover: string;
  min?: string;
  max?: string;
  focusDay: string;
  onFocusDay: (day: string) => void;
  onSelect: (day: string) => void;
  onHover?: (day: string) => void;
};

function Calendar({ months, from, to, hover, min, max, focusDay, onFocusDay, onSelect, onHover }: CalendarProps) {
  const grid = useRef<HTMLDivElement>(null);
  const previewEnd = hover || to;

  useEffect(() => {
    const node = grid.current?.querySelector<HTMLElement>(`[data-day="${focusDay}"]`);
    if (node && document.activeElement !== node) node.focus({ preventScroll: true });
  }, [focusDay]);

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const current = isValidDay(focusDay) ? parseDay(focusDay) : parseDay(todayISO());
    let next: Date | null = null;
    if (event.key === "ArrowLeft") next = new Date(current.getTime() - 86_400_000);
    else if (event.key === "ArrowRight") next = new Date(current.getTime() + 86_400_000);
    else if (event.key === "ArrowUp") next = new Date(current.getTime() - 7 * 86_400_000);
    else if (event.key === "ArrowDown") next = new Date(current.getTime() + 7 * 86_400_000);
    else if (event.key === "PageUp") next = addMonths(current, -1);
    else if (event.key === "PageDown") next = addMonths(current, 1);
    else if (event.key === "Home") next = new Date(current.getTime() - (((current.getUTCDay() + 6) % 7) * 86_400_000));
    else if (event.key === "End") next = new Date(current.getTime() + ((6 - ((current.getUTCDay() + 6) % 7)) * 86_400_000));
    else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      const target = focusDay;
      if (!(min && target < min) && !(max && target > max)) onSelect(target);
      return;
    } else return;
    event.preventDefault();
    let value = iso(next);
    if (min && value < min) value = min;
    if (max && value > max) value = max;
    onFocusDay(value);
  }

  return (
    <div className="dp-months" ref={grid} onKeyDown={onKeyDown}>
      {months.map((month) => (
        <div className="dp-month" key={monthLabel(month)}>
          <h3>{monthLabel(month)}</h3>
          <div className="dp-week">
            {WEEK.map((label) => (
              <span key={label}>{label}</span>
            ))}
          </div>
          <div className="dp-grid">
            {calendarDays(month).map((day) => {
              const value = iso(day);
              const outside = day.getUTCMonth() !== month.getUTCMonth();
              const disabled = Boolean((min && value < min) || (max && value > max));
              const start = from && (value === from || (previewEnd && value === previewEnd && value < from));
              const end = previewEnd && (value === previewEnd || (from && value === from && previewEnd < from));
              const inRange = Boolean(from && previewEnd && value > (previewEnd < from ? previewEnd : from) && value < (previewEnd > from ? previewEnd : from));
              const edge = Boolean(from && (value === from || value === previewEnd));
              return (
                <button
                  key={value}
                  type="button"
                  data-day={value}
                  tabIndex={value === focusDay ? 0 : -1}
                  disabled={disabled}
                  className={[
                    outside ? "is-outside" : "",
                    inRange ? "is-in-range" : "",
                    edge ? "is-edge" : "",
                    start ? "is-start" : "",
                    end ? "is-end" : "",
                    value === todayISO() ? "is-today" : "",
                  ].filter(Boolean).join(" ")}
                  aria-label={`${day.getUTCFullYear()}年${day.getUTCMonth() + 1}月${day.getUTCDate()}日，星期${WEEK[(day.getUTCDay() + 6) % 7]}`}
                  aria-pressed={value === from || value === to}
                  onClick={() => onSelect(value)}
                  onPointerEnter={() => onHover?.(value)}
                >
                  <span>{day.getUTCDate()}</span>
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function useDismiss(open: boolean, close: () => void) {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) close();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close]);
  return root;
}

export function DateRangeField({
  from,
  to,
  onChange,
  min,
  max,
  presets,
  allowClear = false,
  ariaLabel = "选择日期范围",
  className = "",
}: {
  from: string;
  to: string;
  onChange: (from: string, to: string) => void;
  min?: string;
  max?: string;
  presets?: RangePreset[];
  allowClear?: boolean;
  ariaLabel?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [draftFrom, setDraftFrom] = useState(from);
  const [draftTo, setDraftTo] = useState(to);
  const [choosingEnd, setChoosingEnd] = useState(false);
  const [hover, setHover] = useState("");
  const [focusDay, setFocusDay] = useState(from || max || todayISO());
  const trigger = useRef<HTMLButtonElement>(null);
  const root = useDismiss(open, () => setOpen(false));

  const presetList = useMemo(
    () => presets ?? rangePresets(max ?? todayISO()),
    [presets, max],
  );
  const [cursorMonth, setCursorMonth] = useState(() =>
    monthStart(parseDay(from || max || todayISO())),
  );

  function openPanel() {
    if (open) {
      setOpen(false);
      return;
    }
    const initial = from || max || todayISO();
    const end = to || initial;
    setDraftFrom(initial);
    setDraftTo(end);
    setChoosingEnd(false);
    setHover("");
    setFocusDay(initial);
    setCursorMonth(monthStart(parseDay(initial)));
    setOpen(true);
  }

  function closePanel() {
    setOpen(false);
    window.setTimeout(() => trigger.current?.focus(), 0);
  }

  function selectDay(day: string) {
    if (!choosingEnd) {
      setDraftFrom(day);
      setDraftTo(day);
      setChoosingEnd(true);
      setHover("");
      return;
    }
    const start = day < draftFrom ? day : draftFrom;
    const end = day < draftFrom ? draftFrom : day;
    setDraftFrom(start);
    setDraftTo(end);
    setChoosingEnd(false);
    setHover("");
    onChange(start, end);
    closePanel();
  }

  function applyPreset(preset: RangePreset) {
    setDraftFrom(preset.from);
    setDraftTo(preset.to);
    onChange(preset.from, preset.to);
    closePanel();
  }

  function onTriggerKey(event: React.KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (!open) setOpen(true);
    }
  }

  const hasValue = Boolean(from && to);

  return (
    <div ref={root} className={`dp dp-range ${open ? "is-open" : ""} ${className}`.trim()}>
      <button
        ref={trigger}
        type="button"
        className="dp-trigger"
        aria-label={ariaLabel}
        aria-expanded={open}
        onKeyDown={onTriggerKey}
        onClick={openPanel}
      >
        <Icon name="calendar" size={14} />
        {hasValue ? (
          <span className="dp-value dp-range-value">
            <span className="dp-range-date">{from}</span>
            <em aria-hidden="true">→</em>
            <span className="dp-range-date">{to}</span>
          </span>
        ) : (
          <span className="dp-placeholder">选择日期范围</span>
        )}
        <Icon name="chevron" size={13} className="dp-caret" />
      </button>

      {open ? (
        <section className="dp-pop" role="dialog" aria-label={ariaLabel}>
          <header className="dp-pop-head">
            <button type="button" aria-label="上个月" onClick={() => setCursorMonth((month) => addMonths(month, -1))}>
              <Icon name="chevron" size={15} />
            </button>
            <p>{choosingEnd ? "请选择结束日期" : "选择日期范围"}</p>
            <button type="button" aria-label="下个月" onClick={() => setCursorMonth((month) => addMonths(month, 1))}>
              <Icon name="chevron" size={15} />
            </button>
          </header>

          <Calendar
            months={[cursorMonth, addMonths(cursorMonth, 1)]}
            from={draftFrom}
            to={draftTo}
            hover={choosingEnd ? hover : ""}
            min={min}
            max={max}
            focusDay={focusDay}
            onFocusDay={(day) => {
              setFocusDay(day);
            }}
            onHover={(day) => {
              if (choosingEnd) setHover(day);
            }}
            onSelect={selectDay}
          />

          <footer className="dp-foot">
            <div className="dp-presets">
              {presetList.map((preset) => (
                <button type="button" key={preset.key} onClick={() => applyPreset(preset)}>
                  {preset.label}
                </button>
              ))}
              {allowClear ? (
                <button
                  type="button"
                  className="dp-clear"
                  onClick={() => {
                    onChange("", "");
                    closePanel();
                  }}
                >
                  清空
                </button>
              ) : null}
            </div>
            <span>{draftFrom && draftTo ? `${draftFrom} 至 ${draftTo}` : "尚未选择日期"}</span>
          </footer>
        </section>
      ) : null}
    </div>
  );
}

export function DateField({
  value,
  onChange,
  min,
  max,
  ariaLabel = "选择日期",
  className = "",
}: {
  value: string;
  onChange: (value: string) => void;
  min?: string;
  max?: string;
  ariaLabel?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [focusDay, setFocusDay] = useState(value || max || todayISO());
  const trigger = useRef<HTMLButtonElement>(null);
  const root = useDismiss(open, () => setOpen(false));
  const [cursorMonth, setCursorMonth] = useState(monthStart(parseDay(value || max || todayISO())));

  function toggle() {
    if (open) {
      setOpen(false);
      return;
    }
    const initial = value || max || todayISO();
    setFocusDay(initial);
    setCursorMonth(monthStart(parseDay(initial)));
    setOpen(true);
  }

  function closePanel() {
    setOpen(false);
    window.setTimeout(() => trigger.current?.focus(), 0);
  }

  return (
    <div ref={root} className={`dp dp-single ${open ? "is-open" : ""} ${className}`.trim()}>
      <button
        ref={trigger}
        type="button"
        className="dp-trigger"
        aria-label={ariaLabel}
        aria-expanded={open}
        onClick={toggle}
      >
        <Icon name="calendar" size={14} />
        {value ? <span className="dp-value">{value}</span> : <span className="dp-placeholder">选择日期</span>}
        <Icon name="chevron" size={13} className="dp-caret" />
      </button>
      {open ? (
        <section className="dp-pop is-single" role="dialog" aria-label={ariaLabel}>
          <header className="dp-pop-head">
            <button type="button" aria-label="上个月" onClick={() => setCursorMonth((month) => addMonths(month, -1))}>
              <Icon name="chevron" size={15} />
            </button>
            <p>选择日期</p>
            <button type="button" aria-label="下个月" onClick={() => setCursorMonth((month) => addMonths(month, 1))}>
              <Icon name="chevron" size={15} />
            </button>
          </header>
          <Calendar
            months={[cursorMonth]}
            from={value}
            to=""
            hover=""
            min={min}
            max={max}
            focusDay={focusDay}
            onFocusDay={setFocusDay}
            onSelect={(day) => {
              onChange(day);
              closePanel();
            }}
          />
          <footer className="dp-foot">
            <div className="dp-presets">
              {(!max || todayISO() <= max) && (!min || todayISO() >= min) ? (
                <button
                  type="button"
                  onClick={() => {
                    onChange(todayISO());
                    closePanel();
                  }}
                >
                  今天
                </button>
              ) : null}
            </div>
            <span>{value || "尚未选择日期"}</span>
          </footer>
        </section>
      ) : null}
    </div>
  );
}
