import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Icon, type IconName } from "./Icon";

type Variant = "primary" | "ghost" | "quiet" | "danger";
type Size = "md" | "sm";

export function Button({
  variant = "ghost",
  size = "md",
  icon,
  children,
  className = "",
  ...rest
}: {
  variant?: Variant;
  size?: Size;
  icon?: IconName;
  children?: ReactNode;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={`btn btn-${variant} btn-${size} ${className}`.trim()}
      type={rest.type ?? "button"}
      {...rest}
      aria-label={rest["aria-label"] ?? (typeof children === "string" ? children : undefined)}
    >
      {icon ? <Icon name={icon} size={size === "sm" ? 13 : 15} /> : null}
      {children ? <span>{children}</span> : null}
    </button>
  );
}
