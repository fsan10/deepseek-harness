"use client";

import { useState } from "react";
import { boundedPage, pageItems } from "@/lib/pagination";

function PageJump({ page, pages, onChange }: { page: number; pages: number; onChange: (page: number) => void }) {
  const [draft, setDraft] = useState(String(page));
  function jump() {
    const next = boundedPage(draft, pages, page);
    setDraft(String(next));
    if (next !== page) onChange(next);
  }
  return (
    <label className="pager-info">
      第
      <input aria-label="跳转页码" title="输入页码，按回车或移开焦点跳转" type="text" inputMode="numeric" value={draft}
        onChange={(event) => setDraft(event.target.value)} onBlur={jump}
        onKeyDown={(event) => {
          if (event.key === "Enter") { event.preventDefault(); jump(); }
          if (event.key === "Escape") setDraft(String(page));
        }} />
      / {pages} 页
    </label>
  );
}

export function Pagination({
  page,
  pages,
  total,
  onChange,
  label = "条记录",
  pageSize = 20,
  onPageSizeChange,
}: {
  page: number;
  pages: number;
  total: number;
  onChange: (page: number) => void;
  label?: string;
  pageSize?: number;
  onPageSizeChange?: (pageSize: number) => void;
}) {
  const lastPage = Math.max(1, pages);
  const currentPage = boundedPage(page, lastPage);
  return (
    <nav className="pager" aria-label="分页">
      <span>
        共 {total.toLocaleString("zh-CN")} {label}
      </span>
      <div className="pager-controls">
        {onPageSizeChange ? (
          <select className="pager-size" aria-label="每页条数" value={pageSize} onChange={(event) => onPageSizeChange(Number(event.target.value))}>
            {[...new Set([10, 20, 50, 100, pageSize])].sort((a, b) => a - b).map((size) => <option value={size} key={size}>每页 {size} 条</option>)}
          </select>
        ) : <span className="pager-size">每页 {pageSize} 条</span>}
        <div className="pager-pages">
          {pageItems(currentPage, lastPage).map((item, index) =>
            item === "ellipsis" ? (
              <span className="pager-ellipsis" key={`gap-${index}`}>
                …
              </span>
            ) : (
              <button
                type="button"
                key={item}
                aria-label={`第 ${item} 页`}
                aria-current={item === currentPage ? "page" : undefined}
                className={item === currentPage ? "is-active" : ""}
                onClick={() => onChange(item)}
              >
                {item}
              </button>
            ),
          )}
        </div>
        <PageJump key={`${currentPage}-${lastPage}`} page={currentPage} pages={lastPage} onChange={onChange} />
      </div>
    </nav>
  );
}
