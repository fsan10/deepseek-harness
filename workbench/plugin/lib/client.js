/**
 * dsh-workbench 客户端：侧边栏「工作台」入口 + 主区全局面板。
 *
 * 面板是「视图包渲染器」：14 个页面由 views/*.view.json 声明，数据全部来自
 * /api/workbench/*。页面自己不算数，也不缓存假数据。
 */
window.__ModuleLoader__.load({
  id: 'dsh-workbench',
  factory(require) {
    const React = require('react')
    const h = React.createElement
    const { useState, useEffect, useCallback, useRef, useMemo } = React

    const CSS = `
.wb-root{display:flex;flex-direction:column;height:100%;min-height:0;color:inherit;font-size:13px;position:relative;
  background:var(--dsw-alias-bg-base,#fff);--wb-line:var(--dsw-alias-border-l2,#e6e8ec);
  --wb-soft:var(--dsw-alias-bg-layer-1,#f7f8fa);--wb-brand:var(--dsw-alias-brand-primary,#2f6bff);
  --wb-ok:var(--dsw-alias-state-success-primary,#12945a);--wb-warn:var(--dsw-alias-state-warn-primary,#c77700);
  --wb-risk:var(--dsw-alias-state-error-primary,#d93838);--wb-mute:color-mix(in srgb,currentColor 55%,transparent)}
.wb-top{display:flex;align-items:center;gap:12px;height:52px;padding:0 16px;border-bottom:1px solid var(--wb-line);flex:none}
.wb-title{font-size:14px;font-weight:600;letter-spacing:.2px}
.wb-sub{font-size:11px;color:var(--wb-mute)}
.wb-spacer{flex:1}
.wb-body{display:flex;flex:1;min-height:0}
.wb-nav{width:196px;flex:none;border-right:1px solid var(--wb-line);overflow:auto;padding:10px 8px 24px}
.wb-group{margin:14px 0 4px;padding:0 8px;font-size:10px;letter-spacing:.12em;color:var(--wb-mute);text-transform:uppercase}
.wb-navitem{display:block;width:100%;text-align:left;border:0;background:none;color:inherit;
  padding:7px 8px;border-radius:7px;font-size:13px;cursor:pointer;line-height:1.25}
.wb-navitem:hover{background:var(--wb-soft)}
.wb-navitem[data-on="1"]{background:var(--wb-brand);color:#fff}
.wb-navitem[data-on="1"] .wb-q{color:rgba(255,255,255,.78)}
.wb-q{display:block;font-size:10px;color:var(--wb-mute);margin-top:2px;line-height:1.35}
.wb-main{flex:1;min-width:0;overflow:auto;padding:20px 24px 44px}
.wb-head{margin-bottom:16px}
.wb-h1{font-size:19px;font-weight:600;margin:0}
.wb-ask{font-size:12px;color:var(--wb-mute);margin-top:4px}
.wb-btn{display:inline-flex;align-items:center;gap:6px;height:28px;padding:0 10px;border-radius:7px;
  border:1px solid var(--wb-line);background:var(--dsw-alias-bg-layer-1,#fff);color:inherit;font-size:12px;cursor:pointer}
.wb-btn:hover{background:var(--wb-soft)}
.wb-btn[data-tone="primary"]{background:var(--wb-brand);border-color:transparent;color:#fff}
.wb-btn[data-tone="danger"]{color:var(--wb-risk);border-color:color-mix(in srgb,var(--wb-risk) 35%,var(--wb-line))}
.wb-btn:disabled{opacity:.45;cursor:not-allowed}
.wb-chip{display:inline-flex;align-items:center;gap:5px;height:20px;padding:0 7px;border-radius:999px;
  font-size:11px;background:var(--wb-soft);color:var(--wb-mute);white-space:nowrap}
.wb-chip[data-tone="ok"]{color:var(--wb-ok);background:color-mix(in srgb,var(--wb-ok) 12%,transparent)}
.wb-chip[data-tone="warn"]{color:var(--wb-warn);background:color-mix(in srgb,var(--wb-warn) 12%,transparent)}
.wb-chip[data-tone="risk"]{color:var(--wb-risk);background:color-mix(in srgb,var(--wb-risk) 12%,transparent)}
.wb-kpis{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-bottom:16px}
.wb-kpi{border:1px solid var(--wb-line);border-radius:12px;padding:14px 16px;background:var(--dsw-alias-bg-layer-1,#fff)}
.wb-kpi b{display:block;font-size:26px;font-weight:600;letter-spacing:-.02em;line-height:1.15;margin-top:4px}
.wb-kpi span{display:block;font-size:11px;color:var(--wb-mute)}
.wb-kpi em{display:block;font-size:11px;font-style:normal;margin-top:2px;color:var(--wb-mute)}
.wb-cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.wb-card{border:1px solid var(--wb-line);border-radius:12px;background:var(--dsw-alias-bg-layer-1,#fff);overflow:hidden}
.wb-card>h3{margin:0;padding:11px 14px;font-size:12px;font-weight:600;border-bottom:1px solid var(--wb-line);color:var(--wb-mute)}
.wb-row{display:flex;gap:10px;padding:9px 14px;border-bottom:1px solid color-mix(in srgb,var(--wb-line) 60%,transparent);align-items:flex-start}
.wb-row:last-child{border-bottom:0}
.wb-dot{width:7px;height:7px;border-radius:50%;margin-top:6px;flex:none;background:var(--wb-mute)}
.wb-dot[data-tone="risk"]{background:var(--wb-risk)}.wb-dot[data-tone="warn"]{background:var(--wb-warn)}
.wb-dot[data-tone="ok"]{background:var(--wb-ok)}
.wb-row b{font-weight:500;display:block}
.wb-row small{display:block;color:var(--wb-mute);font-size:11px;margin-top:2px}
.wb-table{width:100%;border-collapse:collapse;font-size:12px}
.wb-table th{position:sticky;top:0;background:var(--dsw-alias-bg-layer-1,#fff);text-align:left;font-weight:500;
  color:var(--wb-mute);padding:9px 12px;border-bottom:1px solid var(--wb-line);font-size:11px;white-space:nowrap;z-index:1}
.wb-table td{padding:9px 12px;border-bottom:1px solid color-mix(in srgb,var(--wb-line) 55%,transparent);vertical-align:top}
.wb-table tr:hover td{background:var(--wb-soft)}
.wb-table td[data-align="right"],.wb-table th[data-align="right"]{text-align:right;font-variant-numeric:tabular-nums}
.wb-wrap{border:1px solid var(--wb-line);border-radius:12px;overflow:auto;max-height:calc(100vh - 300px);background:var(--dsw-alias-bg-layer-1,#fff)}
.wb-group-head{display:flex;align-items:center;gap:10px;padding:10px 14px;background:var(--wb-soft);
  border-bottom:1px solid var(--wb-line);font-size:12px;font-weight:600}
.wb-hbar{display:flex;gap:2px;align-items:center}
.wb-hbar i{display:block;width:5px;height:12px;border-radius:2px;background:var(--wb-line)}
.wb-hbar i[data-on="1"]{background:var(--wb-brand)}
.wb-score{font-variant-numeric:tabular-nums;font-weight:600}
.wb-score[data-tone="ok"]{color:var(--wb-ok)}.wb-score[data-tone="warn"]{color:var(--wb-warn)}
.wb-score[data-tone="risk"]{color:var(--wb-risk)}
.wb-cells{display:inline-flex;gap:6px}
.wb-cells i{display:block;width:12px;height:12px;border-radius:50%;background:var(--wb-soft);border:1px solid var(--wb-line)}
.wb-cells i[data-v="2"]{background:var(--wb-ok);border-color:transparent}
.wb-cells i[data-v="1"]{background:var(--wb-warn);border-color:transparent}
.wb-cells i[data-v="0"]{background:color-mix(in srgb,var(--wb-mute) 45%,transparent);border-color:transparent}
.wb-cells i[data-v="null"]{background:transparent;border-style:dashed}
.wb-legend{display:flex;gap:14px;font-size:11px;color:var(--wb-mute);margin:0 0 12px;flex-wrap:wrap}
.wb-legend span{display:inline-flex;align-items:center;gap:6px}
.wb-empty{padding:26px;text-align:center;color:var(--wb-mute);font-size:12px}
.wb-note{margin-top:12px;font-size:11px;color:var(--wb-mute);line-height:1.7}
.wb-drawer{position:absolute;top:0;right:0;bottom:0;width:min(460px,80%);background:var(--dsw-alias-bg-base,#fff);
  border-left:1px solid var(--wb-line);box-shadow:-16px 0 40px rgba(0,0,0,.12);display:flex;flex-direction:column;z-index:5}
.wb-drawer-head{display:flex;align-items:center;gap:10px;padding:14px 16px;border-bottom:1px solid var(--wb-line)}
.wb-drawer-body{flex:1;overflow:auto;padding:16px}
.wb-kv{display:grid;grid-template-columns:96px 1fr;gap:8px 12px;font-size:12px;margin:0 0 18px}
.wb-kv dt{color:var(--wb-mute)}.wb-kv dd{margin:0;word-break:break-all}
.wb-sec{font-size:11px;letter-spacing:.1em;color:var(--wb-mute);margin:0 0 8px}
.wb-log{font-family:ui-monospace,Consolas,monospace;font-size:11px;line-height:1.8;color:var(--wb-mute);
  border:1px solid var(--wb-line);border-radius:8px;padding:10px;max-height:180px;overflow:auto;white-space:pre-wrap}
.wb-confirm{margin-top:14px;border:1px solid color-mix(in srgb,var(--wb-warn) 40%,var(--wb-line));
  background:color-mix(in srgb,var(--wb-warn) 7%,transparent);border-radius:10px;padding:12px;font-size:12px;line-height:1.6}
.wb-confirm b{display:block;margin-bottom:6px}
.wb-confirm .wb-actions{display:flex;gap:8px;margin-top:10px}
.wb-toast{position:absolute;left:50%;bottom:18px;transform:translateX(-50%);background:#1f2328;color:#fff;
  padding:8px 14px;border-radius:999px;font-size:12px;z-index:9;box-shadow:0 8px 24px rgba(0,0,0,.2)}
.wb-loading{padding:40px;text-align:center;color:var(--wb-mute)}
.wb-nav::-webkit-scrollbar,.wb-main::-webkit-scrollbar,.wb-wrap::-webkit-scrollbar{width:10px;height:10px}
.wb-nav::-webkit-scrollbar-thumb,.wb-main::-webkit-scrollbar-thumb,.wb-wrap::-webkit-scrollbar-thumb{
  background:color-mix(in srgb,currentColor 18%,transparent);border-radius:99px;border:3px solid transparent;background-clip:padding-box}
`

    async function api(path, init) {
      const response = await fetch(`/api/workbench${path}`, {
        headers: { 'content-type': 'application/json' },
        ...init,
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        const error = new Error(payload.error ?? `HTTP ${response.status}`)
        error.payload = payload
        error.status = response.status
        throw error
      }
      return payload
    }

    function toneOfState(state) {
      if (state === 'running') return 'ok'
      if (state === 'degraded' || state === 'starting') return 'warn'
      if (state === 'failed') return 'risk'
      return undefined
    }

    function scoreTone(score) {
      if (score >= 80) return 'ok'
      if (score >= 55) return 'warn'
      return 'risk'
    }

    function Chip({ tone, children }) {
      return h('span', { className: 'wb-chip', 'data-tone': tone }, children)
    }

    function Nav({ views, active, onPick }) {
      const groups = []
      for (const view of views) {
        const group = groups.find(item => item.domain === view.domain)
        if (group === undefined) groups.push({ domain: view.domain, items: [view] })
        else group.items.push(view)
      }
      const sections = groups.map(group => {
        const items = group.items.map(view => h('button', {
          key: view.id,
          className: 'wb-navitem',
          'data-on': view.id === active ? '1' : '0',
          onClick: () => onPick(view.id),
          title: view.question,
        },
        h('span', null, view.title),
        h('span', { className: 'wb-q' }, view.question)))
        const heading = group.domain === '今日'
          ? null
          : h('div', { className: 'wb-group' }, group.domain)
        return h('div', { key: group.domain }, heading, items)
      })
      return h('nav', { className: 'wb-nav' }, sections)
    }

    function HealthBar({ parts }) {
      const segs = [
        ['可用性', parts.availability, 40],
        ['成功率', parts.success, 30],
        ['时延', parts.latency, 20],
        ['新鲜度', parts.freshness, 10],
      ]
      const title = segs.map(([name, value, max]) => `${name} ${value}/${max}`).join(' · ')
      const bars = segs.map(([name, value, max]) => {
        const ratio = value / max
        const color = ratio >= 0.6 ? 'var(--wb-ok)' : ratio >= 0.3 ? 'var(--wb-warn)' : 'var(--wb-risk)'
        return h('i', {
          key: name,
          style: { background: color, opacity: 0.35 + 0.65 * ratio },
        })
      })
      return h('div', { className: 'wb-hbar', title }, bars)
    }

    function Overview({ data }) {
      const kpis = h('div', { className: 'wb-kpis' }, data.kpis.map(kpi => h('div', { className: 'wb-kpi', key: kpi.label },
        h('span', null, kpi.label),
        h('b', null, kpi.value),
        h('em', null, kpi.hint))))

      const cards = data.lists.map(list => {
        const rows = list.rows.length === 0
          ? h('div', { className: 'wb-empty' }, '没有条目')
          : list.rows.map((row, index) => h('div', { className: 'wb-row', key: index },
            h('i', { className: 'wb-dot', 'data-tone': row.tone ?? 'muted' }),
            h('div', null,
              h('b', null, row.text),
              row.meta ? h('small', null, row.meta) : null)))
        return h('div', { className: 'wb-card', key: list.title },
          h('h3', null, list.title),
          rows)
      })

      return h('div', null,
        kpis,
        h('div', { className: 'wb-cols' }, cards),
        data.note ? h('div', { className: 'wb-note' }, data.note) : null)
    }

    function Control({ data, onOpen }) {
      const head = ['项目', '形态', '状态', '健康分', '构成', '时延', '最近运行', '负责人']
      const header = h('tr', null, head.map((label, index) =>
        h('th', { key: label, 'data-align': index === 3 ? 'right' : undefined }, label)))

      const rows = []
      for (const group of data.groups) {
        // 空形态不占行：四种形态的说明放在分组标题里，没有条目就没有这一组
        if (group.rows.length === 0) continue
        const caption = group.form === 'service' ? '服务 · 启停重启'
          : group.form === 'job' ? '任务 · 跑一次看上次'
            : group.form === 'mcp' ? '连接 · 重连看调用量'
              : '视图 · 打开即可'
        rows.push(h('tr', { key: `g-${group.form}` },
          h('td', { colSpan: 8, style: { padding: 0 } },
            h('div', { className: 'wb-group-head' },
              h('span', null, caption),
              h(Chip, null, `${group.rows.length} 个`)))))
        for (const row of group.rows) {
          const lastRun = row.lastRun === null || row.lastRun === undefined
            ? '无记录'
            : `${new Date(row.lastRun.at).toLocaleTimeString('zh-CN', { hour12: false })} · ${row.lastRun.ok ? '成功' : '失败'}`
          rows.push(h('tr', {
            key: row.id,
            style: { cursor: 'pointer' },
            onClick: () => onOpen(row.id),
          },
          h('td', null,
            h('b', { style: { fontWeight: 500 } }, row.name),
            row.problems.length > 0
              ? h('small', { style: { color: 'var(--wb-risk)', display: 'block' } }, row.problems.join('；'))
              : null),
          h('td', null, h(Chip, null, row.form)),
          h('td', null, h(Chip, { tone: toneOfState(row.state) }, row.label)),
          h('td', { 'data-align': 'right' }, h('span', { className: 'wb-score', 'data-tone': scoreTone(row.health) }, String(row.health))),
          h('td', null, h(HealthBar, { parts: row.parts })),
          h('td', null, row.latencyMs === null ? '—' : `${row.latencyMs}ms`),
          h('td', null, lastRun),
          h('td', null, row.owner)))
        }
      }

      const chips = h('div', { style: { display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' } },
        h(Chip, null, `登记 ${data.summary.total}`),
        h(Chip, { tone: 'ok' }, `运行中 ${data.summary.running}`),
        h(Chip, { tone: 'warn' }, `降级 ${data.summary.degraded}`),
        h(Chip, { tone: 'risk' }, `失败 ${data.summary.failed}`),
        h('span', { className: 'wb-spacer' }),
        h('span', { className: 'wb-sub' }, '点任意行看健康分构成与最近运行'))

      return h('div', null,
        chips,
        h('div', { className: 'wb-wrap' },
          h('table', { className: 'wb-table' },
            h('thead', null, header),
            h('tbody', null, rows))),
        data.note ? h('div', { className: 'wb-note' }, data.note) : null)
    }

    function TableView({ data }) {
      const kpis = data.kpis !== undefined && data.kpis.length > 0
        ? h('div', { className: 'wb-kpis', style: { gridTemplateColumns: `repeat(${Math.min(3, data.kpis.length)},minmax(0,1fr))` } },
          data.kpis.map(kpi => h('div', { className: 'wb-kpi', key: kpi.label },
            h('span', null, kpi.label),
            h('b', null, String(kpi.value)),
            h('em', null, kpi.hint))))
        : null

      const header = h('tr', null, data.columns.map(column =>
        h('th', { key: column.key, 'data-align': column.align, style: { width: column.width } }, column.label)))

      const body = data.rows.length === 0
        ? h('div', { className: 'wb-empty' }, '没有数据')
        : h('table', { className: 'wb-table' },
          h('thead', null, header),
          h('tbody', null, data.rows.map((row, index) => h('tr', { key: index },
            data.columns.map(column => h('td', {
              key: column.key,
              'data-align': column.align,
            }, String(row[column.key] ?? '—')))))))

      return h('div', null,
        kpis,
        h('div', { className: 'wb-wrap' }, body),
        data.note ? h('div', { className: 'wb-note' }, data.note) : null)
    }

    function MatrixView({ data }) {
      const chips = data.summary === undefined ? null : h('div', { style: { display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' } },
        h(Chip, null, `${data.summary.shops} 个店铺 · ${data.summary.platforms} 个平台`),
        h(Chip, { tone: 'ok' }, `接待 ${data.summary.reception}`),
        h(Chip, { tone: 'ok' }, `评分 ${data.summary.score}`),
        h(Chip, { tone: 'warn' }, `直播 ${data.summary.live}`))

      const legend = h('div', { className: 'wb-legend' }, data.legend.map(item => h('span', { key: String(item.value) },
        h('span', { className: 'wb-cells' }, h('i', { 'data-v': String(item.value) })),
        item.label)))

      const header = h('tr', null,
        h('th', null, '店铺'),
        h('th', null, '平台'),
        data.columns.map(column => h('th', { key: column.key, style: { textAlign: 'center' } }, column.label)),
        h('th', null, '备注'))

      const rows = data.rows.map((row, index) => h('tr', { key: index },
        h('td', null, row.label),
        h('td', null, h(Chip, null, row.sub)),
        row.cells.map((cell, cellIndex) => h('td', { key: cellIndex, style: { textAlign: 'center' } },
          h('span', { className: 'wb-cells' }, h('i', { 'data-v': String(cell) })))),
        h('td', { style: { color: 'var(--wb-mute)' } }, row.meta)))

      return h('div', null,
        chips,
        legend,
        h('div', { className: 'wb-wrap' },
          h('table', { className: 'wb-table' },
            h('thead', null, header),
            h('tbody', null, rows))),
        data.note ? h('div', { className: 'wb-note' }, data.note) : null)
    }

    function GovernanceView({ data }) {
      const chips = h('div', { style: { display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' } },
        h(Chip, null, `${data.summary.roles ?? data.summary.companies} 组`),
        data.summary.mapped === undefined
          ? null
          : h(Chip, { tone: 'warn' }, `可反推归属 ${data.summary.mapped}/${data.summary.totalShops}`))

      const cards = data.groups.map(group => h('div', { className: 'wb-card', key: group.label },
        h('h3', null, group.label),
        h('div', { style: { padding: '8px 14px', fontSize: 11, color: 'var(--wb-mute)' } }, group.sub),
        group.rows.map((row, index) => h('div', { className: 'wb-row', key: index },
          h('i', { className: 'wb-dot', 'data-tone': row.tone ?? 'muted' }),
          h('div', null,
            h('b', null, row.label),
            row.meta ? h('small', null, row.meta) : null)))))

      const recent = data.recent === undefined ? null : h('div', { style: { marginTop: 16 } },
        h('div', { className: 'wb-sec' }, '最近审计'),
        h('div', { className: 'wb-log' }, data.recent.map(row =>
          `${String(row.at).slice(11, 19)}  ${row.action ?? '?'}  ${row.project ?? ''}  ${row.ok === false ? '拒绝/失败' : '成功'}  ${row.intent ?? ''}`).join('\n')))

      return h('div', null,
        chips,
        h('div', { className: 'wb-cols' }, cards),
        recent,
        data.note ? h('div', { className: 'wb-note' }, data.note) : null)
    }

    function UnavailableView({ data }) {
      const inventory = data.inventory.length === 0
        ? h('div', { className: 'wb-empty' }, '没有可展示的资产')
        : data.inventory.map((item, index) => h('div', { className: 'wb-row', key: index },
          h('i', { className: 'wb-dot', 'data-tone': 'ok' }),
          h('div', null,
            h('b', null, item.name),
            h('small', null, item.meta))))

      return h('div', null,
        h('div', { className: 'wb-card', style: { padding: 18, marginBottom: 14 } },
          h('div', { style: { fontSize: 13, fontWeight: 600, marginBottom: 6 } }, '数据源未接入'),
          h('div', { style: { color: 'var(--wb-mute)', lineHeight: 1.7 } }, data.reason)),
        h('div', { className: 'wb-cols' },
          h('div', { className: 'wb-card' },
            h('h3', null, '需要什么才能开'),
            data.requirements.map((item, index) => h('div', { className: 'wb-row', key: index },
              h('i', { className: 'wb-dot', 'data-tone': 'warn' }),
              h('div', null, h('b', null, item))))),
          h('div', { className: 'wb-card' },
            h('h3', null, '现在已有的资产'),
            inventory)),
        data.note ? h('div', { className: 'wb-note' }, data.note) : null)
    }

    function Body({ data, onOpen }) {
      if (data === null) return h('div', { className: 'wb-loading' }, '读取视图…')
      if (data.kind === 'overview') return h(Overview, { data })
      if (data.kind === 'control') return h(Control, { data, onOpen })
      if (data.kind === 'table') return h(TableView, { data })
      if (data.kind === 'matrix') return h(MatrixView, { data })
      if (data.kind === 'governance') return h(GovernanceView, { data })
      return h(UnavailableView, { data })
    }

    function Drawer({ project, onClose, onChanged, notify }) {
      const [busy, setBusy] = useState(false)
      const [confirming, setConfirming] = useState(null)
      const [error, setError] = useState(null)
      const [log, setLog] = useState(null)

      useEffect(() => { setConfirming(null); setError(null); setLog(null) }, [project.id])

      const loadLog = async () => {
        try {
          const payload = await api(`/projects/${project.id}/log?lines=60`)
          setLog(payload.text === '' ? '（还没有日志：尚未启动过）' : payload.text)
        } catch (failure) {
          setLog(`日志读取失败：${failure.message}`)
        }
      }

      const act = async action => {
        setBusy(true)
        setError(null)
        try {
          const result = await api(`/projects/${project.id}/${action}`, {
            method: 'POST',
            body: JSON.stringify({ confirm: true, intent: '工作台面板手动操作', actor: 'web' }),
          })
          notify(result.ok ? `${project.name} 已${action === 'start' ? '启动' : '停止'}` : `操作失败：${result.error}`)
          setConfirming(null)
          onChanged()
        } catch (failure) {
          setError(failure.payload?.hint ?? failure.message)
        } finally {
          setBusy(false)
        }
      }

      const copyPrompt = async () => {
        const text = `【项目】${project.name}（${project.id}）\n【状态】${project.label} · 健康分 ${project.health.total}\n【诉求】`
        try {
          await navigator.clipboard.writeText(text)
          notify('已复制会话开场语')
        } catch {
          notify('浏览器拒绝剪贴板权限，请手动选择文本')
        }
      }

      const parts = project.health.parts
      const rows = [
        ['负责人', project.owner],
        ['健康分', `${project.health.total}（可用性 ${parts.availability}/40 · 成功率 ${parts.success}/30 · 时延 ${parts.latency}/20 · 新鲜度 ${parts.freshness}/10）`],
        ['入口', project.url === null ? '无（任务/视图形态）' : project.url],
        ['依赖', project.depends.length > 0 ? project.depends.join('、') : '无'],
        ['前置', project.ready ? '已就绪' : `缺少 ${project.missing.join('、')}`],
        ['说明', project.description || '—'],
      ]
      if (project.error) rows.push(['当前异常', project.error])
      if (project.foreign) rows.push(['注意', '端口已被非工作台进程占用：停止不会影响它，启动会因端口冲突失败；要托管请先腾出端口或改 project.yaml 的 port。'])

      const kv = []
      for (const [key, value] of rows) {
        kv.push(h('dt', { key: `${key}-k` }, key))
        kv.push(h('dd', {
          key: `${key}-v`,
          style: key === '当前异常' ? { color: 'var(--wb-risk)' } : undefined,
        }, value))
      }

      const logs = project.runs !== undefined && project.runs.length > 0
        ? project.runs.map(run => `${String(run.at).slice(5, 19).replace('T', ' ')}  ${run.ok ? '成功' : '失败'}  ${run.error ?? `${run.durationMs ?? 0}ms`}`).join('\n')
        : '无运行记录'

      const actions = [
        h('button', {
          key: 'start',
          className: 'wb-btn',
          'data-tone': 'primary',
          disabled: busy || project.form !== 'service' || !project.ready,
          onClick: () => setConfirming('start'),
        }, project.state === 'running' ? '重新启动' : '启动'),
        h('button', {
          key: 'stop',
          className: 'wb-btn',
          'data-tone': 'danger',
          disabled: busy || project.form !== 'service' || project.state !== 'running',
          onClick: () => setConfirming('stop'),
        }, '停止'),
        project.url === null
          ? null
          : h('button', { key: 'open', className: 'wb-btn', onClick: () => window.open(project.url, '_blank', 'noopener') }, '打开界面'),
        h('button', { key: 'prompt', className: 'wb-btn', onClick: copyPrompt }, '生成会话开场语'),
        h('button', { key: 'log', className: 'wb-btn', onClick: loadLog }, '启动日志'),
      ]

      const confirmBox = h('div', { className: 'wb-confirm' },
        h('b', null, confirming === 'start' ? `确认启动 ${project.name}？` : `确认停止 ${project.name}？`),
        h('div', null, confirming === 'start'
          ? `将占用端口 ${project.port ?? '—'}，持续运行直到手动停止；启动失败会记录审计。`
          : '将中断该服务的在线访问，进行中的请求会失败；pid 记录随之清理。'),
        error === null ? null : h('div', { style: { color: 'var(--wb-risk)', marginTop: 8 } }, error),
        h('div', { className: 'wb-actions' },
          h('button', {
            className: 'wb-btn',
            'data-tone': 'primary',
            disabled: busy,
            onClick: () => act(confirming),
          }, busy ? '执行中…' : '确认执行'),
          h('button', { className: 'wb-btn', disabled: busy, onClick: () => setConfirming(null) }, '取消')))

      return h('div', { className: 'wb-drawer' },
        h('div', { className: 'wb-drawer-head' },
          h('div', { style: { flex: 1 } },
            h('div', { style: { fontWeight: 600 } }, project.name),
            h('div', { className: 'wb-sub' }, `${project.id} · ${project.form} · ${project.domain}`)),
          h(Chip, { tone: toneOfState(project.state) }, project.label),
          project.foreign ? h(Chip, { tone: 'warn' }, '外部进程') : null,
          h('button', { className: 'wb-btn', onClick: onClose }, '关闭')),
        h('div', { className: 'wb-drawer-body' },
          h('dl', { className: 'wb-kv' }, kv),
          h('div', { className: 'wb-sec' }, '最近运行'),
          h('div', { className: 'wb-log' }, logs),
          confirming === null
            ? h('div', { style: { display: 'flex', gap: 8, marginTop: 16, flexWrap: 'wrap' } }, actions)
            : confirmBox,
          log === null
            ? null
            : h('div', { style: { marginTop: 14 } },
              h('div', { className: 'wb-sec' }, '启动日志'),
              h('div', { className: 'wb-log', style: { maxHeight: 220 } }, log))))
    }

    function Workbench() {
      const [boot, setBoot] = useState(null)
      const [active, setActive] = useState('today')
      const [data, setData] = useState(null)
      const [error, setError] = useState(null)
      const [drawerId, setDrawerId] = useState(null)
      const [toast, setToast] = useState(null)
      const timer = useRef(null)

      const notify = useCallback(message => {
        setToast(message)
        window.clearTimeout(timer.current)
        timer.current = window.setTimeout(() => setToast(null), 2400)
      }, [])

      const loadBoot = useCallback(async () => {
        try {
          const payload = await api('/bootstrap')
          setBoot(payload)
          setError(null)
        } catch (failure) {
          setError(`工作台接口不可用：${failure.message}`)
        }
      }, [])

      const loadView = useCallback(async (id, silent = false) => {
        if (!silent) setData(null)
        try {
          const payload = await api(`/views/${id}`)
          setData(payload.data)
          setError(null)
        } catch (failure) {
          setError(`视图 ${id} 读取失败：${failure.message}`)
        }
      }, [])

      useEffect(() => { loadBoot() }, [loadBoot])
      useEffect(() => { loadView(active) }, [active, loadView])

      // 控制室自己会走：20s 静默刷新一次状态，切到后台就停（零模型调用）
      useEffect(() => {
        const timerId = window.setInterval(() => {
          if (document.visibilityState !== 'visible') return
          loadBoot()
          loadView(active, true)
        }, 20_000)
        return () => window.clearInterval(timerId)
      }, [active, loadBoot, loadView])

      const drawer = useMemo(() => {
        if (boot === null || drawerId === null) return null
        return boot.projects.find(project => project.id === drawerId) ?? null
      }, [boot, drawerId])

      const refresh = useCallback(async () => {
        await loadBoot()
        await loadView(active)
        notify('已刷新')
      }, [active, loadBoot, loadView, notify])

      if (boot === null) {
        return h('div', { className: 'wb-root' },
          h('style', null, CSS),
          h('div', { className: 'wb-loading' }, error ?? '工作台启动中…'))
      }

      const spec = boot.views.find(view => view.id === active) ?? boot.views[0]
      const failedChip = boot.summary.failed > 0
        ? h(Chip, { tone: 'risk' }, `失败 ${boot.summary.failed}`)
        : h(Chip, { tone: 'ok' }, '无失败')

      return h('div', { className: 'wb-root' },
        h('style', null, CSS),
        h('div', { className: 'wb-top' },
          h('div', null,
            h('div', { className: 'wb-title' }, '项目控制室'),
            h('div', { className: 'wb-sub' }, `联邦 · ${boot.summary.total} 个项目 · 运行中 ${boot.summary.running} · 待安装 ${boot.summary.notReady}`)),
          h('span', { className: 'wb-spacer' }),
          failedChip,
          h('button', { className: 'wb-btn', onClick: refresh }, '刷新')),
        h('div', { className: 'wb-body' },
          h(Nav, { views: boot.views, active, onPick: id => { setDrawerId(null); setActive(id) } }),
          h('main', { className: 'wb-main' },
            h('div', { className: 'wb-head' },
              h('h1', { className: 'wb-h1' }, spec.title),
              h('div', { className: 'wb-ask' }, spec.question)),
            error === null
              ? null
              : h('div', { className: 'wb-card', style: { padding: 14, marginBottom: 12, color: 'var(--wb-risk)' } }, error),
            h(Body, { data, onOpen: setDrawerId }),
            h('div', { className: 'wb-note' },
              `健康分 ${boot.policy.formula} · 数据源：项目本地库与文件系统 · 生成于 ${new Date(boot.generatedAt).toLocaleTimeString('zh-CN', { hour12: false })}`))),
        drawer === null
          ? null
          : h(Drawer, {
            project: drawer,
            onClose: () => setDrawerId(null),
            onChanged: async () => { await loadBoot(); await loadView(active) },
            notify,
          }),
        toast === null ? null : h('div', { className: 'wb-toast' }, toast))
    }

    function WorkbenchIcon({ size = 16 }) {
      const stroke = 'currentColor'
      return h('svg', { width: size, height: size, viewBox: '0 0 16 16', fill: 'none', 'aria-hidden': true },
        h('rect', { x: 1.5, y: 1.5, width: 5, height: 5, rx: 1.2, stroke, strokeWidth: 1.2 }),
        h('rect', { x: 9.5, y: 1.5, width: 5, height: 5, rx: 1.2, stroke, strokeWidth: 1.2 }),
        h('rect', { x: 1.5, y: 9.5, width: 5, height: 5, rx: 1.2, stroke, strokeWidth: 1.2 }),
        h('path', { d: 'M9.5 12h5M12 9.5v5', stroke, strokeWidth: 1.2, strokeLinecap: 'round' }))
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        ctx.slots.inject('main', () => ctx.slots.register({ name: 'main', key: 'workbench' }, Workbench))
        ctx.slots.inject('sidebar.panellist', () => ctx.slots.register({
          name: 'sidebar.panellist', id: 'workbench', order: 5, label: '工作台',
        }, WorkbenchIcon))
      },
    }
  },
})
