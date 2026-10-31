"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { CollectionShops } from "./CollectionShops";
import { EventPanel } from "./collection/EventPanel";
import { PlanTable } from "./collection/PlanTable";
import { RuntimePanel } from "./collection/RuntimePanel";
import { Topbar } from "@/components/shell/Topbar";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { Panel } from "@/components/ui/Panel";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { ErrorState } from "@/components/ui/States";
import { Toast, useToast } from "@/components/ui/Toast";
import { ToggleSetting } from "@/components/ui/ToggleSetting";
import { jsonBody, jsonRequest } from "@/lib/client";
import type { MetricProfile, MetricSnapshot } from "@/lib/metric-types";
import styles from "./MetricCollection.module.css";
import stylesModule from "./collection/Collection.module.css";

type AlertConfig = {
  enabled: boolean;
  app_id: string;
  app_secret: string;
  chat_id: string;
  mention_open_id: string;
  relay_url: string;
  relay_token: string;
  app_secret_configured?: boolean;
  relay_token_configured?: boolean;
};

const SETTINGS_TABS = [
  { value: "shops", label: "店铺与范围" },
  { value: "plans", label: "采集计划" },
  { value: "runtime", label: "运行与环境" },
  { value: "alerts", label: "通知与异常" },
];
const DEFAULT_ALERT: AlertConfig = { enabled: false, app_id: "", app_secret: "", chat_id: "", mention_open_id: "", relay_url: "", relay_token: "" };
const ALERT_FIELDS = [
  { key: "app_id", label: "飞书应用 App ID" },
  { key: "app_secret", label: "App Secret", secret: true, configured: "app_secret_configured" },
  { key: "chat_id", label: "接收提醒的群 Chat ID（oc_）" },
  { key: "mention_open_id", label: "提醒人员 Open ID（可选，ou_）" },
  { key: "relay_url", label: "共享人工处理服务地址（可选）" },
  { key: "relay_token", label: "共享服务机器人令牌（可选）", secret: true, configured: "relay_token_configured" },
] as const;

export function MetricSettings() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const requestedTab = pathname === "/collection/settings/shops" ? "shops" : params.get("tab") || "shops";
  const tab = SETTINGS_TABS.some((item) => item.value === requestedTab) ? requestedTab : "shops";

  const [snapshot, setSnapshot] = useState<MetricSnapshot | null>(null);
  const [checkedAt, setCheckedAt] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [alert, setAlert] = useState<AlertConfig>(DEFAULT_ALERT);
  const [initialized, setInitialized] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [dirtyPlans, setDirtyPlans] = useState(0);
  const [pendingTab, setPendingTab] = useState<string | null>(null);
  const { toast, notify } = useToast();

  const load = useCallback(async () => {
    const result = await jsonRequest<MetricSnapshot>("/api/collection");
    setSnapshot(result);
    setCheckedAt(Date.now());
    if (result.workerError) setError(result.workerError);
    return result;
  }, []);

  useEffect(() => {
    let alive = true;
    void Promise.resolve()
      .then(() => Promise.all([load(), jsonRequest<{ config: AlertConfig }>("/api/collection/notifications")]))
      .then(([, notifications]) => {
        if (!alive) return;
        setAlert({ ...DEFAULT_ALERT, ...notifications.config });
        setInitialized(true);
      })
      .catch((caught) => { if (alive) setError(caught instanceof Error ? caught.message : "读取配置失败"); });
    const timer = setInterval(() => void load().catch(() => {}), 5000);
    return () => { alive = false; clearInterval(timer); };
  }, [load]);

  function messageFor(name: string, result: unknown) {
    if (name === "sync") return "已同步六个平台业务账号";
    if (name === "configure" || name === "mapping") return "店铺配置已保存";
    if (name === "login") return "会话已加密保存，HTTP 身份核验通过";
    if (name === "availability") return "店铺采集状态已更新，三类采集同时生效";
    if (name === "batch-configure") {
      const summary = result as { updated?: number; skipped?: number } | null;
      const updated = summary?.updated ?? 0;
      const skipped = summary?.skipped ?? 0;
      return `已更新 ${updated} 家店铺的采集范围${skipped ? `，${skipped} 项因平台不支持已跳过` : ""}`;
    }
    return "登录状态已更新";
  }

  async function action(name: string, profile?: MetricProfile, extra: Record<string, unknown> = {}) {
    setBusy(name + (profile?.profile_id || ""));
    setError("");
    try {
      const result = await jsonRequest<unknown>("/api/collection", jsonBody("POST", { action: name, profileId: profile?.profile_id, ...extra }));
      notify(messageFor(name, result));
      await load();
      return true;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "操作失败");
      return false;
    } finally {
      setBusy("");
    }
  }

  async function saveAuthPoll(minutes: number) {
    setBusy("service"); setError("");
    try {
      await jsonRequest("/api/collection", jsonBody("PUT", { auth_poll_minutes: minutes }));
      notify("共用登录检查间隔已保存");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setBusy("");
    }
  }

  async function refreshSettings() {
    setError("");
    try {
      await load();
      setRefreshKey((value) => value + 1);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "刷新失败");
    }
  }

  async function saveAlerts() {
    setBusy("alerts"); setError("");
    try {
      const result = await jsonRequest<{ config: AlertConfig }>("/api/collection/notifications", jsonBody("PUT", alert));
      setAlert({ ...DEFAULT_ALERT, ...result.config });
      notify("飞书与人工处理配置已加密保存");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "保存飞书配置失败");
    } finally {
      setBusy("");
    }
  }

  function navigate(value: string) {
    router.replace(value === "shops" ? "/collection/settings/shops" : `/collection/settings?tab=${value}`, { scroll: false });
  }

  function changeTab(value: string) {
    if (value === tab) return;
    if (tab === "plans" && dirtyPlans > 0) {
      setPendingTab(value);
      return;
    }
    navigate(value);
  }

  return <>
    <Topbar title="采集设置" actions={<>
      <Link className="btn btn-ghost" aria-label="前往采集" href="/reviews/collection"><Icon name="play" size={14} /><span>前往采集</span></Link>
      <Button icon="refresh" disabled={Boolean(busy)} onClick={() => void refreshSettings()}>刷新</Button>
    </>} />
    <div className="content stack">
      <div className="filter-bar collection-settings-nav">
        <SegmentedControl className="seg-settings" options={SETTINGS_TABS} value={tab} ariaLabel="采集设置栏目" onChange={changeTab} />
      </div>
      {error ? <ErrorState message={error} onRetry={() => void load().catch((caught: Error) => setError(caught.message))} /> : null}

      {tab === "shops" ? <CollectionShops snapshot={snapshot} busy={busy} error={error} onAction={action} /> : null}

      {tab === "plans" ? <PlanTable snapshot={snapshot} onOpenRuntime={() => navigate("runtime")}
        onSaved={() => { notify("采集计划已保存"); void load(); }} onDirtyChange={setDirtyPlans} /> : null}

      {tab === "runtime" ? <RuntimePanel snapshot={snapshot} workerError={snapshot?.workerError ?? ""} busy={busy === "service"}
        checkedAt={checkedAt} refreshKey={String(refreshKey)} onSaveAuthPoll={saveAuthPoll} /> : null}

      {tab === "alerts" ? <>
        <EventPanel />
        <div className={stylesModule.alertBanner}>
          保存配置不会发送消息；App Secret 与令牌使用当前 Windows 用户加密保存，留空表示保留原值。
        </div>
        <div className={stylesModule.alertCards}>
          <Panel title="飞书异常提醒" subtitle="配置由你填写 · 应用需具备发送消息权限并已加入目标群">
            <ToggleSetting label="启用飞书异常提醒" checked={alert.enabled} onChange={(enabled) => setAlert((old) => ({ ...old, enabled }))} />
            <div className={styles.formGrid} style={{ marginTop: 22 }}>{ALERT_FIELDS.map((field) => <div className="form-row" key={field.key}>
              <label htmlFor={`alert-${field.key}`}>{field.label}</label>
              <input className="input" id={`alert-${field.key}`} type={"secret" in field && field.secret ? "password" : "text"} autoComplete="off"
                value={alert[field.key]} placeholder={"configured" in field && alert[field.configured] ? "已设置，留空保留" : ""}
                onChange={(event) => setAlert((old) => ({ ...old, [field.key]: event.target.value }))} />
            </div>)}</div>
            <p className="meta" style={{ lineHeight: 1.8, marginTop: 14 }}>共享人工处理服务可填写 mock_coffice 的异常处理服务地址和令牌。会话失效后自动登录并更新会话；遇到验证码、滑块等验证时通知人工，处理后自动继续。密钥使用当前 Windows 用户加密保存。</p>
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 14 }}>
              <Button variant="primary" disabled={Boolean(busy) || !initialized} onClick={() => void saveAlerts()}>{busy === "alerts" ? "保存中…" : "保存飞书配置"}</Button>
            </div>
          </Panel>
          <Panel title="什么时候发提醒" subtitle="提醒与异常记录共用同一条事件">
            <div className={stylesModule.alertRules}>
              <p>会话失效先自动登录；遇验证码、滑块或二次验证时提醒人工。</p>
              <p>人工验证等待超过 5 分钟，再提醒登录失败；成功进度保留。</p>
              <p>同一店铺同一类型 30 分钟内只提醒一次。</p>
              <p>发送结果记入该条异常，失败保留原因，不自动重发。</p>
            </div>
          </Panel>
        </div>
      </> : null}
    </div>

    {pendingTab ? <Modal title="离开「采集计划」？" width={440} onClose={() => setPendingTab(null)}
      footer={<>
        <Button onClick={() => setPendingTab(null)}>留在本页</Button>
        <Button variant="danger" onClick={() => { const target = pendingTab; setPendingTab(null); navigate(target); }}>放弃并离开</Button>
      </>}>
      <p style={{ lineHeight: 1.8 }}>有 {dirtyPlans} 项未保存的采集计划，离开后会丢弃这些改动。</p>
    </Modal> : null}

    <Toast message={toast} />
  </>;
}
