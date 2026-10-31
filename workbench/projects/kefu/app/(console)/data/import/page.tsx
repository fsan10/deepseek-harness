"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Topbar } from "@/components/shell/Topbar";
import { Button } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Panel";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { Toast, useToast } from "@/components/ui/Toast";
import { jsonRequest } from "@/lib/client";
import { formatDateTime } from "@/lib/date";
import { copyText } from "@/lib/clipboard";

type ImportOverview = {
  lastImportAt: string | null;
  lastBatchCount: number;
  lastBatchSuccess: number;
  lastBatchFailed: number;
  sevenDaySuccessRate: number | null;
  source: string;
  batchCount: number;
};

type ImportInfo = {
  name: string;
  version: string;
  endpoint: string;
  method: string;
  authentication: string;
  maxBatchSize: number;
  idempotency: string;
  platformCapabilities: Record<string, string[]>;
  overview?: ImportOverview;
};

const FIELDS = [
  { key: "reportDate", required: "是", desc: "业务日期，格式 YYYY-MM-DD，按北京时间解释", sample: "2026-10-21" },
  { key: "platform", required: "是", desc: "平台名称，需与 reporting-config 中的店铺范围一致", sample: "抖音" },
  { key: "shopName", required: "是", desc: "店铺名，按平台 + 名称精确定位，不做模糊合并", sample: "MOCK咖啡旗舰店" },
  { key: "metricName", required: "是", desc: "指标别名会按平台规范化，例如「我的体验分」→「店铺体验分」", sample: "店铺体验分" },
  { key: "value", required: "是", desc: "数值、百分比或区间文本；百分比统一按小数存储", sample: "4.92 / 3.8% / 3%–5%" },
];

export default function ImportPage() {
  const router = useRouter();
  const [info, setInfo] = useState<ImportInfo | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const endpointText = useRef<HTMLSpanElement>(null);
  const { toast, notify } = useToast();

  useEffect(() => {
    jsonRequest<ImportInfo>("/api/import")
      .then(setInfo)
      .catch((caught) => setError(caught instanceof Error ? caught.message : "接入信息读取失败"))
      .finally(() => setLoading(false));
  }, []);

  async function copyEndpoint() {
    if (!info?.endpoint) return;
    if (await copyText(info.endpoint)) {
      notify("接口地址已复制");
    } else {
      const selection = window.getSelection();
      if (endpointText.current && selection) {
        const range = document.createRange();
        range.selectNodeContents(endpointText.current);
        selection.removeAllRanges(); selection.addRange(range);
      }
      notify("接口地址已选中，请按 Ctrl+C 复制");
    }
  }

  const overview = info?.overview;
  const platforms = info ? Object.entries(info.platformCapabilities) : [];

  return (
    <>
      <Topbar
        title="数据接入"
        crumb="配置 / 数据接入"
        actions={<Button onClick={() => router.push("/data")}>返回数据维护</Button>}
      />

      <div className="content">
        {error ? <ErrorState message={error} /> : null}

        <div className="summary-bar" style={{ minHeight: 64, alignItems: "flex-start", paddingTop: 12, paddingBottom: 12 }}>
          <div className="stack" style={{ gap: 4 }}>
            <span className="summary-tag">外部写入统一走 HTTP API</span>
            <span className="summary-text">Python、影刀 RPA 等程序按批次写入；同日期 + 店铺 + 指标自动更新，不产生重复记录。</span>
          </div>
          <a className="link" href="/api/import/docs" target="_blank" rel="noreferrer">API_IMPORT.md</a>
        </div>

        <div className="info-cards">
          <Panel
            title="API 接入"
            subtitle={info ? `${info.method} /api/import · application/json` : "读取接口信息中…"}
            action={<a className="link" href="#import-fields">查看字段说明</a>}
          >
            {loading ? (
              <EmptyState title="正在读取接口信息" compact />
            ) : info ? (
              <>
                <div className="code-block has-copy">
                  <code>POST&nbsp;&nbsp;<span ref={endpointText}>{info.endpoint}</span>&nbsp;&nbsp;&nbsp;&nbsp;Authorization: Bearer &lt;IMPORT_API_KEY&gt;</code>
                  <button className="code-copy" type="button" aria-label="复制接口地址" title="复制接口地址" onClick={() => void copyEndpoint()}>复制</button>
                </div>
                <div className="info-list" style={{ marginTop: 10 }}>
                  <div className="info-row"><span>鉴权</span><span>{info.authentication}</span></div>
                  <div className="info-row"><span>单批上限</span><span>{info.maxBatchSize} 条 / 批</span></div>
                  <div className="info-row"><span>写入规则</span><span>{info.idempotency}</span></div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 12 }}>
                  <a className="btn btn-ghost btn-md" href="/api/import/template" download>
                    下载 CSV 模板
                  </a>
                </div>
              </>
            ) : (
              <EmptyState title="接口信息不可用" description="请检查服务是否正常启动。" compact />
            )}
          </Panel>

          <Panel title="接入概览" subtitle="最近 7 天写入">
            {overview ? (
              <>
                <div className="info-list">
                  <div className="info-row">
                    <span>最近导入</span>
                    <span>{overview.lastImportAt ? formatDateTime(overview.lastImportAt) : "暂无记录"}</span>
                  </div>
                  <div className="info-row">
                    <span>最近批次</span>
                    <span className={overview.lastBatchFailed ? "is-warning" : overview.lastBatchCount ? "is-good" : ""}>
                      {overview.lastBatchCount
                        ? `${overview.lastBatchCount} 条 · ${overview.lastBatchFailed ? `${overview.lastBatchFailed} 条失败` : "全部成功"}`
                        : "—"}
                    </span>
                  </div>
                  <div className="info-row">
                    <span>7 天成功率</span>
                    <span className="is-good">{overview.sevenDaySuccessRate === null ? "—" : `${overview.sevenDaySuccessRate.toFixed(1)}%`}</span>
                  </div>
                  <div className="info-row"><span>数据来源</span><span>{overview.source}</span></div>
                </div>
                <div className="keyword-row" style={{ marginTop: 12 }}>
                  {platforms.map(([name, scopes]) => (
                    <span className="keyword-chip is-static" key={name}>
                      {name}
                      <b>{scopes.length}</b>
                    </span>
                  ))}
                </div>
                <p className="meta" style={{ marginTop: 12, lineHeight: 1.7 }}>
                  单批失败会整体回滚，不会写入部分数据；重试请使用相同批次内容。
                </p>
              </>
            ) : (
              <EmptyState title="暂无概览" compact />
            )}
          </Panel>
        </div>

        <section id="import-fields" className="anchor-section">
          <Panel
            title="导入字段与规范化"
            subtitle="字段缺失或类型不符会整批失败，不写入部分数据"
            action={<a className="link" href="/api/import/template" download>下载示例</a>}
          >
            <div className="table-wrap">
              <table className="table is-roomy">
                <thead>
                  <tr>
                    <th style={{ width: 150 }}>字段</th>
                    <th style={{ width: 60 }}>必填</th>
                    <th>说明</th>
                    <th style={{ width: 220 }}>示例</th>
                  </tr>
                </thead>
                <tbody>
                  {FIELDS.map((field) => (
                    <tr key={field.key}>
                      <td className="mono is-strong">{field.key}</td>
                      <td className="is-danger">{field.required}</td>
                      <td>{field.desc}</td>
                      <td className="mono">{field.sample}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="meta" style={{ marginTop: 10 }}>
              完整字段、平台能力矩阵与调用示例见项目根目录 <strong>API_IMPORT.md</strong>；修改导入契约时需同步更新该文档与调用示例。
            </p>
          </Panel>
        </section>
      </div>
      <Toast message={toast} />
    </>
  );
}
