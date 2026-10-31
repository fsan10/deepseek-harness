import type { ReactNode } from "react";
import { Sidebar } from "@/components/shell/Sidebar";

export default function ConsoleLayout({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <Sidebar />
      <main className="workspace">{children}</main>
    </div>
  );
}
