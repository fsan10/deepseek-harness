import type { Metadata } from "next";
import { headers } from "next/headers";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host") ?? "localhost";
  const protocol = requestHeaders.get("x-forwarded-proto") ?? (host.includes("localhost") ? "http" : "https");
  const base = new URL(`${protocol}://${host}`);
  const image = new URL("/og.png", base).toString();
  return {
    metadataBase: base,
    title: "客服数据台｜每日经营报表",
    description: "客服部接待量、店铺体验与竞品数据的一站式日报系统。",
    icons: { icon: "/favicon.svg" },
    openGraph: {
      title: "客服数据台",
      description: "每日经营报表 · 一眼看清接待量与店铺体验",
      type: "website",
      images: [{ url: image, width: 1792, height: 936, alt: "客服数据台每日经营报表" }],
    },
    twitter: {
      card: "summary_large_image",
      title: "客服数据台",
      description: "每日经营报表 · 一眼看清接待量与店铺体验",
      images: [image],
    },
  };
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
