/**
 * 状态与健康：控制室的可信度来源。
 *
 * 状态机：idle → starting → running ⇄ degraded → stopped / failed
 *  - starting 超过 30s 仍未通过健康检查 → failed
 *  - running 连续 3 次探测失败 → degraded（仍在跑，只是不再接新任务）
 * 健康分 = 可用性 40 + 成功率 30 + 时延 20 + 新鲜度 10（口径随分返回，界面必须展示）
 */
import { connect } from 'node:net'
import { statSync } from 'node:fs'
import { request } from 'node:http'
import { join } from 'node:path'

export const HEALTH_FORMULA = '可用性 40 + 成功率 30 + 时延 20 + 新鲜度 10'
const STARTING_TIMEOUT_MS = 30_000
const PROBE_TTL_MS = 8_000

/** TCP 连接探测（不依赖服务协议，端口通即视为存活）。 */
function tcpProbe(port, timeoutMs) {
  return new Promise(resolve => {
    const started = Date.now()
    const socket = connect({ host: '127.0.0.1', port })
    let settled = false
    const done = ok => {
      if (settled) return
      settled = true
      socket.destroy()
      resolve({ ok, latencyMs: Date.now() - started, error: ok ? null : 'connect-timeout' })
    }
    socket.setTimeout(timeoutMs)
    socket.once('connect', () => done(true))
    socket.once('timeout', () => done(false))
    socket.once('error', error => {
      if (settled) return
      settled = true
      resolve({ ok: false, latencyMs: Date.now() - started, error: error.code ?? 'connect-failed' })
    })
  })
}

/** HTTP 健康检查；返回状态码与解析后的 JSON（失败时为 null）。 */
function httpProbe(url, timeoutMs) {
  return new Promise(resolve => {
    const started = Date.now()
    const req = request(url, { method: 'GET', timeout: timeoutMs }, res => {
      let body = ''
      res.setEncoding('utf8')
      res.on('data', chunk => { if (body.length < 200_000) body += chunk })
      res.on('end', () => {
        let json = null
        try { json = JSON.parse(body) } catch { /* 非 JSON 健康端点按状态码判定 */ }
        resolve({
          ok: res.statusCode !== undefined && res.statusCode < 400,
          status: res.statusCode ?? 0,
          latencyMs: Date.now() - started,
          json,
        })
      })
    })
    req.on('timeout', () => { req.destroy(); resolve({ ok: false, status: 0, latencyMs: Date.now() - started, json: null }) })
    req.on('error', () => resolve({ ok: false, status: 0, latencyMs: Date.now() - started, json: null }))
    req.end()
  })
}

function ageHours(paths) {
  let newest = 0
  for (const file of paths) {
    try {
      const stat = statSync(file)
      if (stat.mtimeMs > newest) newest = stat.mtimeMs
    } catch { /* 文件可能尚未生成 */ }
  }
  if (newest === 0) return null
  return (Date.now() - newest) / 3_600_000
}

function freshnessScore(hours) {
  if (hours === null) return { score: 5, label: '无数据文件' }
  if (hours <= 24) return { score: 10, label: '24h 内更新' }
  if (hours <= 24 * 7) return { score: 6, label: `${Math.round(hours / 24)} 天前` }
  return { score: 2, label: `${Math.round(hours / 24)} 天前` }
}

function latencyScore(ms) {
  if (ms === null) return 12
  if (ms <= 200) return 20
  if (ms <= 500) return 15
  if (ms <= 1500) return 8
  return 3
}

/**
 * 状态看板：持有进程内状态机，负责探测、评分与降级判定。
 */
export class StatusBoard {
  /**
   * @param {() => object[]} getProjects 取当前注册表条目。
   * @param {{varDir: string}} options 运行目录。
   */
  constructor(getProjects, options) {
    this.getProjects = getProjects
    this.varDir = options.varDir
    this.states = new Map()
    this.probeAt = new Map()
    this.runs = new Map()
  }

  /** 记录一次运行结果（由 runner 写入）。 */
  recordRun(projectId, run) {
    const list = this.runs.get(projectId) ?? []
    list.unshift(run)
    this.runs.set(projectId, list.slice(0, 30))
  }

  /** 载入历史运行（进程重启后仍能算成功率）。 */
  seedRuns(entries) {
    for (const entry of entries) this.recordRun(entry.projectId, entry)
  }

  state(projectId) {
    return this.states.get(projectId) ?? null
  }

  markStarting(projectId) {
    this.states.set(projectId, { state: 'starting', since: Date.now(), failures: 0, error: null })
    this.probeAt.delete(projectId)
  }

  markStopped(projectId, reason) {
    this.states.set(projectId, { state: 'stopped', since: Date.now(), failures: 0, error: reason ?? null })
    this.probeAt.delete(projectId)
  }

  /**
   * 探测并推进状态机。
   * @param {boolean} force 忽略 TTL 强制探测。
   * @returns {Promise<Map<string, object>>}
   */
  async refresh(force = false) {
    const projects = this.getProjects()
    await Promise.all(projects.map(project => this.probeOne(project, force)))
    return this.snapshot(projects)
  }

  async probeOne(project, force) {
    const now = Date.now()
    const last = this.probeAt.get(project.id) ?? 0
    if (!force && now - last < PROBE_TTL_MS && this.states.has(project.id)) return
    this.probeAt.set(project.id, now)

    const previous = this.states.get(project.id)
    let state = previous?.state ?? 'idle'
    let latency = null
    let http = null
    let error = null

    if (project.form === 'service' && project.port) {
      const tcp = await tcpProbe(project.port, project.health.timeoutMs)
      latency = tcp.latencyMs
      if (tcp.ok) {
        if (project.health.path) {
          http = await httpProbe(`${project.url}${project.health.path}`, project.health.timeoutMs)
          if (!http.ok) error = `健康检查 ${http.status || '无响应'}`
        }
        state = error ? 'degraded' : 'running'
      } else {
        error = tcp.error
        if (state === 'starting' && now - (previous?.since ?? now) > STARTING_TIMEOUT_MS) state = 'failed'
        else if (state !== 'starting') state = 'stopped'
      }
    } else if (project.form === 'view') {
      state = 'running'
    } else if (project.form === 'mcp') {
      state = previous?.state === 'running' ? 'running' : 'stopped'
    } else {
      const runs = this.runs.get(project.id) ?? []
      const lastRun = runs[0]
      state = lastRun === undefined ? 'idle' : (lastRun.ok ? 'idle' : 'failed')
    }

    const failures = error === null ? 0 : (previous?.failures ?? 0) + 1
    if (state === 'running' && failures >= 3) state = 'degraded'
    const next = {
      state,
      since: state === previous?.state ? (previous?.since ?? now) : now,
      failures,
      // 已停止就是没在跑，不把连接被拒当成「异常」挂在面板上
      error: state === 'stopped' ? null : error,
      latencyMs: latency,
      http,
      probedAt: now,
    }
    this.states.set(project.id, next)
  }

  snapshot(projects) {
    const rows = {}
    for (const project of projects) {
      const state = this.states.get(project.id) ?? { state: 'idle', since: Date.now(), failures: 0, error: null, latencyMs: null }
      const runs = this.runs.get(project.id) ?? []
      const scored = runs.slice(0, 20).filter(run => typeof run.ok === 'boolean')
      const successRate = scored.length === 0 ? null : scored.filter(run => run.ok).length / scored.length

      let availability = 0
      if (project.form === 'service') {
        availability = state.state === 'running' ? 40 : state.state === 'starting' ? 20 : state.state === 'degraded' ? 22 : 0
      } else if (project.form === 'view') {
        availability = 40
      } else if (project.form === 'job') {
        const lastRun = runs[0]
        availability = lastRun === undefined ? 24 : lastRun.ok ? 40 : 0
      } else {
        availability = state.state === 'running' ? 40 : 12
      }
      const success = successRate === null
        ? (state.state === 'running' ? 30 : state.state === 'degraded' ? 15 : 0)
        : Math.round(successRate * 30)
      // 没在跑就没有「时延」可言：不拿未知当合格
      const latency = project.form === 'service'
        ? (state.state === 'running' || state.state === 'degraded' ? latencyScore(state.latencyMs) : 0)
        : 16
      const fresh = freshnessScore(ageHours(project.dataFiles.map(f => join(project.dir, f))))
      const total = Math.max(0, Math.min(100, availability + success + latency + fresh.score))

      rows[project.id] = {
        ...state,
        label: stateLabel(state.state),
        health: {
          total,
          parts: { availability, success, latency, freshness: fresh.score },
          successRate,
          freshness: fresh.label,
        },
        lastRun: runs[0] ?? null,
        runs: runs.slice(0, 10),
      }
    }
    return rows
  }
}

/** 状态的中文标签（界面与工具输出共用一套词）。 */
export function stateLabel(state) {
  switch (state) {
    case 'running': return '运行中'
    case 'starting': return '启动中'
    case 'degraded': return '降级'
    case 'stopped': return '已停止'
    case 'failed': return '失败'
    case 'idle': return '待运行'
    default: return state
  }
}
