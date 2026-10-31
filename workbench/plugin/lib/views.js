/**
 * 视图包数据解析：每个视图只回答一个问题，页面不做二次计算。
 *
 * 数据来源只有两种：项目自己落盘的真实文件/本地库，或 dsh 运行时状态。
 * 没有来源的指标一律返回「未接入」并列出所需契约，绝不填演示数字。
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join, extname } from 'node:path'
import { query, scalar } from './db.js'

const KEFU_DB = root => join(root, 'projects/kefu/data/kefu.sqlite')
const LIVEOPS_DB = root => join(root, 'projects/liveops/var/liveops.sqlite3')
const COFFICE = root => join(root, 'projects/coffice-core')

function nowIso() { return new Date().toISOString() }

function relTime(iso) {
  if (!iso) return '—'
  const ms = Date.parse(String(iso).replace(' ', 'T'))
  if (Number.isNaN(ms)) return String(iso)
  const diff = Date.now() - ms
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.round(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.round(diff / 3_600_000)} 小时前`
  return `${Math.round(diff / 86_400_000)} 天前`
}

function money(value) {
  const n = Number(value)
  if (!Number.isFinite(n) || n === 0) return null
  if (Math.abs(n) >= 10_000) return `¥${(n / 10_000).toFixed(1)} 万`
  return `¥${n.toFixed(0)}`
}

/** 递归统计目录里的文件与最近修改时间（工作台用它做「资产清单」）。 */
function scanDir(dir, maxDepth = 3) {
  const out = { files: 0, bytes: 0, latest: 0, byExt: {} }
  const walk = (current, depth) => {
    if (depth > maxDepth || !existsSync(current)) return
    let entries
    try { entries = readdirSync(current, { withFileTypes: true }) } catch { return }
    for (const entry of entries) {
      if (entry.name.startsWith('.') || entry.name === '__pycache__' || entry.name === 'node_modules') continue
      const full = join(current, entry.name)
      if (entry.isDirectory()) { walk(full, depth + 1); continue }
      try {
        const stat = statSync(full)
        out.files++
        out.bytes += stat.size
        if (stat.mtimeMs > out.latest) out.latest = stat.mtimeMs
        const ext = extname(entry.name).toLowerCase() || '(无)'
        out.byExt[ext] = (out.byExt[ext] ?? 0) + 1
      } catch { /* 单文件失败不影响清单 */ }
    }
  }
  walk(dir, 0)
  return out
}

function listDirs(dir) {
  try {
    return readdirSync(dir, { withFileTypes: true })
      .filter(entry => entry.isDirectory() && !entry.name.startsWith('.') && entry.name !== '__pycache__')
      .map(entry => entry.name)
  } catch { return [] }
}

function countFiles(dir, suffix) {
  try {
    return readdirSync(dir, { withFileTypes: true })
      .filter(e => e.isFile() && e.name.endsWith(suffix)).length
  } catch { return 0 }
}

/** 统一表格结果。 */
function table(columns, rows, extra = {}) {
  return { kind: 'table', columns, rows, ...extra }
}

// ── 各页面 ─────────────────────────────────────────────────────────────────

const resolvers = {
  /** 今日：我现在该动哪一件事？ */
  today(ctx) {
    const rows = Object.values(ctx.states)
    const total = ctx.projects.length
    const online = ctx.projects.filter(p => ctx.states[p.id]?.state === 'running').length
    const abnormal = ctx.projects.filter(p => ['degraded', 'failed'].includes(ctx.states[p.id]?.state))
    const liveRuns = query(LIVEOPS_DB(ctx.root),
      "select kind,status,started_at,message from collection_runs where status<>'success' order by started_at desc limit 20")
    // 同一类失败合并成一条，避免「5 条一模一样的报错」淹没真正的异常
    const grouped = new Map()
    for (const run of liveRuns.rows) {
      const key = `${run.kind}|${run.message ?? ''}`
      const existing = grouped.get(key)
      if (existing === undefined) grouped.set(key, { ...run, count: 1 })
      else existing.count += 1
    }
    const negatives = scalar(KEFU_DB(ctx.root),
      "select count(*) from negative_reviews where review_date >= date('now','-3 day')")

    const todos = []
    for (const project of abnormal) {
      todos.push({
        tone: 'risk',
        text: `${project.name} · ${ctx.states[project.id].label}`,
        meta: ctx.states[project.id].error ?? `健康分 ${ctx.states[project.id].health.total}`,
        target: project.id,
      })
    }
    for (const run of [...grouped.values()].slice(0, 3)) {
      todos.push({
        tone: 'warn',
        text: `直播运营 · ${run.kind} 采集失败${run.count > 1 ? ` ×${run.count}` : ''}`,
        meta: `${relTime(run.started_at)} · ${String(run.message ?? '').slice(0, 42)}`,
        target: 'liveops',
      })
    }
    if (negatives.value) {
      todos.push({
        tone: 'warn',
        text: `客服中心 · 近 3 天 ${negatives.value} 条中差评待跟进`,
        meta: '来自 kefu 本地库 negative_reviews',
        target: 'kefu',
      })
    }
    if (todos.length === 0) todos.push({ tone: 'ok', text: '没有异常，按计划推进即可', meta: '所有探测点正常' })

    const running = ctx.projects
      .filter(p => ctx.states[p.id]?.state === 'running')
      .map(p => ({ text: p.name, meta: `${p.form === 'view' ? '视图投影' : `端口 ${p.port ?? '—'}`} · 健康分 ${ctx.states[p.id].health.total}`, tone: 'ok' }))

    const freshness = ctx.freshnessHours
    return {
      kind: 'overview',
      kpis: [
        { label: '项目在线', value: `${online}/${total}`, hint: '含视图投影，不含待运行任务', tone: online === total ? 'ok' : 'warn' },
        { label: '待处理异常', value: String(todos.filter(t => t.tone !== 'ok').length), hint: '降级/失败/采集失败', tone: todos.some(t => t.tone === 'risk') ? 'risk' : 'warn' },
        { label: '数据新鲜度', value: freshness === null ? '无数据' : `${Math.round(freshness)}h`, hint: '工作台可读数据文件的最新修改距现在', tone: freshness !== null && freshness < 48 ? 'ok' : 'warn' },
      ],
      lists: [
        { title: '需要你处理', rows: todos },
        { title: '今天在跑', rows: running.length ? running : [{ text: '暂无运行中的服务', meta: '可在项目矩阵里启动', tone: 'muted' }] },
      ],
      note: '首页只有一个主导区域：待办清单。KPI 只放三个数，不放趋势图。',
      generatedAt: nowIso(),
    }
  },

  /** 项目矩阵：哪个项目、哪条公共能力在掉链子？ */
  projects(ctx) {
    const groups = []
    for (const form of ['service', 'job', 'mcp', 'view']) {
      const rows = ctx.projects.filter(p => p.form === form).map(project => {
        const state = ctx.states[project.id]
        return {
          id: project.id,
          name: project.name,
          owner: project.owner,
          domain: project.domain,
          state: state?.state ?? 'idle',
          label: state?.label ?? '待运行',
          health: state?.health.total ?? 0,
          parts: state?.health.parts ?? {},
          successRate: state?.health.successRate ?? null,
          latencyMs: state?.latencyMs ?? null,
          freshness: state?.health.freshness ?? '—',
          uptimeFrom: state?.since ?? null,
          url: project.url,
          port: project.port,
          error: state?.error ?? null,
          lastRun: state?.lastRun ?? null,
          problems: project.problems,
          depends: project.depends,
          split: project.split,
          levels: project.levels,
        }
      })
      groups.push({ form, rows })
    }
    return {
      kind: 'control',
      groups,
      summary: {
        total: ctx.projects.length,
        running: ctx.projects.filter(p => ctx.states[p.id]?.state === 'running').length,
        degraded: ctx.projects.filter(p => ctx.states[p.id]?.state === 'degraded').length,
        failed: ctx.projects.filter(p => ctx.states[p.id]?.state === 'failed').length,
      },
      note: '启停属 L2：点开项目看影响面，确认后执行并留审计；已停止不代表故障。',
      generatedAt: nowIso(),
    }
  },

  /** 店铺全景：哪家公司、哪个平台、哪项能力缺？ */
  shops(ctx) {
    const db = KEFU_DB(ctx.root)
    const shops = query(db, 'select id,name,platform,kind,score_enabled,reception_enabled from shops order by platform,name')
    const reviewCounts = query(db, "select shop_name, count(*) c, max(review_date) d from negative_reviews group by shop_name")
    const reviewMap = new Map(reviewCounts.rows.map(r => [r.shop_name, r]))
    const liveShops = query(LIVEOPS_DB(ctx.root), 'select distinct shop_name from shift_reports')
    const liveSet = new Set(liveShops.rows.map(r => r.shop_name))

    const rows = shops.rows.map(shop => {
      const reviews = reviewMap.get(shop.name)
      return {
        label: shop.name,
        sub: shop.platform,
        cells: [
          shop.reception_enabled ? 2 : 0,
          shop.score_enabled ? 2 : 0,
          reviews ? (reviews.c > 3 ? 1 : 2) : 0,
          liveSet.has(shop.name) ? 2 : 0,
          null,
        ],
        meta: reviews ? `${reviews.c} 条差评 · ${reviews.d}` : '无差评记录',
      }
    })
    const platforms = [...new Set(shops.rows.map(s => s.platform))]
    return {
      kind: 'matrix',
      columns: [
        { key: 'reception', label: '接待' },
        { key: 'score', label: '评分' },
        { key: 'reviews', label: '差评' },
        { key: 'live', label: '直播' },
        { key: 'settle', label: '结算' },
      ],
      legend: [
        { value: 2, label: '已启用' },
        { value: 1, label: '有问题' },
        { value: 0, label: '未启用' },
        { value: null, label: '未接入' },
      ],
      rows,
      summary: {
        shops: shops.rows.length,
        platforms: platforms.length,
        reception: shops.rows.filter(s => s.reception_enabled).length,
        score: shops.rows.filter(s => s.score_enabled).length,
        live: liveSet.size,
      },
      note: '五个圆点一屏回答「哪项能力缺」。结算列未接入：需要 ADS 资金表契约。',
      generatedAt: nowIso(),
    }
  },

  /** 经营总览：钱在哪个店、哪个环节卡住？ */
  overview(ctx) {
    const db = KEFU_DB(ctx.root)
    const latest = scalar(db, 'select max(report_date) d from daily_records')
    const shops = scalar(db, 'select count(*) from shops')
    const metrics = query(db, 'select m.name, m.category, m.unit, count(*) rows, max(d.report_date) d from daily_records d join metrics m on m.id=d.metric_id group by m.id order by rows desc limit 8')
    const reviews = query(db, "select platform, count(*) c from negative_reviews group by platform order by c desc")
    return {
      kind: 'overview',
      kpis: [
        { label: '店铺数', value: String(shops.value ?? 0), hint: 'kefu.shops', tone: 'ok' },
        { label: '数据截止', value: latest.value ?? '—', hint: 'kefu.daily_records 最新日期', tone: 'ok' },
        { label: '采集指标', value: String(metrics.rows.length ? metrics.rows[0].rows : 0), hint: '最近可见指标行数（样本）', tone: 'muted' },
      ],
      lists: [
        {
          title: '指标覆盖（按采集行数）',
          rows: metrics.rows.map(r => ({ text: `${r.name}`, meta: `${r.category} · ${r.rows} 行 · 截至 ${r.d}`, tone: 'ok' })),
        },
        {
          title: '差评平台分布',
          rows: reviews.rows.map(r => ({ text: r.platform, meta: `${r.c} 条`, tone: 'warn' })),
        },
      ],
      note: '成交/净收/毛利需要 ADS 指标表；本轮只展示客服域已落库的真实口径。',
      generatedAt: nowIso(),
    }
  },

  /** 资金与结算：未接入，但把契约和现有资产摆出来。 */
  finance(ctx) {
    const base = COFFICE(ctx.root)
    const ads = scanDir(join(base, 'sql/ads'))
    const platforms = listDirs(join(base, 'sql')).filter(name => !['ads', 'ai', 'bank', 'common', 'dim'].includes(name))
    return {
      kind: 'unavailable',
      reason: '资金口径在 ADS 层，工作台首版不连生产库（只读也不连），因此不显示任何金额。',
      requirements: [
        'ADS 视图契约：平台 / 账期 / 已到账 / 待结算 / 差异金额 / 差异原因',
        '7 平台账期表（T+1 / T+7 / T+15 由财务确认）',
        '差异定义：结算表与资金表的对账口径，需与月度核验脚本一致',
      ],
      inventory: [
        { name: 'ADS 脚本', meta: `${ads.files} 个文件 · 最近更新 ${ads.latest ? relTime(new Date(ads.latest).toISOString()) : '—'}` },
        ...platforms.map(p => ({ name: `sql/${p}`, meta: `${scanDir(join(base, 'sql', p), 1).files} 个对象` })),
      ],
      note: '未接入不是缺陷：宁可空着，也不让业务把示例数字当经营结果。',
      generatedAt: nowIso(),
    }
  },

  /** 门店与人效：线下没有 ODS 来源。 */
  storeops() {
    return {
      kind: 'unavailable',
      reason: '门店销售来自 POS 导出、用工成本来自考勤/薪酬表，两条线都还没进 ODS，本轮不画金额与人效。',
      requirements: [
        'POS 日销明细：门店 / 日期 / 销售额 / 客单数',
        '考勤或排班工时：门店 / 日期 / 在岗人数 / 工时',
        '人效口径确认：当日销售 ÷ 当日在岗人数（含兼职折算规则）',
      ],
      inventory: [],
      note: '版式与项目矩阵同构：左表 + 底部三张成本/排班/人效卡，数据到位即可开。',
      generatedAt: nowIso(),
    }
  },

  /** 商品中心：差评里暴露的商品问题最真实。 */
  products(ctx) {
    const db = KEFU_DB(ctx.root)
    const rows = query(db, `select product_name, platform, count(*) c, max(review_date) d
      from negative_reviews where product_name is not null and product_name<>''
      group by product_name, platform order by c desc limit 20`)
    const coded = scalar(db, "select sum(case when product_code is not null and product_code<>'' then 1 else 0 end)||'/'||count(*) from negative_reviews")
    return table(
      [
        { key: 'name', label: '商品', width: '38%' },
        { key: 'platform', label: '平台', width: '14%' },
        { key: 'count', label: '差评数', align: 'right', width: '12%' },
        { key: 'date', label: '最近', width: '18%' },
        { key: 'level', label: '信号', width: '18%' },
      ],
      rows.rows.map(r => ({
        name: r.product_name,
        platform: r.platform,
        count: r.c,
        date: r.d,
        level: r.c >= 3 ? '集中爆发' : '零散',
      })),
      {
        kpis: [{ label: '商品编码覆盖', value: coded.value ?? '—', hint: '差评明细中带 product_code 的比例' }],
        note: 'SKU 主档仍在 coffice 共享能力层；这里先看「差评聚集到哪些商品」。',
        generatedAt: nowIso(),
      },
    )
  },

  /** 履约与售后：物流体验指标 + 售后系统缺口。 */
  fulfillment(ctx) {
    const db = KEFU_DB(ctx.root)
    const rows = query(db, `select m.name, m.unit, round(avg(d.numeric_value),2) v, max(d.report_date) d, count(*) n
      from daily_records d join metrics m on m.id=d.metric_id
      where m.category='物流体验' group by m.id order by n desc limit 12`)
    return table(
      [
        { key: 'name', label: '指标', width: '40%' },
        { key: 'value', label: '均值/最新', align: 'right', width: '16%' },
        { key: 'unit', label: '单位', width: '10%' },
        { key: 'date', label: '截止日期', width: '18%' },
        { key: 'rows', label: '样本', align: 'right', width: '16%' },
      ],
      rows.rows.map(r => ({ name: r.name, value: r.v, unit: r.unit, date: r.d, rows: r.n })),
      {
        kpis: [],
        note: '售后工单目前没有系统承载：本页只覆盖物流履约指标，「退款/换货/补发」需要新建工单域。',
        generatedAt: nowIso(),
      },
    )
  },

  /** 客服中心：门户只放指标与差评派单，会话工作台仍在 kefu。 */
  kefu(ctx) {
    const db = KEFU_DB(ctx.root)
    const rows = query(db, `select s.name, s.platform, s.reception_enabled, s.score_enabled,
        (select count(*) from negative_reviews r where r.shop_name=s.name) rev,
        (select max(r.review_date) from negative_reviews r where r.shop_name=s.name) last_rev
      from shops s order by rev desc, s.name limit 30`)
    const runs = query(db, 'select status, count(*) c from metric_runs group by status')
    const ok = runs.rows.find(r => r.status === 'success')?.c ?? 0
    const total = runs.rows.reduce((sum, r) => sum + r.c, 0)
    return table(
      [
        { key: 'name', label: '店铺', width: '34%' },
        { key: 'platform', label: '平台', width: '12%' },
        { key: 'reception', label: '接待', width: '10%' },
        { key: 'score', label: '评分', width: '10%' },
        { key: 'reviews', label: '差评', align: 'right', width: '12%' },
        { key: 'last', label: '最近差评', width: '22%' },
      ],
      rows.rows.map(r => ({
        name: r.name, platform: r.platform,
        reception: r.reception_enabled ? '开' : '关',
        score: r.score_enabled ? '开' : '关',
        reviews: r.rev, last: r.last_rev ?? '—',
      })),
      {
        kpis: [
          { label: '店铺', value: String(scalar(db, 'select count(*) from shops').value ?? 0), hint: 'kefu.shops 全量' },
          { label: '指标采集成功率', value: total ? `${Math.round((ok / total) * 100)}%` : '—', hint: `最近 ${total} 次 metric_runs` },
          { label: '差评总量', value: String(scalar(db, 'select count(*) from negative_reviews').value ?? 0), hint: 'negative_reviews' },
        ],
        note: '会话工作台仍在 kefu（进入项目即打开原系统）；门户只做指标与派单。',
        generatedAt: nowIso(),
      },
    )
  },

  /** 内容与达人：主播排班与场次数据。 */
  content(ctx) {
    const db = LIVEOPS_DB(ctx.root)
    const rows = query(db, `select host_name, count(*) shifts, max(work_date) last_date,
        sum(case when enabled=1 then 1 else 0 end) enabled
      from shift_schedules where host_name is not null group by host_name order by shifts desc limit 20`)
    const reports = query(db, `select host_name, count(*) c, max(work_date) d from shift_reports where host_name is not null group by host_name`)
    const reportMap = new Map(reports.rows.map(r => [r.host_name, r]))
    const shots = scalar(db, "select count(*) from screenshot_requests where status='done'")
    return table(
      [
        { key: 'name', label: '主播', width: '24%' },
        { key: 'shifts', label: '排班', align: 'right', width: '12%' },
        { key: 'enabled', label: '启用', align: 'right', width: '12%' },
        { key: 'reports', label: '已出报表', align: 'right', width: '16%' },
        { key: 'last', label: '最近场次', width: '22%' },
        { key: 'tone', label: '状态', width: '14%' },
      ],
      rows.rows.map(r => {
        const report = reportMap.get(r.host_name)
        return {
          name: r.host_name, shifts: r.shifts, enabled: r.enabled,
          reports: report?.c ?? 0, last: report?.d ?? r.last_date,
          tone: report ? '正常' : '只有排班',
        }
      }),
      {
        kpis: [
          { label: '主播', value: String(rows.rows.length), hint: 'liveops.shift_schedules' },
          { label: '已完成截图', value: String(shots.value ?? 0), hint: 'screenshot_requests.status=done' },
        ],
        note: '达人与内容素材仍分散在 coffice.influencer_config 与直播运营截图，后续按能力包归并。',
        generatedAt: nowIso(),
      },
    )
  },

  /** 数据与连接：只看资产与最近证据，不假装知道线上鉴权态。 */
  connectors(ctx) {
    const base = COFFICE(ctx.root)
    const platforms = listDirs(join(base, 'commerce_api/platforms')).filter(n => n !== '__pycache__')
    const pwDir = join(base, 'scripts/auto_download/playwright')
    const kefuProfiles = scalar(KEFU_DB(ctx.root), 'select count(*) from metric_profiles')
    const liveModules = query(LIVEOPS_DB(ctx.root), 'select code,name,enabled from collector_modules')
    const rows = platforms.map(name => {
      const dir = join(base, 'commerce_api/platforms', name)
      const stat = scanDir(dir, 2)
      return {
        name,
        kind: '平台适配器',
        assets: `${stat.files} 个文件`,
        latest: stat.latest ? relTime(new Date(stat.latest).toISOString()) : '—',
        status: '文件就绪',
        note: '鉴权态需运行 auth status 才有证据',
      }
    })
    for (const module of liveModules.rows) {
      rows.push({
        name: module.name,
        kind: '采集模块',
        assets: module.code,
        latest: '—',
        status: module.enabled ? '已启用' : '已停用',
        note: 'liveops.collector_modules',
      })
    }
    return table(
      [
        { key: 'name', label: '连接器', width: '30%' },
        { key: 'kind', label: '形态', width: '14%' },
        { key: 'assets', label: '资产', width: '18%' },
        { key: 'latest', label: '最近更新', width: '14%' },
        { key: 'status', label: '状态', width: '24%' },
      ],
      rows.slice(0, 30).map(r => ({ name: r.name, kind: r.kind, assets: r.assets, latest: r.latest, status: `${r.status} · ${r.note}` })),
      {
        kpis: [
          { label: '平台适配器', value: String(platforms.length), hint: 'commerce_api/platforms' },
          { label: '采集脚本', value: String(countFiles(pwDir, '.py')), hint: 'scripts/auto_download/playwright' },
          { label: '客服 Profile', value: String(kefuProfiles.value ?? 0), hint: 'kefu.metric_profiles' },
        ],
        note: '字段映射覆盖率、QPS 限流属于运行时事实，首版不猜；运行 auth status 后再补。',
        generatedAt: nowIso(),
      },
    )
  },

  /** 调度运行：三个项目各自的运行记录合并成一条时间线。 */
  runs(ctx) {
    const items = []
    for (const project of ctx.projects) {
      const state = ctx.states[project.id]
      for (const run of state?.runs ?? []) {
        items.push({
          at: run.at,
          source: project.name,
          task: run.action === 'runtime' ? '启停' : run.action,
          status: run.ok ? '成功' : '失败',
          message: run.error ?? `${run.durationMs ?? 0}ms`,
        })
      }
    }
    for (const row of query(LIVEOPS_DB(ctx.root), 'select kind,status,started_at,message from collection_runs order by started_at desc limit 20').rows) {
      items.push({ at: row.started_at, source: '直播运营', task: row.kind, status: row.status, message: row.message })
    }
    for (const row of query(KEFU_DB(ctx.root), 'select \'指标采集\' task,status,created_at at,collected_count c from metric_runs order by created_at desc limit 10').rows) {
      items.push({ at: row.at, source: '客服中心', task: row.task, status: row.status, message: `采集 ${row.c} 条` })
    }
    for (const row of query(KEFU_DB(ctx.root), 'select \'差评采集\' task,status,created_at at,collected_count c from review_runs order by created_at desc limit 10').rows) {
      items.push({ at: row.at, source: '客服中心', task: row.task, status: row.status, message: `采集 ${row.c} 条` })
    }
    items.sort((a, b) => String(b.at).localeCompare(String(a.at)))
    return table(
      [
        { key: 'at', label: '时间', width: '20%' },
        { key: 'source', label: '来源项目', width: '16%' },
        { key: 'task', label: '任务', width: '18%' },
        { key: 'status', label: '状态', width: '12%' },
        { key: 'message', label: '说明', width: '34%' },
      ],
      items.slice(0, 40).map(item => ({
        at: String(item.at).replace('T', ' ').slice(0, 19),
        source: item.source,
        task: item.task,
        status: item.status,
        message: item.message ?? '—',
      })),
      {
        kpis: [],
        note: '重试沿用原 Run，不新建批次；本页只做投影，不重算状态。',
        generatedAt: nowIso(),
      },
    )
  },

  /** 公司与店铺：公司→店铺→账号的结构，缺口直接暴露。 */
  companies(ctx) {
    const db = KEFU_DB(ctx.root)
    const companies = query(db, `select coalesce(company,'（未标注公司）') company, count(distinct shop_name) shops, count(*) reviews
      from negative_reviews group by company order by shops desc`)
    const shops = query(db, 'select platform, count(*) c from shops group by platform order by c desc')
    const mapped = scalar(db, "select count(distinct shop_name) from negative_reviews where company is not null and company<>''")
    const totalShops = scalar(db, 'select count(*) from shops')
    return {
      kind: 'governance',
      groups: companies.rows.map(row => ({
        label: row.company,
        sub: `${row.shops} 家店铺有差评记录 · ${row.reviews} 条`,
        rows: shops.rows.map(s => ({
          label: s.platform,
          meta: `${s.c} 家店铺`,
          tone: 'muted',
        })),
      })),
      summary: {
        companies: companies.rows.length,
        mapped: mapped.value ?? 0,
        totalShops: totalShops.value ?? 0,
      },
      note: `56 家店铺里只有 ${mapped.value ?? 0} 家能从差评明细反推公司归属；DIM（平台+店铺+公司）仍需补全。`,
      generatedAt: nowIso(),
    }
  },

  /** 人员与权限：读策略文件 + 真实审计流水。 */
  access(ctx) {
    const roles = ctx.roles
    const recent = ctx.auditTail(12)
    return {
      kind: 'governance',
      groups: roles.map(role => ({
        label: role.name,
        sub: `${role.scope} · 最高 ${role.maxLevel}`,
        rows: role.abilities.map(a => ({ label: a, meta: '允许', tone: 'ok' })),
      })),
      summary: { roles: roles.length, events: recent.length },
      recent,
      note: '授权范围写「公司 · 模块」，不写权限点串；L3 红线由财务与法务确认后写入 policies/redlines.md。',
      generatedAt: nowIso(),
    }
  },
}

/**
 * 计算一个视图的数据。
 * @param {string} id 视图 id。
 * @param {object} ctx 工作台上下文（projects/states/root/roles/auditTail）。
 * @returns {object} 视图数据（含 kind）。
 */
export function computeView(id, ctx) {
  const resolver = resolvers[id]
  if (resolver === undefined) {
    return { kind: 'unavailable', reason: `未知视图：${id}`, requirements: [], inventory: [], generatedAt: nowIso() }
  }
  try {
    return resolver(ctx)
  } catch (error) {
    return {
      kind: 'unavailable',
      reason: `视图计算失败：${String(error && error.message ? error.message : error)}`,
      requirements: [],
      inventory: [],
      generatedAt: nowIso(),
    }
  }
}
