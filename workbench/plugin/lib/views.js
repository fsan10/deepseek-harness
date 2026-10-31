/**
 * 视图包数据解析：每个视图只回答一个问题，页面不做二次计算。
 *
 * 数据来源：项目自己落盘的真实文件/本地库，或工作台本地业务库（var/workbench.db）。
 * 没有来源的指标一律返回「未接入」并列出所需契约，绝不填演示数字。
 * 带写操作的页面返回 kind='ops'：表单与行内动作都由 Host 的 /action 接口执行。
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

/** 递归统计目录里的文件与最近修改时间。 */
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

function table(columns, rows, extra = {}) {
  return { kind: 'table', columns, rows, ...extra }
}

function bytes(size) {
  if (!Number.isFinite(size)) return '—'
  if (size > 1024 * 1024) return `${(size / 1048576).toFixed(1)} MB`
  return `${Math.round(size / 1024)} KB`
}

const PLATFORMS = ['抖音', '天猫', '京东', '拼多多', '快手', '小红书', '视频号', '天猫超市', '千川', '银行']

// ── 各页面 ─────────────────────────────────────────────────────────────────

const resolvers = {
  /** 今日：我现在该动哪一件事？ */
  today(ctx) {
    const total = ctx.projects.length
    const online = ctx.projects.filter(p => ctx.states[p.id]?.state === 'running').length
    const abnormal = ctx.projects.filter(p => ['degraded', 'failed'].includes(ctx.states[p.id]?.state))
    const liveRuns = query(LIVEOPS_DB(ctx.root),
      "select kind,status,started_at,message from collection_runs where status<>'success' order by started_at desc limit 20")
    const grouped = new Map()
    for (const run of liveRuns.rows) {
      const key = `${run.kind}|${run.message ?? ''}`
      const existing = grouped.get(key)
      if (existing === undefined) grouped.set(key, { ...run, count: 1 })
      else existing.count += 1
    }
    const negatives = scalar(KEFU_DB(ctx.root),
      "select count(*) from negative_reviews where review_date >= date('now','-3 day')")
    const pending = ctx.store.get("select count(*) c from fund_adjustments where status='待复核'").c
    const batches = ctx.store.get("select count(*) c from ingest_batches where status='待登记'").c

    const todos = []
    for (const project of abnormal) {
      todos.push({
        tone: 'risk',
        text: `${project.name} · ${ctx.states[project.id].label}`,
        meta: ctx.states[project.id].error ?? `健康分 ${ctx.states[project.id].health.total}`,
        target: project.id,
      })
    }
    for (const run of [...grouped.values()].slice(0, 2)) {
      todos.push({
        tone: 'warn',
        text: `直播运营 · ${run.kind} 采集失败${run.count > 1 ? ` ×${run.count}` : ''}`,
        meta: `${relTime(run.started_at)} · ${String(run.message ?? '').slice(0, 42)}`,
        target: 'liveops',
      })
    }
    if (negatives.value) {
      todos.push({ tone: 'warn', text: `客服中心 · 近 3 天 ${negatives.value} 条中差评待跟进`, meta: 'kefu.negative_reviews', target: 'kefu' })
    }
    if (pending > 0) {
      todos.push({ tone: 'warn', text: `资金拆分 · ${pending} 张调整单待复核`, meta: '本地库 fund_adjustments', target: 'funds' })
    }
    if (batches > 0) {
      todos.push({ tone: 'muted', text: `文件接入 · ${batches} 个批次待登记`, meta: 'coffice-core/data 真实文件', target: 'ingest' })
    }
    if (todos.length === 0) todos.push({ tone: 'ok', text: '没有异常，按计划推进即可', meta: '所有探测点正常' })

    const running = ctx.projects
      .filter(p => ctx.states[p.id]?.state === 'running')
      .map(p => ({
        text: p.name,
        meta: `${p.form === 'view' ? '视图投影' : `端口 ${p.port ?? '—'}`} · 健康分 ${ctx.states[p.id].health.total}${p.foreign ? ' · 外部进程' : ''}`,
        tone: 'ok',
      }))

    const freshness = ctx.freshnessHours
    return {
      kind: 'overview',
      kpis: [
        { label: '项目在线', value: `${online}/${total}`, hint: '含视图投影，不含待运行任务', tone: online === total ? 'ok' : 'warn' },
        { label: '待处理', value: String(todos.filter(t => t.tone !== 'ok').length), hint: '异常 / 采集失败 / 待复核 / 待登记', tone: todos.some(t => t.tone === 'risk') ? 'risk' : 'warn' },
        { label: '数据新鲜度', value: freshness === null ? '无数据' : `${Math.round(freshness)}h`, hint: '工作台可读数据文件的最新修改距现在', tone: freshness !== null && freshness < 48 ? 'ok' : 'warn' },
      ],
      lists: [
        { title: '需要你处理', rows: todos },
        { title: '今天在跑', rows: running.length ? running : [{ text: '暂无运行中的服务', meta: '可在项目矩阵里启动', tone: 'muted' }] },
      ],
      note: '首页只有一个主导区域：待办清单。每条都能点进对应的项目或页面。',
      generatedAt: nowIso(),
    }
  },

  /** 公司整体：本地镜像里的跨源经营视图。 */
  overview(ctx) {
    const board = ctx.store.overview()
    const companies = board.companies.slice(0, 8)
    return {
      kind: 'overview',
      kpis: [
        { label: '直播成交额（镜像）', value: money(board.gmv) ?? '¥0', hint: `${board.totals.rows ?? 0} 行指标 · 截至 ${board.totals.latest ?? '—'}`, tone: 'ok' },
        { label: '覆盖店铺', value: String(board.totals.shops ?? 0), hint: `${board.totals.companies ?? 0} 家公司有归属`, tone: 'ok' },
        { label: '待处理单据', value: String((board.funds.total ?? 0)), hint: `资金调整待复核 ${board.funds.total ?? 0} 张 · 批次待登记 ${board.batches.registered ?? 0}`, tone: (board.funds.total ?? 0) > 0 ? 'warn' : 'ok' },
      ],
      lists: [
        {
          title: '按公司（直播成交额）',
          rows: companies.map(row => ({
            text: row.company,
            meta: `${row.shops} 家店 · ${row.rows} 行指标 · 成交 ${money(row.gmv) ?? '¥0'}`,
            tone: row.company === '（未归属）' ? 'warn' : 'ok',
          })),
        },
        {
          title: '数据来源',
          rows: board.bySource.map(row => ({
            text: row.source === 'kefu' ? '客服中心（指标采集）' : row.source === 'liveops' ? '直播运营（场次）' : row.source,
            meta: `${row.rows} 行 · ${row.shops} 家店`,
            tone: 'ok',
          })),
        },
      ],
      note: '全部来自工作台本地镜像（var/workbench.db），由「自动化流程」同步；不读生产库。',
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
    const owned = new Set(ctx.store.all('select shop_name from dim_shop_company').map(r => r.shop_name))

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
          owned.has(shop.name) ? 2 : 1,
        ],
        meta: reviews ? `${reviews.c} 条差评 · ${reviews.d}` : '无差评记录',
      }
    })
    return {
      kind: 'matrix',
      columns: [
        { key: 'reception', label: '接待' },
        { key: 'score', label: '评分' },
        { key: 'reviews', label: '差评' },
        { key: 'live', label: '直播' },
        { key: 'company', label: '公司归属' },
      ],
      legend: [
        { value: 2, label: '已具备' },
        { value: 1, label: '缺失/有问题' },
        { value: 0, label: '未启用' },
        { value: null, label: '未接入' },
      ],
      rows,
      summary: {
        shops: shops.rows.length,
        platforms: new Set(shops.rows.map(s => s.platform)).size,
        reception: shops.rows.filter(s => s.reception_enabled).length,
        score: shops.rows.filter(s => s.score_enabled).length,
        live: liveSet.size,
      },
      note: '第五列改成「公司归属」：现在能直接看到哪家店还没落 DIM（去「公司与店铺」补）。',
      generatedAt: nowIso(),
    }
  },

  /** 资金与结算：仍未接入，但把契约和现有资产摆出来。 */
  finance(ctx) {
    const base = COFFICE(ctx.root)
    const ads = scanDir(join(base, 'sql/ads'))
    const platforms = listDirs(join(base, 'sql')).filter(name => !['ads', 'ai', 'bank', 'common', 'dim'].includes(name))
    return {
      kind: 'unavailable',
      reason: '资金口径在 ADS 层，工作台不连生产库，因此不显示任何金额。资金调整请到「资金拆分」页操作（本地库，可复核）。',
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

  /** 商品中心：差评里暴露的商品问题。 */
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
        name: r.product_name, platform: r.platform, count: r.c, date: r.d,
        level: r.c >= 3 ? '集中爆发' : '零散',
      })),
      {
        kpis: [{ label: '商品编码覆盖', value: coded.value ?? '—', hint: '差评明细中带 product_code 的比例' }],
        note: 'SKU 主档仍在 coffice 共享能力层；这里先看「差评聚集到哪些商品」。',
        generatedAt: nowIso(),
      },
    )
  },

  /** 履约与售后：物流体验指标。 */
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
        note: '售后工单目前没有系统承载：本页只覆盖物流履约指标。',
        generatedAt: nowIso(),
      },
    )
  },

  /** 客服中心：直接进原系统，页面顶部只放三个数。 */
  kefu(ctx) {
    const db = KEFU_DB(ctx.root)
    const project = ctx.projects.find(p => p.id === 'kefu')
    const state = ctx.states.kefu
    const shops = scalar(db, 'select count(*) from shops')
    const reviews = scalar(db, 'select count(*) from negative_reviews')
    const runs = query(db, 'select status, count(*) c from metric_runs group by status')
    const ok = runs.rows.find(r => r.status === 'success')?.c ?? 0
    const total = runs.rows.reduce((sum, r) => sum + r.c, 0)
    return {
      kind: 'app',
      title: '客服中心（原系统）',
      projectId: 'kefu',
      url: project?.url ?? null,
      running: state?.state === 'running',
      kpis: [
        { label: '店铺', value: String(shops.value ?? 0), hint: 'kefu.shops' },
        { label: '差评', value: String(reviews.value ?? 0), hint: 'negative_reviews' },
        { label: '采集成功率', value: total ? `${Math.round((ok / total) * 100)}%` : '—', hint: `${total} 次 metric_runs` },
      ],
      note: '下面是 kefu 本体（未改动），导入、采集、评价、指标都在里面操作；工作台只做外层与统计。',
      generatedAt: nowIso(),
    }
  },

  /** 直播运营：直接进原系统。 */
  liveops(ctx) {
    const db = LIVEOPS_DB(ctx.root)
    const project = ctx.projects.find(p => p.id === 'liveops')
    const state = ctx.states.liveops
    const shifts = scalar(db, 'select count(*) from shift_schedules')
    const reports = scalar(db, 'select count(*) from shift_reports')
    const runs = query(db, "select status, count(*) c from collection_runs group by status")
    const failed = runs.rows.find(r => r.status === 'failed')?.c ?? 0
    const total = runs.rows.reduce((sum, r) => sum + r.c, 0)
    return {
      kind: 'app',
      title: '直播运营（原系统）',
      projectId: 'liveops',
      url: project?.url ?? null,
      running: state?.state === 'running',
      kpis: [
        { label: '排班', value: String(shifts.value ?? 0), hint: 'shift_schedules' },
        { label: '场次报表', value: String(reports.value ?? 0), hint: 'shift_reports' },
        { label: '采集失败', value: `${failed}/${total}`, hint: 'collection_runs', tone: failed > 0 ? 'warn' : 'ok' },
      ],
      note: '下面是 liveops 本体（未改动），排班、采集、截图、飞书配置都在里面操作。',
      generatedAt: nowIso(),
    }
  },

  /** 文件接入：真实文件 → 批次登记 → 入库状态。 */
  ingest(ctx) {
    const rows = ctx.store.all('select * from ingest_batches order by created_at desc, file_path limit 60')
    const total = ctx.store.get('select count(*) c from ingest_batches').c
    const pending = ctx.store.get("select count(*) c from ingest_batches where status='待登记'").c
    const registered = ctx.store.get("select count(*) c from ingest_batches where status='已登记'").c
    return {
      kind: 'ops',
      kpis: [
        { label: '文件总数', value: String(total), hint: 'coffice-core/data 下真实文件' },
        { label: '待登记', value: String(pending), hint: '还没建批次' },
        { label: '已登记', value: String(registered), hint: '批次已建立' },
      ],
      forms: [],
      toolbar: [{ id: 'scan', label: '扫描新文件', action: 'ingest.scan', level: 'L1' }],
      columns: [
        { key: 'file_name', label: '文件', width: '34%' },
        { key: 'platform', label: '平台', width: '10%' },
        { key: 'company', label: '公司', width: '18%' },
        { key: 'shop_name', label: '店铺', width: '14%' },
        { key: 'size', label: '大小', align: 'right', width: '9%' },
        { key: 'rows', label: '行数', align: 'right', width: '7%' },
        { key: 'status', label: '状态', width: '8%' },
      ],
      rows: rows.map(row => ({
        id: row.id,
        file_name: row.file_name,
        platform: row.platform,
        company: row.company ?? '未识别',
        shop_name: row.shop_name ?? '未识别',
        size: bytes(row.file_size),
        rows: row.rows === null ? '—' : row.rows,
        status: row.status,
      })),
      rowActions: [
        { id: 'register', label: '登记', action: 'ingest.register', level: 'L1', payloadKey: 'id' },
        { id: 'loaded', label: '标记入库', action: 'ingest.mark', level: 'L1', payloadKey: 'id' },
      ],
      note: '登记只写本地库（var/workbench.db），不碰 ODS、不碰生产库。行数只对 CSV 实数；xlsx 留空不猜。',
      generatedAt: nowIso(),
    }
  },

  /** 自动化流程：真跑同步，写运行记录。 */
  automation(ctx) {
    const flows = ctx.store.flowBoard()
    const runs = ctx.store.all('select * from flow_runs order by finished_at desc limit 12')
    return {
      kind: 'ops',
      kpis: [
        { label: '流程', value: String(flows.length), hint: '内置三条，可新建' },
        { label: '最近成功', value: String(runs.filter(r => r.status === 'success').length), hint: '最近 12 次' },
        { label: '最近失败', value: String(runs.filter(r => r.status === 'failed').length), hint: '最近 12 次', tone: runs.some(r => r.status === 'failed') ? 'warn' : 'ok' },
      ],
      forms: [{
        id: 'flow-create',
        title: '新建流程',
        action: 'flow.create',
        level: 'L2',
        submitLabel: '创建',
        fields: [
          { key: 'name', label: '流程名', type: 'text', required: true, placeholder: '例如 每日客服指标同步' },
          {
            key: 'kind', label: '类型', type: 'select', required: true,
            options: [
              { value: 'sync-kefu', label: '客服指标 → 本地镜像' },
              { value: 'sync-liveops', label: '直播场次 → 本地镜像' },
              { value: 'sync-dim', label: '公司归属（从差评反推）' },
            ],
          },
        ],
      }],
      columns: [
        { key: 'name', label: '流程', width: '26%' },
        { key: 'kind', label: '类型', width: '22%' },
        { key: 'last', label: '最近运行', width: '26%' },
        { key: 'result', label: '结果', width: '26%' },
      ],
      rows: flows.map(flow => ({
        id: flow.id,
        name: flow.name + (flow.enabled ? '' : '（已停用）'),
        kind: flow.kind,
        last: flow.last_at ? relTime(flow.last_at) : '未运行',
        result: flow.last_status ? `${flow.last_status === 'success' ? '成功' : '失败'} · ${flow.last_rows ?? 0} 行 · ${flow.last_message ?? ''}` : '—',
      })),
      rowActions: [{ id: 'run', label: '立即运行', action: 'flow.run', level: 'L2', payloadKey: 'id' }],
      lists: [{
        title: '最近运行记录',
        rows: runs.map(run => ({
          text: `${run.flow_name} · ${run.status === 'success' ? '成功' : '失败'} · ${run.rows} 行`,
          meta: `${relTime(run.finished_at)} · ${run.message ?? ''} · by ${run.actor}`,
          tone: run.status === 'success' ? 'ok' : 'risk',
        })),
      }],
      note: '三条内置流程都是真实现：读 kefu/liveops 的库写本地镜像。运行属 L2，需确认。',
      generatedAt: nowIso(),
    }
  },

  /** 达人主数据：可新增/编辑/停用。 */
  influencers(ctx) {
    const rows = ctx.store.all('select * from influencers order by status, name')
    const active = rows.filter(r => r.status === '在职').length
    return {
      kind: 'ops',
      kpis: [
        { label: '达人', value: String(rows.length), hint: '本地主数据' },
        { label: '在职', value: String(active), hint: '可参与排班' },
        { label: '缺佣金率', value: String(rows.filter(r => r.commission_rate === null).length), hint: '需要补', tone: 'warn' },
      ],
      forms: [{
        id: 'influencer-create',
        title: '新增达人',
        action: 'influencer.upsert',
        level: 'L2',
        submitLabel: '保存',
        fields: [
          { key: 'name', label: '姓名', type: 'text', required: true },
          { key: 'platform', label: '平台', type: 'select', options: PLATFORMS.map(p => ({ value: p, label: p })) },
          { key: 'shop_name', label: '所属店铺', type: 'text' },
          { key: 'commission_rate', label: '佣金率(%)', type: 'number', placeholder: '例如 12.5' },
        ],
      }],
      columns: [
        { key: 'name', label: '姓名', width: '20%' },
        { key: 'platform', label: '平台', width: '12%' },
        { key: 'shop_name', label: '店铺', width: '26%' },
        { key: 'commission_rate', label: '佣金率', align: 'right', width: '12%' },
        { key: 'status', label: '状态', width: '12%' },
        { key: 'updated_at', label: '更新', width: '18%' },
      ],
      rows: rows.map(row => ({
        id: row.id,
        name: row.name,
        platform: row.platform ?? '—',
        shop_name: row.shop_name ?? '—',
        commission_rate: row.commission_rate === null ? '—' : `${row.commission_rate}%`,
        status: row.status,
        updated_at: relTime(row.updated_at),
      })),
      rowActions: [{ id: 'offboard', label: '停用', action: 'influencer.disable', level: 'L2', payloadKey: 'id' }],
      note: '初始名单来自直播运营的真实排班主播；佣金率需要在本地补齐。',
      generatedAt: nowIso(),
    }
  },

  /** 资金拆分调整：新建 → 待复核 → 复核/驳回。 */
  funds(ctx) {
    const rows = ctx.store.all('select * from fund_adjustments order by created_at desc limit 40')
    const pending = rows.filter(r => r.status === '待复核')
    const amount = ctx.store.get("select coalesce(sum(amount),0) s from fund_adjustments where status='待复核'").s
    return {
      kind: 'ops',
      kpis: [
        { label: '待复核', value: String(pending.length), hint: '张调整单' },
        { label: '待复核金额', value: money(amount) ?? '¥0', hint: '合计' },
        { label: '已处理', value: String(rows.length - pending.length), hint: '复核或驳回' },
      ],
      forms: [{
        id: 'fund-create',
        title: '新建调整单',
        action: 'fund.adjust',
        level: 'L2',
        submitLabel: '提交复核',
        fields: [
          { key: 'platform', label: '平台', type: 'select', options: PLATFORMS.map(p => ({ value: p, label: p })) },
          { key: 'shop_name', label: '店铺', type: 'text', required: true },
          { key: 'amount', label: '调整金额', type: 'number', required: true, placeholder: '负数表示冲减' },
          { key: 'reason', label: '原因', type: 'text', required: true, placeholder: '例如 9 月小红书结算差异' },
        ],
      }],
      columns: [
        { key: 'shop_name', label: '店铺', width: '20%' },
        { key: 'platform', label: '平台', width: '10%' },
        { key: 'amount', label: '金额', align: 'right', width: '12%' },
        { key: 'reason', label: '原因', width: '30%' },
        { key: 'status', label: '状态', width: '10%' },
        { key: 'created_at', label: '创建', width: '18%' },
      ],
      rows: rows.map(row => ({
        id: row.id,
        shop_name: row.shop_name ?? '—',
        platform: row.platform ?? '—',
        amount: `¥${Number(row.amount).toFixed(2)}`,
        reason: row.reason,
        status: row.status,
        created_at: relTime(row.created_at),
      })),
      rowActions: [
        { id: 'approve', label: '复核', action: 'fund.approve', level: 'L3', payloadKey: 'id' },
        { id: 'reject', label: '驳回', action: 'fund.reject', level: 'L2', payloadKey: 'id' },
      ],
      note: '复核（L3）不由 AI 执行，只能人工点；驳回是 L2。全部写本地库并留审计。',
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

  /** 数据与连接：资产与最近证据。 */
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
        name, kind: '平台适配器', assets: `${stat.files} 个文件`,
        latest: stat.latest ? relTime(new Date(stat.latest).toISOString()) : '—',
        status: '文件就绪 · 鉴权态需 auth status',
      }
    })
    for (const module of liveModules.rows) {
      rows.push({
        name: module.name, kind: '采集模块', assets: module.code, latest: '—',
        status: module.enabled ? '已启用' : '已停用',
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
      rows.slice(0, 30).map(r => ({ name: r.name, kind: r.kind, assets: r.assets, latest: r.latest, status: r.status })),
      {
        kpis: [
          { label: '平台适配器', value: String(platforms.length), hint: 'commerce_api/platforms' },
          { label: '采集脚本', value: String(countFiles(pwDir, '.py')), hint: 'scripts/auto_download/playwright' },
          { label: '客服 Profile', value: String(kefuProfiles.value ?? 0), hint: 'kefu.metric_profiles' },
        ],
        note: '字段映射覆盖率、QPS 限流属于运行时事实，首版不猜。',
        generatedAt: nowIso(),
      },
    )
  },

  /** 调度运行：三个项目 + 工作台流程的运行记录。 */
  runs(ctx) {
    const items = []
    for (const project of ctx.projects) {
      const state = ctx.states[project.id]
      for (const run of state?.runs ?? []) {
        items.push({
          at: run.at, source: project.name,
          task: run.action === 'runtime' ? '启停' : run.action,
          status: run.ok ? '成功' : '失败',
          message: run.error ?? `${run.durationMs ?? 0}ms`,
        })
      }
    }
    for (const row of ctx.store.all('select * from flow_runs order by finished_at desc limit 10')) {
      items.push({
        at: row.finished_at, source: '工作台流程', task: row.flow_name,
        status: row.status, message: `${row.rows} 行 · ${row.message}`,
      })
    }
    for (const row of query(LIVEOPS_DB(ctx.root), 'select kind,status,started_at,message from collection_runs order by started_at desc limit 15').rows) {
      items.push({ at: row.started_at, source: '直播运营', task: row.kind, status: row.status, message: row.message })
    }
    for (const row of query(KEFU_DB(ctx.root), "select '指标采集' task,status,created_at at,collected_count c from metric_runs order by created_at desc limit 8").rows) {
      items.push({ at: row.at, source: '客服中心', task: row.task, status: row.status, message: `采集 ${row.c} 条` })
    }
    items.sort((a, b) => String(b.at).localeCompare(String(a.at)))
    return table(
      [
        { key: 'at', label: '时间', width: '20%' },
        { key: 'source', label: '来源', width: '16%' },
        { key: 'task', label: '任务', width: '18%' },
        { key: 'status', label: '状态', width: '12%' },
        { key: 'message', label: '说明', width: '34%' },
      ],
      items.slice(0, 40).map(item => ({
        at: String(item.at).replace('T', ' ').slice(0, 19),
        source: item.source, task: item.task, status: item.status, message: item.message ?? '—',
      })),
      { kpis: [], note: '重试沿用原批次，不新建；本页只做投影。', generatedAt: nowIso() },
    )
  },

  /** 公司与店铺：可补 DIM 归属。 */
  companies(ctx) {
    const rows = ctx.store.shopOwnership()
    const mapped = rows.filter(r => r.company !== null)
    const companies = [...new Set(mapped.map(r => r.company))]
    return {
      kind: 'ops',
      kpis: [
        { label: '店铺', value: String(rows.length), hint: 'kefu.shops 全量' },
        { label: '已归属', value: String(mapped.length), hint: '本地 DIM' },
        { label: '未归属', value: String(rows.length - mapped.length), hint: '补齐后可做公司级分析', tone: 'warn' },
      ],
      forms: [{
        id: 'company-map',
        title: '补公司归属',
        action: 'company.map',
        level: 'L2',
        submitLabel: '保存归属',
        fields: [
          {
            key: 'shop_name', label: '店铺', type: 'select', required: true,
            options: rows.map(row => ({ value: row.shop_name, label: `${row.shop_name}（${row.platform ?? '—'}）` })),
          },
          { key: 'platform', label: '平台', type: 'text', placeholder: '与店铺的平台一致' },
          { key: 'company', label: '公司', type: 'text', required: true, placeholder: '营业执照主体全名' },
        ],
      }],
      columns: [
        { key: 'shop_name', label: '店铺', width: '34%' },
        { key: 'platform', label: '平台', width: '14%' },
        { key: 'company', label: '公司', width: '38%' },
        { key: 'state', label: '状态', width: '14%' },
      ],
      rows: rows.map(row => ({
        id: `${row.shop_name}|${row.platform ?? ''}`,
        shop_name: row.shop_name,
        platform: row.platform ?? '—',
        company: row.company ?? '未归属',
        state: row.company ? '已归属' : '待补',
      })),
      summary: { companies: companies.length, mapped: mapped.length, total: rows.length },
      note: '归属只写本地 DIM（dim_shop_company），不碰 coffice 的 dim 表；补完会同步刷新镜像里的 company。',
      generatedAt: nowIso(),
    }
  },

  /** 人员与权限。 */
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
      note: '授权范围写「公司 · 模块」；L3 红线由财务与法务确认后写入 policies/redlines.md。',
      generatedAt: nowIso(),
    }
  },
}

/**
 * 计算一个视图的数据。
 * @param {string} id 视图 id。
 * @param {object} ctx 工作台上下文（projects/states/root/store/roles/auditTail）。
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
