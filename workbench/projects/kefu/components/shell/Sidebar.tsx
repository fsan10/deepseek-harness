"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Icon, type IconName } from "@/components/ui/Icon";

type Item = { href: string; label: string; icon: IconName; exact?: boolean };

const groups: { label: string; items: Item[] }[] = [
  {
    label: "分析",
    items: [
      { href: "/overview", label: "经营总览", icon: "grid" },
      { href: "/reception", label: "接待量分析", icon: "chart" },
      { href: "/scores", label: "店铺体验分", icon: "star" },
      { href: "/reviews", label: "差评分析", icon: "message" },
    ],
  },
  {
    label: "运营",
    items: [
      { href: "/reviews/collection", label: "评价采集", icon: "play" },
      { href: "/reception/collection", label: "接待量采集", icon: "chart" },
      { href: "/scores/collection", label: "店铺体验分采集", icon: "star" },
      { href: "/data", label: "数据维护", icon: "database" },
    ],
  },
  {
    label: "配置",
    items: [
      { href: "/collection/settings", label: "采集设置", icon: "sliders" },
      { href: "/data/import", label: "数据接入", icon: "plug" },
    ],
  },
];

export function Sidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  function isActive(item: Item) {
    if (["/reception", "/scores"].includes(item.href)) return pathname === item.href;
    if (item.href === "/reviews") return pathname === "/reviews";
    if (item.href === "/data") return pathname === "/data";
    return pathname === item.href || pathname.startsWith(`${item.href}/`);
  }

  return (
    <>
      {!open ? (
        <button className="menu-button" type="button" aria-label="打开导航" onClick={() => setOpen(true)}>
          <Icon name="menu" size={18} />
        </button>
      ) : null}
      <aside className={`sidebar ${open ? "is-open" : ""}`}>
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            <i />
            <i />
            <i />
            <i />
          </span>
          <div className="brand-text">
            <strong>客服数据台</strong>
            <small>局域网 · 内部系统</small>
          </div>
        </div>

        <nav className="nav" aria-label="主导航">
          {groups.map((group) => (
            <div className="nav-group" key={group.label}>
              <span className="nav-label">{group.label}</span>
              {group.items.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`nav-item ${isActive(item) ? "is-active" : ""}`.trim()}
                  onClick={() => setOpen(false)}
                >
                  <Icon name={item.icon} size={17} />
                  <span>{item.label}</span>
                </Link>
              ))}
            </div>
          ))}
        </nav>

        <div className="profile">
          <span className="avatar">管</span>
          <div>
            <strong>本地管理员</strong>
            <small>客服运营</small>
          </div>
        </div>
      </aside>
      {open ? <button className="sidebar-mask" type="button" aria-label="关闭导航" onClick={() => setOpen(false)} /> : null}
    </>
  );
}
