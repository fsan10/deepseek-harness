"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Chip } from "@/components/ui/Chip";
import { Drawer } from "@/components/ui/Drawer";
import { Modal } from "@/components/ui/Modal";
import { Panel } from "@/components/ui/Panel";
import { SearchField } from "@/components/ui/SearchField";
import { Select } from "@/components/ui/Select";
import { EmptyState } from "@/components/ui/States";
import { formatDateTime } from "@/lib/date";
import { METRIC_PLATFORM_NAMES, METRIC_STATE_NAMES, type MetricProfile, type MetricSnapshot } from "@/lib/metric-types";
import type { Tone } from "@/lib/format";
import { BatchScopeDialog, type BatchScope } from "./collection/BatchScopeDialog";
import styles from "./collection/Collection.module.css";

type Scope = { reviews: boolean; reception: boolean; score: boolean };
type ShopForm = { shopName: string; scope: Scope; authCheckEnabled: boolean };
const SCOPES = [
  { key: "reviews", label: "评论采集", capability: "review_enabled" },
  { key: "reception", label: "接待量采集", capability: "reception_enabled" },
  { key: "score", label: "店铺体验分采集", capability: "score_enabled" },
] as const;

const STATE_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "active", label: "仅看启用中" },
  { value: "stopped", label: "仅看已停用" },
  { value: "unavailable", label: "仅看账号不可用" },
];
const SCOPE_OPTIONS = [
  { value: "", label: "全部采集范围" },
  { value: "reviews", label: "含评论采集" },
  { value: "reception", label: "含接待量采集" },
  { value: "score", label: "含体验分采集" },
];

const SCOPE_CAPABILITY: Record<string, "review_enabled" | "reception_enabled" | "score_enabled"> = {
  reviews: "review_enabled",
  reception: "reception_enabled",
  score: "score_enabled",
};
const SCOPE_COLLECT: Record<string, "collect_reviews" | "collect_reception" | "collect_score"> = {
  reviews: "collect_reviews",
  reception: "collect_reception",
  score: "collect_score",
};
const SCOPE_SHORT: Record<string, string> = { reviews: "评论", reception: "接待量", score: "体验分" };

const EMPTY_PROFILES: MetricProfile[] = [];

function loginClass(state?: string) {
  if (state === "valid") return styles.loginGood;
  if (state === "auth_required" || state === "needs_human") return styles.loginWarn;
  if (state === "error") return styles.loginDanger;
  return styles.loginIdle;
}

function statusChip(profile: MetricProfile): { tone: Tone; label: string } {
  if (profile.excluded) return { tone: "danger", label: profile.exclusion_reason || "账号不可用" };
  if (profile.disabled) return { tone: "neutral", label: "已停用" };
  return { tone: "good", label: "启用中" };
}

export function CollectionShops({ snapshot, busy, error, onAction }: {
  snapshot: MetricSnapshot | null;
  busy: string;
  error: string;
  onAction: (action: string, profile?: MetricProfile, extra?: Record<string, unknown>) => Promise<boolean>;
}) {
  const [query, setQuery] = useState("");
  const [keyword, setKeyword] = useState("");
  const [platform, setPlatform] = useState("");
  const [stateFilter, setStateFilter] = useState("");
  const [scopeFilter, setScopeFilter] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [editing, setEditing] = useState<MetricProfile | null>(null);
  const [form, setForm] = useState<ShopForm>({ shopName: "", scope: { reviews: false, reception: false, score: false }, authCheckEnabled: true });
  const [batchOpen, setBatchOpen] = useState(false);
  const [confirmDisable, setConfirmDisable] = useState<MetricProfile | null>(null);

  const profiles = snapshot?.profiles ?? EMPTY_PROFILES;
  const active = profiles.filter((profile) => !profile.excluded && !profile.disabled).length;
  const platforms = useMemo(() => Object.entries(METRIC_PLATFORM_NAMES).map(([value, label]) => ({ value, label })), []);
  const visible = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return profiles.filter((profile) => {
      if (keyword) {
        const haystack = `${profile.expected_shop_name} ${profile.shop_name} ${profile.company} ${profile.profile_name} ${METRIC_PLATFORM_NAMES[profile.platform] ?? ""}`.toLowerCase();
        if (!haystack.includes(keyword)) return false;
      }
      if (platform && profile.platform !== platform) return false;
      if (stateFilter === "active" && (profile.excluded || profile.disabled)) return false;
      if (stateFilter === "stopped" && (profile.excluded || !profile.disabled)) return false;
      if (stateFilter === "unavailable" && !profile.excluded) return false;
      if (scopeFilter) {
        const capability = profile[SCOPE_CAPABILITY[scopeFilter]];
        if (!(profile[SCOPE_COLLECT[scopeFilter]] && capability)) return false;
      }
      return true;
    });
  }, [profiles, query, platform, stateFilter, scopeFilter]);

  const selectable = visible.filter((profile) => !profile.excluded);
  const allSelected = selectable.length > 0 && selectable.every((profile) => selected.includes(profile.profile_id));
  const mapped = snapshot?.shops.find((shop) => shop.platform === METRIC_PLATFORM_NAMES[editing?.platform || ""] && shop.name === form.shopName);

  function toggleAll() {
    if (allSelected) setSelected((old) => old.filter((id) => !selectable.some((profile) => profile.profile_id === id)));
    else setSelected((old) => [...new Set([...old, ...selectable.map((profile) => profile.profile_id)])]);
  }

  function toggleOne(profile: MetricProfile) {
    setSelected((old) => old.includes(profile.profile_id) ? old.filter((id) => id !== profile.profile_id) : [...old, profile.profile_id]);
  }

  function edit(profile: MetricProfile) {
    setForm({
      shopName: profile.shop_name,
      authCheckEnabled: profile.auth_check_enabled !== 0,
      scope: {
        reviews: Boolean(profile.review_enabled && profile.collect_reviews),
        reception: Boolean(profile.reception_enabled && profile.collect_reception),
        score: Boolean(profile.score_enabled && profile.collect_score),
      },
    });
    setEditing(profile);
  }

  async function save() {
    if (!editing) return;
    const supported = {
      reviews: Boolean(editing.review_enabled),
      reception: Boolean(editing.reception_enabled),
      score: Boolean(editing.score_enabled),
    };
    const scope = {
      reviews: form.scope.reviews && supported.reviews,
      reception: form.scope.reception && supported.reception,
      score: form.scope.score && supported.score,
    };
    if (await onAction("configure", editing, { shopName: form.shopName, scope, authCheckEnabled: form.authCheckEnabled })) setEditing(null);
  }

  async function applyBatch(scope: BatchScope) {
    const done = await onAction("batch-configure", undefined, { profileIds: selected, scope });
    if (done) {
      setBatchOpen(false);
      setSelected([]);
    }
    return done;
  }

  const dirtyFilter = Boolean(keyword || query || platform || stateFilter || scopeFilter);

  return <>
    <Panel title="店铺与采集范围" subtitle={`${profiles.length} 家店铺 · ${active} 家启用；范围变更只作用于下一次定时任务`}
      action={<>
        <Button disabled={Boolean(busy)} onClick={() => void onAction("sync")}>{busy === "sync" ? "同步中…" : "同步店铺"}</Button>
        <Button variant="primary" disabled={Boolean(busy) || !selected.length} onClick={() => setBatchOpen(true)}>批量设置范围</Button>
      </>}>
      <div className={styles.toolbar}>
        <Select className={styles.toolbarSelect} ariaLabel="平台" options={[{ value: "", label: "全部平台" }, ...platforms]} value={platform} onChange={setPlatform} />
        <Select className={styles.toolbarSelect} ariaLabel="采集状态" options={STATE_OPTIONS} value={stateFilter} onChange={setStateFilter} />
        <Select className={styles.toolbarSelect} ariaLabel="采集范围" options={SCOPE_OPTIONS} value={scopeFilter} onChange={setScopeFilter} />
        <SearchField className={styles.toolbarSearch} placeholder="搜索店铺 / 公司" value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          onKeyDown={(event) => { if (event.key === "Enter") setQuery(keyword.trim()); }} />
        <Button size="sm" onClick={() => setQuery(keyword.trim())}>搜索</Button>
        <Button size="sm" disabled={!dirtyFilter} onClick={() => { setKeyword(""); setQuery(""); setPlatform(""); setStateFilter(""); setScopeFilter(""); }}>清空</Button>
        <span className={styles.spacer} />
        <span className={styles.toolbarMeta}>共 {profiles.length} 家 · 启用 {active} 家</span>
      </div>
      {selected.length ? <div className={styles.selectionBar}>
        <strong>已选 {selected.length} 家</strong>
        <span className="meta">只修改勾选店铺的采集范围，映射与登录状态不变</span>
        <span className={styles.spacer} />
        <Button size="sm" onClick={() => setSelected([])}>清除选择</Button>
        <Button size="sm" variant="primary" onClick={() => setBatchOpen(true)}>设置范围</Button>
      </div> : null}
      {visible.length ? <div className="table-wrap table-scroll collection-shops-table">
        <table className="table">
          <thead><tr>
            <th className={styles.selectCell}>
              <input className={styles.selectBox} type="checkbox" aria-label="全选可配置店铺" checked={allSelected} onChange={toggleAll} />
            </th>
            <th>平台 / 店铺</th><th>公司</th><th>采集范围</th><th>采集状态</th><th>登录状态</th>
            <th className="collection-operation">检查</th><th className="collection-operation">操作</th>
          </tr></thead>
          <tbody>{visible.map((profile) => {
            const scope = SCOPES.filter((item) => profile[SCOPE_COLLECT[item.key]] && profile[item.capability]).map((item) => SCOPE_SHORT[item.key]);
            const state = statusChip(profile);
            const unavailable = Boolean(profile.excluded || profile.disabled);
            return <tr key={profile.profile_id}>
              <td className={styles.selectCell}>
                <input className={styles.selectBox} type="checkbox" aria-label={`选择 ${profile.expected_shop_name || profile.profile_name}`}
                  disabled={Boolean(profile.excluded)} checked={selected.includes(profile.profile_id)} onChange={() => toggleOne(profile)} />
              </td>
              <td><strong>{profile.expected_shop_name || profile.profile_name}</strong><div className="meta">{METRIC_PLATFORM_NAMES[profile.platform]}</div></td>
              <td className="collection-company">{profile.company || "—"}</td>
              <td><span className={styles.scopeCell}>{scope.length ? scope.join(" · ") : "未启用采集"}</span></td>
              <td><Chip tone={state.tone}>{state.label}</Chip></td>
              <td><span className={loginClass(profile.auth_state)}>{METRIC_STATE_NAMES[profile.auth_state || ""] || "未检查"}</span>
                {profile.auth_check_enabled === 0 ? <div className="meta">自动检查已关闭</div> : null}</td>
              <td className="collection-operation">
                <button type="button" className={styles.checkLink} disabled={Boolean(busy) || unavailable}
                  onClick={() => void onAction("status", profile)}>
                  {busy === `status${profile.profile_id}` ? "检查中…" : "检查"}
                </button>
              </td>
              <td className="collection-operation">
                <div className="row-actions collection-shop-actions">
                  <button type="button" className={styles.checkLink} disabled={Boolean(busy) || unavailable}
                    onClick={() => void onAction("login", profile)}>
                    {busy === `login${profile.profile_id}` ? "登录中…" : "登录"}
                  </button>
                  <button type="button" disabled={Boolean(busy) || Boolean(profile.excluded)}
                    onClick={() => profile.disabled ? void onAction("availability", profile, { disabled: false }) : setConfirmDisable(profile)}>
                    {busy === `availability${profile.profile_id}` ? "保存中…" : profile.disabled ? "启用" : "停用"}
                  </button>
                  <button type="button" disabled={Boolean(busy)} onClick={() => edit(profile)}>配置</button>
                </div>
              </td>
            </tr>;
          })}</tbody>
        </table>
      </div> : <EmptyState title={profiles.length ? "当前筛选没有匹配店铺" : "还没有同步店铺"}
        description={profiles.length ? "清空搜索或调整筛选后再试。" : "同步后可统一配置每家店铺的采集范围与启停状态。"} compact />}
    </Panel>

    {editing ? <Drawer width={560} title="店铺配置" subtitle={`${METRIC_PLATFORM_NAMES[editing.platform]} · ${editing.expected_shop_name || editing.profile_name}`}
      onClose={() => { if (!busy) setEditing(null); }}
      footer={<>
        <Button disabled={Boolean(busy)} onClick={() => setEditing(null)}>取消</Button>
        <Button variant="primary" disabled={Boolean(busy)} onClick={() => void save()}>
          {busy === `configure${editing.profile_id}` ? "保存中…" : "保存配置"}
        </Button>
      </>}>
      {error ? <p className="is-danger" role="alert">{error}</p> : null}
      <div className={styles.drawerIdentity}>
        <strong>{editing.expected_shop_name || editing.profile_name}</strong>
        <span>{editing.company || "未填写公司"} · {editing.profile_name}</span>
        <span>实际登录店铺：{editing.actual_shop_name || "尚未核验"}</span>
      </div>
      <label className={styles.drawerField}>
        <span>指标入库店铺</span>
        <select className="input" value={form.shopName} onChange={(event) => setForm((old) => ({ ...old, shopName: event.target.value }))}>
          <option value="">未配置</option>
          {snapshot?.shops.filter((shop) => shop.platform === METRIC_PLATFORM_NAMES[editing.platform]).map((shop) => <option value={shop.name} key={shop.name}>{shop.name}</option>)}
        </select>
      </label>
      <div>
        <div className={styles.drawerField}><span>采集范围</span></div>
        {SCOPES.map((item) => {
          const supported = Boolean(editing[item.capability]);
          return <div className={`${styles.scopeRow} ${supported ? "" : styles.isDisabled}`.trim()} key={item.key}>
            <span>{item.label}{supported ? "" : " · 当前平台或入库店铺不支持"}</span>
            <button type="button" className={`switch ${form.scope[item.key] && supported ? "is-on" : ""}`} role="switch"
              aria-checked={form.scope[item.key] && supported} aria-label={`${item.label}范围`} disabled={Boolean(busy) || !supported}
              onClick={() => setForm((old) => ({ ...old, scope: { ...old.scope, [item.key]: !old.scope[item.key] } }))} />
          </div>;
        })}
        <p className="meta" style={{ marginTop: 8 }}>三类开关独立生效；保存后作用于下一次定时任务，不影响历史数据。</p>
      </div>
      <div>
        <div className={styles.scopeRow}>
          <span>自动检查登录状态</span>
          <button type="button" className={`switch ${form.authCheckEnabled ? "is-on" : ""}`} role="switch"
            aria-checked={form.authCheckEnabled} aria-label="自动检查登录状态" disabled={Boolean(busy)}
            onClick={() => setForm((old) => ({ ...old, authCheckEnabled: !old.authCheckEnabled }))} />
        </div>
        <p className="meta" style={{ marginTop: 8, lineHeight: 1.7 }}>启用中的店铺默认开启，按运行与环境中设置的间隔检查。关闭后跳过定时检查；采集时登录失效仍会自动登录并继续，遇到验证码、滑块等验证时通知人工。</p>
      </div>
      <div className={styles.infoRows}>
        <div><span>登录状态</span><span className={loginClass(editing.auth_state)}>{METRIC_STATE_NAMES[editing.auth_state || ""] || "未检查"}</span></div>
        <div><span>最近检查</span><span>{formatDateTime(editing.checked_at)}</span></div>
        <div><span>映射平台</span><span>{METRIC_PLATFORM_NAMES[editing.platform]}{mapped ? " · 已匹配店铺" : " · 未匹配入库店铺"}</span></div>
      </div>
      <div className="notice" role="note">关闭某类采集后，该店铺不再进入对应任务；登录会话与历史数据保留，可随时恢复。</div>
    </Drawer> : null}

    {batchOpen ? <BatchScopeDialog count={selected.length} busy={Boolean(busy)} onClose={() => setBatchOpen(false)} onApply={applyBatch} /> : null}

    {confirmDisable ? <Modal title="停用该店铺？" width={460} onClose={() => setConfirmDisable(null)}
      footer={<>
        <Button onClick={() => setConfirmDisable(null)}>取消</Button>
        <Button variant="danger" disabled={Boolean(busy)} onClick={() => {
          void onAction("availability", confirmDisable, { disabled: true }).then((done) => { if (done) setConfirmDisable(null); });
        }}>停用</Button>
      </>}>
      <p style={{ lineHeight: 1.8 }}>
        {confirmDisable.expected_shop_name || confirmDisable.profile_name} 将跳过评论、接待量、体验分三类采集；
        登录会话与历史数据保留，可随时恢复。
      </p>
    </Modal> : null}
  </>;
}
