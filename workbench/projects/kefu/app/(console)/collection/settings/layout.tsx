import { Suspense, type ReactNode } from "react";
import { MetricSettings } from "@/components/MetricSettings";

export default function CollectionSettingsLayout({ children }: { children: ReactNode }) {
  return <>
    <Suspense fallback={<div className="content">正在读取采集设置…</div>}><MetricSettings /></Suspense>
    {children}
  </>;
}
