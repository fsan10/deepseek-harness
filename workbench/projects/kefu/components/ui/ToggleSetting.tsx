"use client";

export function ToggleSetting({ label, checked, onChange, description, ariaLabel, disabled = false }: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  description?: string;
  ariaLabel?: string;
  disabled?: boolean;
}) {
  return <div className="setting-row">
    <div><strong>{label}</strong><div className="meta">{description ?? (checked ? "已启用" : "当前未启用")}</div></div>
    <button type="button" className={`switch ${checked ? "is-on" : ""}`} aria-label={ariaLabel || label} aria-pressed={checked} disabled={disabled} onClick={() => onChange(!checked)} />
  </div>;
}
