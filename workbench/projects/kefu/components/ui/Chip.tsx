import type { ReactNode } from "react";
import type { Tone } from "@/lib/format";

export function Chip({
  tone = "neutral",
  children,
  className = "",
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  return <span className={`chip chip-${tone} ${className}`.trim()}>{children}</span>;
}
