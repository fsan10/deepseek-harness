import type { InputHTMLAttributes } from "react";
import { Icon } from "./Icon";

export function SearchField({
  className = "",
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & { className?: string }) {
  return (
    <label className={`search ${className}`.trim()}>
      <Icon name="search" size={14} />
      <input type="search" {...rest} />
    </label>
  );
}
