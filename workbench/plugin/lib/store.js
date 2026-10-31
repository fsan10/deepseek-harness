/**
 * 工作台本地业务库：coffice 的业务数据只落在 var/workbench.db，不碰生产 PG。
 *
 * 原则：
 *  - 只读别人的库（kefu / liveops 的 sqlite），只写自己的库。
 *  - 所有写动作都是「一条动作 = 一次审计」的粒度，便于 AI 与人共用同一通道。
 *  - 同步流程是真跑：把 kefu/liveops 的数据抽到本地镜像，返回真实行数。
 */
import { DatabaseSync } from 'node:sqlite'
import { existsSync, mkdirSync, readdirSync, statSync, readFileSync } from 'node:fs'
import { join, relative, basename, extname } from 'node:path'

const SCHEMA = `
CREATE TABLE IF NOT EXISTS ingest_batches(
  id TEXT PRIMARY KEY, platform TEXT, company TEXT, shop_name TEXT,
  file_path TEXT, file_name TEXT, file_size INTEGER, rows INTEGER,
  status TEXT, note TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS flows(
  id TEXT PRIMARY KEY, name TEXT, kind TEXT, enabled INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS flow_runs(
  id TEXT PRIMARY KEY, flow_id TEXT, flow_name TEXT, status TEXT, rows INTEGER,
  message TEXT, started_at TEXT, finished_at TEXT, actor TEXT);
CREATE TABLE IF NOT EXISTS influencers(
  id TEXT PRIMARY KEY, name TEXT, platform TEXT, shop_name TEXT,
  commission_rate REAL, status TEXT, note TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS fund_adjustments(
  id TEXT PRIMARY KEY, platform TEXT, shop_name TEXT, amount REAL,
  reason TEXT, status TEXT, batch_id TEXT, created_at TEXT, actor TEXT);
CREATE TABLE IF NOT EXISTS dim_shop_company(
  shop_name TEXT, platform TEXT, company TEXT, updated_at TEXT,
  PRIMARY KEY(shop_name, platform));
CREATE TABLE IF NOT EXISTS metrics_daily(
  report_date TEXT, company TEXT, shop_name TEXT, platform TEXT,
  metric TEXT, value REAL, unit TEXT, source TEXT,
  PRIMARY KEY(report_date, shop_name, metric, source));
CREATE INDEX IF NOT EXISTS idx_metrics_day ON metrics_daily(report_date);
CREATE INDEX IF NOT EXISTS idx_metrics_company ON metrics_daily(company);
`

/** 允许 AI 查询的表（只读白名单）。 */
export const READABLE_TABLES = [
  'ingest_batches', 'flows', 'flow_runs', 'influencers',
  'fund_adjustments', 'dim_shop_company', 'metrics_daily',
]

/** 内置流程：都是真实现的同步动作，不是占位。 */
const BUILTIN_FLOWS = [
  { id: 'sync-kefu', name: '客服指标同步', kind: 'sync-kefu' },
  { id: 'sync-liveops', name: '直播场次同步', kind: 'sync-liveops' },
  { id: 'sync-dim', name: '公司归属补全', kind: 'sync-dim' },
]

function nowIso() { return new Date().toISOString() }
function uid(prefix) { return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}` }

/** 由文本派生稳定 id：同一个文件重复扫描不会重复建批次。 */
function hashId(prefix, text) {
  let hash = 5381
  for (let i = 0; i < text.length; i++) hash = ((hash * 33) ^ text.charCodeAt(i)) >>> 0
  return `${prefix}-${hash.toString(36)}`
}

/** 从文件名里猜公司/店铺（京东_墨客咖时（南京）生物科技有限公司_MOCK饮品旗舰店_结算_001.csv）。 */
function parseName(fileName) {
  const stem = basename(fileName, extname(fileName))
  const parts = stem.split(/[_-]/).map(part => part.trim()).filter(Boolean)
  const company = parts.find(part => part.includes('公司')) ?? null
  const shop = parts.find(part => part.includes('店') && part !== company) ?? null
  return { company, shop }
}

export class Store {
  /**
   * @param {{root: string, varDir: string}} options 工作台根与运行目录。
   */
  constructor(options) {
    this.root = options.root
    this.varDir = options.varDir
    mkdirSync(this.varDir, { recursive: true })
    this.file = join(this.varDir, 'workbench.db')
    this.db = new DatabaseSync(this.file)
    this.db.exec('PRAGMA journal_mode = WAL;')
    this.db.exec(SCHEMA)
    this.migrateIngestIds()
    this.seeded = this.seed()
  }

  // ── 基础 ────────────────────────────────────────────────────────────────
  all(sql, params = []) { return this.db.prepare(sql).all(...params) }
  get(sql, params = []) { return this.db.prepare(sql).get(...params) ?? null }
  run(sql, params = []) { return this.db.prepare(sql).run(...params) }

  kefuDb() { return join(this.root, 'projects/kefu/data/kefu.sqlite') }
  liveopsDb() { return join(this.root, 'projects/liveops/var/liveops.sqlite3') }
  cofficeData() { return join(this.root, 'projects/coffice-core/data') }

  /** 只读别人的库：挂载为 ATTACH 后立即 DETACH，避免长期占用。 */
  readOther(file, sql, params = []) {
    if (!existsSync(file)) return []
    try {
      this.db.exec(`ATTACH DATABASE '${file.replace(/'/g, "''")}' AS ext`)
      try { return this.db.prepare(sql).all(...params) } finally { this.db.exec('DETACH DATABASE ext') }
    } catch {
      return []
    }
  }

  // ── 首次播种 ────────────────────────────────────────────────────────────
  seed() {
    const report = {}
    const batchCount = this.get('SELECT count(*) c FROM ingest_batches').c
    if (batchCount === 0) report.ingest = this.seedIngest()
    if (this.get('SELECT count(*) c FROM dim_shop_company').c === 0) report.dim = this.syncDim()
    if (this.get('SELECT count(*) c FROM metrics_daily').c === 0) {
      report.kefu = this.syncKefu()
      report.liveops = this.syncLiveops()
    }
    if (this.get('SELECT count(*) c FROM flows').c === 0) {
      for (const flow of BUILTIN_FLOWS) {
        this.run('INSERT INTO flows(id,name,kind,enabled,created_at) VALUES(?,?,?,?,?)',
          [flow.id, flow.name, flow.kind, 1, nowIso()])
      }
      report.flows = BUILTIN_FLOWS.length
    }
    if (this.get('SELECT count(*) c FROM influencers').c === 0) report.influencers = this.seedInfluencers()
    return report
  }

  /**
   * 一次性迁移：早期版本用随机 id 建批次，重复扫描会重复插入。
   * 这里重建为按 file_path 派生的稳定 id，并把用户已设置的登记状态按路径带回来。
   */
  migrateIngestIds() {
    const rows = this.all('select id, file_path, status from ingest_batches')
    if (rows.length === 0) return
    if (rows.every(row => row.id === hashId('ing', row.file_path))) return
    const status = new Map(rows.map(row => [row.file_path, row.status]))
    this.run('delete from ingest_batches')
    this.seedIngest()
    for (const [filePath, value] of status) {
      if (value !== '待登记') {
        this.run('update ingest_batches set status=? where file_path=?', [value, filePath])
      }
    }
  }

  /** 把 coffice-core/data 下的真实文件登记成「待登记批次」。 */
  seedIngest() {    const base = this.cofficeData()
    if (!existsSync(base)) return 0
    let count = 0
    const walk = (dir, depth) => {
      if (depth > 2) return
      let entries = []
      try { entries = readdirSync(dir, { withFileTypes: true }) } catch { return }
      for (const entry of entries) {
        const full = join(dir, entry.name)
        if (entry.isDirectory()) { walk(full, depth + 1); continue }
        const ext = extname(entry.name).toLowerCase()
        if (!['.xlsx', '.xls', '.csv'].includes(ext)) continue
        const rel = relative(base, full).split('\\')
        const platform = rel[0]
        const { company, shop } = parseName(entry.name)
        let size = 0
        let rows = null
        try {
          size = statSync(full).size
          if (ext === '.csv') {
            const text = readFileSync(full, 'utf8')
            rows = Math.max(0, text.split('\n').filter(line => line.trim() !== '').length - 1)
          }
        } catch { /* 单文件失败不影响登记 */ }
        this.run(`INSERT OR IGNORE INTO ingest_batches
          (id,platform,company,shop_name,file_path,file_name,file_size,rows,status,note,created_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?)`,
        [hashId('ing', relative(base, full)), platform, company, shop, relative(base, full), entry.name, size, rows, '待登记', '来自 coffice-core/data', nowIso()])
        count++
      }
    }
    walk(base, 0)
    return count
  }

  /** 公司归属：从 kefu 差评明细反推（这是当前唯一有公司字段的真实来源）。 */
  syncDim() {
    const rows = this.readOther(this.kefuDb(),
      "select distinct company, shop_name, platform from negative_reviews where company is not null and company<>''")
    let n = 0
    for (const row of rows) {
      this.run('INSERT OR REPLACE INTO dim_shop_company(shop_name,platform,company,updated_at) VALUES(?,?,?,?)',
        [row.shop_name, row.platform, row.company, nowIso()])
      n++
    }
    return n
  }

  /** 客服指标 → 本地镜像。 */
  syncKefu() {
    const rows = this.readOther(this.kefuDb(), `
      select d.report_date, s.name shop_name, s.platform, m.name metric, m.unit, d.numeric_value value
      from daily_records d
      join shops s on s.id = d.shop_id
      join metrics m on m.id = d.metric_id
      where d.numeric_value is not null`)
    const dim = new Map(this.all('select shop_name, company from dim_shop_company').map(r => [r.shop_name, r.company]))
    let n = 0
    this.db.exec('BEGIN')
    try {
      for (const row of rows) {
        this.run(`INSERT OR REPLACE INTO metrics_daily
          (report_date,company,shop_name,platform,metric,value,unit,source) VALUES(?,?,?,?,?,?,?,?)`,
        [row.report_date, dim.get(row.shop_name) ?? null, row.shop_name, row.platform, row.metric, row.value, row.unit, 'kefu'])
        n++
      }
      this.db.exec('COMMIT')
    } catch (error) {
      this.db.exec('ROLLBACK')
      throw error
    }
    return n
  }

  /** 直播场次 GMV → 本地镜像（metrics_json 里取 gmv）。 */
  syncLiveops() {
    const rows = this.readOther(this.liveopsDb(),
      'select work_date, host_name, shop_name, metrics_json from shift_reports where metrics_json is not null')
    const dim = new Map(this.all('select shop_name, company from dim_shop_company').map(r => [r.shop_name, r.company]))
    let n = 0
    this.db.exec('BEGIN')
    try {
      for (const row of rows) {
        let metrics = null
        try { metrics = JSON.parse(row.metrics_json) } catch { continue }
        const gmv = Number(metrics?.gmv)
        if (!Number.isFinite(gmv)) continue
        this.run(`INSERT OR REPLACE INTO metrics_daily
          (report_date,company,shop_name,platform,metric,value,unit,source) VALUES(?,?,?,?,?,?,?,?)`,
        [row.work_date, dim.get(row.shop_name) ?? null, row.shop_name, '抖音', '直播成交额', gmv, '元', 'liveops'])
        n++
      }
      this.db.exec('COMMIT')
    } catch (error) {
      this.db.exec('ROLLBACK')
      throw error
    }
    return n
  }

  /** 达人主数据：先用直播运营的真实主播建档。 */
  seedInfluencers() {
    const rows = this.readOther(this.liveopsDb(),
      'select distinct host_name, shop_name from shift_schedules where host_name is not null')
    let n = 0
    for (const row of rows) {
      this.run('INSERT OR IGNORE INTO influencers(id,name,platform,shop_name,commission_rate,status,note,updated_at) VALUES(?,?,?,?,?,?,?,?)',
        [uid('inf'), row.host_name, '抖音', row.shop_name ?? null, null, '在职', '来自直播运营排班', nowIso()])
      n++
    }
    return n
  }

  // ── 读 ──────────────────────────────────────────────────────────────────
  /** 概览：跨源聚合，全部来自本地镜像。 */
  overview() {
    const totals = this.get(`select
      count(distinct shop_name) shops,
      count(distinct company) companies,
      count(*) rows,
      max(report_date) latest
      from metrics_daily`) ?? {}
    const bySource = this.all("select source, count(*) rows, count(distinct shop_name) shops from metrics_daily group by source")
    const gmv = this.get("select sum(value) total from metrics_daily where metric='直播成交额'")?.total ?? 0
    const companies = this.all(`select coalesce(company,'（未归属）') company, count(distinct shop_name) shops,
        count(*) rows, round(sum(case when metric='直播成交额' then value else 0 end),2) gmv
      from metrics_daily group by company order by gmv desc, shops desc`)
    const batches = this.get("select count(*) total, sum(case when status='已登记' then 1 else 0 end) registered from ingest_batches") ?? {}
    const funds = this.get("select count(*) total, round(sum(amount),2) amount from fund_adjustments where status='待复核'") ?? {}
    return { totals, bySource, gmv, companies, batches, funds }
  }

  /** 公司级分析：给 AI 用的结构化结果。 */
  analysis(days = 30) {
    const since = new Date(Date.now() - days * 86400_000).toISOString().slice(0, 10)
    const rows = this.all(`select company, shop_name, platform, metric, sum(value) total, count(*) n, max(report_date) latest
      from metrics_daily where report_date >= ? group by company, shop_name, platform, metric`, [since])
    const byCompany = new Map()
    for (const row of rows) {
      const key = row.company ?? '（未归属）'
      const bucket = byCompany.get(key) ?? { company: key, shops: new Set(), metrics: {}, rows: 0, latest: '' }
      bucket.shops.add(row.shop_name)
      bucket.metrics[row.metric] = (bucket.metrics[row.metric] ?? 0) + (row.total ?? 0)
      bucket.rows += row.n
      if (row.latest > bucket.latest) bucket.latest = row.latest
      byCompany.set(key, bucket)
    }
    const coverage = this.all(`select source, metric, count(*) n, max(report_date) latest from metrics_daily group by source, metric order by n desc`)
    return {
      window: { days, since },
      companies: [...byCompany.values()].map(item => ({
        company: item.company,
        shops: item.shops.size,
        rows: item.rows,
        latest: item.latest,
        metrics: item.metrics,
      })),
      coverage,
      totals: this.overview().totals,
    }
  }

  /**
   * AI 只读查询：只允许 SELECT，且只能碰白名单表。
   * @param {string} sql SQL 文本。
   */
  query(sql) {
    const text = String(sql ?? '').trim().replace(/;+\s*$/, '')
    if (!/^select\s/i.test(text)) throw new Error('只允许 SELECT')
    if (/;/.test(text)) throw new Error('一次只允许一条语句')
    if (/\b(attach|detach|pragma|insert|update|delete|drop|alter|create|replace)\b/i.test(text)) {
      throw new Error('只读查询不允许包含写操作或 PRAGMA')
    }
    const mentioned = [...text.matchAll(/\bfrom\s+([a-z_][a-z0-9_]*)/gi)].map(m => m[1].toLowerCase())
    for (const name of mentioned) {
      if (!READABLE_TABLES.includes(name)) throw new Error(`表不在白名单：${name}`)
    }
    const rows = this.all(text)
    return { rows, count: rows.length }
  }

  // ── 写动作 ──────────────────────────────────────────────────────────────
  /** 跑一次流程：kind 决定真实现。 */
  runFlow(flowId, actor = 'web') {
    const flow = this.get('select * from flows where id=?', [flowId])
    if (flow === null) throw new Error(`流程不存在：${flowId}`)
    const startedAt = nowIso()
    let rows = 0
    let status = 'success'
    let message = ''
    try {
      if (flow.kind === 'sync-kefu') { rows = this.syncKefu(); message = `客服指标 ${rows} 行写入本地镜像` }
      else if (flow.kind === 'sync-liveops') { rows = this.syncLiveops(); message = `直播场次 ${rows} 行写入本地镜像` }
      else if (flow.kind === 'sync-dim') { rows = this.syncDim(); message = `公司归属 ${rows} 条` }
      else { status = 'failed'; message = `未知流程类型：${flow.kind}` }
    } catch (error) {
      status = 'failed'
      message = String(error && error.message ? error.message : error)
    }
    const runId = uid('run')
    this.run(`INSERT INTO flow_runs(id,flow_id,flow_name,status,rows,message,started_at,finished_at,actor)
      VALUES(?,?,?,?,?,?,?,?,?)`,
    [runId, flow.id, flow.name, status, rows, message, startedAt, nowIso(), actor])
    return { runId, status, rows, message }
  }

  /** 登记一个批次（把文件从「待登记」推进到「已登记」）。 */
  registerBatch(batchId, status = '已登记', note = null) {
    const batch = this.get('select * from ingest_batches where id=?', [batchId])
    if (batch === null) throw new Error(`批次不存在：${batchId}`)
    this.run('update ingest_batches set status=?, note=coalesce(?, note) where id=?', [status, note, batchId])
    return this.get('select * from ingest_batches where id=?', [batchId])
  }

  /** 重新扫描磁盘，把新出现的文件补登成「待登记」。 */
  scanFiles() {
    const before = this.get('select count(*) c from ingest_batches').c
    this.seedIngest()
    const after = this.get('select count(*) c from ingest_batches').c
    return { added: after - before, total: after }
  }

  /** 新建流程（只允许内置的三种真实现类型）。 */
  createFlow(payload) {
    const name = String(payload.name ?? '').trim()
    if (name === '') throw new Error('流程名不能为空')
    const kinds = ['sync-kefu', 'sync-liveops', 'sync-dim']
    if (!kinds.includes(payload.kind)) throw new Error(`流程类型必须是 ${kinds.join(' / ')}`)
    const id = uid('flow')
    this.run('INSERT INTO flows(id,name,kind,enabled,created_at) VALUES(?,?,?,?,?)',
      [id, name, payload.kind, 1, nowIso()])
    return this.get('select * from flows where id=?', [id])
  }

  setFlowEnabled(id, enabled) {
    const flow = this.get('select * from flows where id=?', [id])
    if (flow === null) throw new Error(`流程不存在：${id}`)
    this.run('update flows set enabled=? where id=?', [enabled ? 1 : 0, id])
    return this.get('select * from flows where id=?', [id])
  }

  setInfluencerStatus(id, status) {
    const row = this.get('select * from influencers where id=?', [id])
    if (row === null) throw new Error(`达人不存在：${id}`)
    this.run('update influencers set status=?, updated_at=? where id=?', [status, nowIso(), id])
    return this.get('select * from influencers where id=?', [id])
  }

  /** 流程列表 + 最近一次运行。 */
  flowBoard() {
    return this.all(`select f.*, r.status last_status, r.rows last_rows, r.message last_message, r.finished_at last_at
      from flows f left join flow_runs r on r.id = (
        select id from flow_runs where flow_id=f.id order by finished_at desc limit 1)
      order by f.created_at`)
  }

  /** 店铺归属总表：kefu 的全部店铺 × 本地 DIM。 */
  shopOwnership() {
    const shops = this.readOther(this.kefuDb(), 'select name, platform from shops order by platform, name')
    const dim = new Map(this.all('select shop_name, platform, company from dim_shop_company')
      .map(row => [`${row.shop_name}|${row.platform ?? ''}`, row.company]))
    return shops.map(shop => ({
      shop_name: shop.name,
      platform: shop.platform,
      company: dim.get(`${shop.name}|${shop.platform}`) ?? null,
    }))
  }

  upsertInfluencer(payload) {
    const name = String(payload.name ?? '').trim()
    if (name === '') throw new Error('达人姓名不能为空')
    const id = payload.id ?? uid('inf')
    const existing = this.get('select * from influencers where id=?', [id])
    const rate = payload.commission_rate === undefined || payload.commission_rate === null || payload.commission_rate === ''
      ? null : Number(payload.commission_rate)
    if (existing === null) {
      this.run('INSERT INTO influencers(id,name,platform,shop_name,commission_rate,status,note,updated_at) VALUES(?,?,?,?,?,?,?,?)',
        [id, name, payload.platform ?? null, payload.shop_name ?? null, rate, payload.status ?? '在职', payload.note ?? null, nowIso()])
    } else {
      this.run('update influencers set name=?, platform=?, shop_name=?, commission_rate=?, status=?, note=?, updated_at=? where id=?',
        [name, payload.platform ?? existing.platform, payload.shop_name ?? existing.shop_name,
          rate ?? existing.commission_rate, payload.status ?? existing.status, payload.note ?? existing.note, nowIso(), id])
    }
    return this.get('select * from influencers where id=?', [id])
  }

  addFundAdjustment(payload) {
    const amount = Number(payload.amount)
    if (!Number.isFinite(amount) || amount === 0) throw new Error('调整金额必须是非零数字')
    const reason = String(payload.reason ?? '').trim()
    if (reason === '') throw new Error('必须写调整原因')
    const id = uid('fund')
    this.run(`INSERT INTO fund_adjustments(id,platform,shop_name,amount,reason,status,batch_id,created_at,actor)
      VALUES(?,?,?,?,?,?,?,?,?)`,
    [id, payload.platform ?? null, payload.shop_name ?? null, amount, reason, '待复核', payload.batch_id ?? null, nowIso(), payload.actor ?? 'web'])
    return this.get('select * from fund_adjustments where id=?', [id])
  }

  reviewFundAdjustment(id, status) {
    if (!['已复核', '已驳回'].includes(status)) throw new Error('状态只能是 已复核 / 已驳回')
    const row = this.get('select * from fund_adjustments where id=?', [id])
    if (row === null) throw new Error(`调整单不存在：${id}`)
    if (row.status !== '待复核') throw new Error(`该单据已是「${row.status}」，不能重复处理`)
    this.run('update fund_adjustments set status=? where id=?', [status, id])
    return this.get('select * from fund_adjustments where id=?', [id])
  }

  mapCompany(payload) {
    const shop = String(payload.shop_name ?? '').trim()
    if (shop === '') throw new Error('店铺名不能为空')
    this.run('INSERT OR REPLACE INTO dim_shop_company(shop_name,platform,company,updated_at) VALUES(?,?,?,?)',
      [shop, payload.platform ?? null, payload.company ?? null, nowIso()])
    // 归属变了，把镜像里的 company 一并补上
    this.run('update metrics_daily set company=? where shop_name=? and platform is ?',
      [payload.company ?? null, shop, payload.platform ?? null])
    return this.get('select * from dim_shop_company where shop_name=? and platform is ?', [shop, payload.platform ?? null])
  }

  /** 可登记的文件清单（真实磁盘内容）。 */
  files() {
    const base = this.cofficeData()
    if (!existsSync(base)) return []
    const out = []
    const walk = (dir, depth) => {
      if (depth > 2) return
      let entries = []
      try { entries = readdirSync(dir, { withFileTypes: true }) } catch { return }
      for (const entry of entries) {
        const full = join(dir, entry.name)
        if (entry.isDirectory()) { walk(full, depth + 1); continue }
        const ext = extname(entry.name).toLowerCase()
        if (!['.xlsx', '.xls', '.csv'].includes(ext)) continue
        const rel = relative(base, full)
        out.push({ path: rel, name: entry.name, platform: rel.split('\\')[0], size: statSync(full).size })
      }
    }
    walk(base, 0)
    return out.sort((a, b) => a.path.localeCompare(b.path))
  }
}
