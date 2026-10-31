"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import styles from "./Collection.module.css";

export type ScopeChoice = "keep" | "on" | "off";
export type BatchScope = { reviews: ScopeChoice; reception: ScopeChoice; score: ScopeChoice };

const ROWS = [
  { key: "reviews", label: "评论采集" },
  { key: "reception", label: "接待量采集" },
  { key: "score", label: "店铺体验分采集" },
] as const;

export function BatchScopeDialog({ count, busy, onClose, onApply }: {
  count: number;
  busy: boolean;
  onClose: () => void;
  onApply: (scope: BatchScope) => Promise<boolean>;
}) {
  const [scope, setScope] = useState<BatchScope>({ reviews: "keep", reception: "keep", score: "keep" });
  const untouched = Object.values(scope).every((value) => value === "keep");
  return (
    <Modal
      title={`批量设置采集范围 · 已选 ${count} 家`}
      width={520}
      onClose={() => { if (!busy) onClose(); }}
      footer={<>
        <Button onClick={onClose} disabled={busy}>取消</Button>
        <Button variant="primary" disabled={busy || untouched} onClick={() => void onApply(scope)}>
          {busy ? "保存中…" : `应用到 ${count} 家`}
        </Button>
      </>}
    >
      <p className="meta" style={{ marginBottom: 10 }}>
        只影响已选店铺；平台不支持的类别会跳过，停用或不可用的店铺不会被改动。
      </p>
      {ROWS.map((row) => (
        <div className={styles.triRow} key={row.key}>
          <span>{row.label}</span>
          <div className={styles.triGroup} role="group" aria-label={row.label}>
            {(["keep", "on", "off"] as const).map((choice) => (
              <button key={choice} type="button" data-choice={choice} aria-pressed={scope[row.key] === choice}
                onClick={() => setScope((old) => ({ ...old, [row.key]: choice }))}>
                {choice === "keep" ? "不修改" : choice === "on" ? "开启" : "关闭"}
              </button>
            ))}
          </div>
        </div>
      ))}
    </Modal>
  );
}
