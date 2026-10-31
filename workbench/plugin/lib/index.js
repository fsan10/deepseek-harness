/**
 * dsh-workbench：把「联邦式平台」装进 dsh 的运行时插件。
 *
 * 设计边界（对应工作台方案）：
 *  - dsh 是运行时：项目只在工作台登记，代码留在自己的目录，平台不改它一行。
 *  - 控制室是状态投影：状态只来自端口探测、健康检查与运行记录，不猜。
 *  - 页面 = 视图包，操作 = 工具：人和 AI 走同一条通道，没有后门。
 *  - 启停是 L2：必须带 confirm 与 reason，结果全部进审计。
 */
import { existsSync, readdirSync, readFileSync, appendFileSync, mkdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { scanProjects, writeIndex, FORMS } from './registry.js'
import { StatusBoard, HEALTH_FORMULA } from './status.js'
import { Runner } from './runner.js'
import { Audit } from './audit.js'
import { parseYaml } from './yaml.js'
import { computeView } from './views.js'

export const name = 'dsh-workbench'
export const inject = ['webServer']

/** 工作台根目录：DSH_WORKBENCH_ROOT 优先，否则用插件包所在位置推。 */
function resolveRoot() {
  const env = process.env.DSH_WORKBENCH_ROOT
  if (env !== undefined && env.trim() !== '') return env.trim()
  return fileURLToPath(new URL('../../', import.meta.url))
}

function readJsonl(file) {
  if (!existsSync(file)) return []
  const rows = []
  for (const line of readFileSync(file, 'utf8').split('\n')) {
    if (line.trim() === '') continue
    try { rows.push(JSON.parse(line)) } catch { /* 半行跳过 */ }
  }
  return rows
}

function sendJson(res, status, payload) {
  const body = JSON.stringify(payload)
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
    'content-length': Buffer.byteLength(body),
  })
  res.end(body)
}

function readBody(req) {
  return new Promise(resolve => {
    let raw = ''
    req.on('data', chunk => { if (raw.length < 200_000) raw += chunk })
    req.on('end', () => {
      if (raw.trim() === '') return resolve({})
      try { resolve(JSON.parse(raw)) } catch { resolve({}) }
    })
    req.on('error', () => resolve({}))
  })
}

/**
 * 挂载工作台插件。
 * @param {import('@deepseek-ai/cordis').Context} ctx Cordis 上下文。
 */
export function apply(ctx) {
  const root = resolveRoot()
  const projectsDir = join(root, 'projects')
  const viewsDir = join(root, 'views')
  const varDir = join(root, 'var')
  const runsFile = join(varDir, 'runs.jsonl')
  mkdirSync(varDir, { recursive: true })

  let cache = { at: 0, value: scanProjects(projectsDir) }
  const getRegistry = () => {
    const now = Date.now()
    if (now - cache.at < 5000) return cache.value
    cache = { at: now, value: scanProjects(projectsDir), }
    writeIndex(projectsDir, cache.value)
    return cache.value
  }
  const getProjects = () => getRegistry().projects

  const board = new StatusBoard(getProjects, { varDir })
  board.seedRuns(readJsonl(runsFile).reverse())

  const audit = new Audit(join(varDir, 'audit.jsonl'))
  const runner = new Runner({
    varDir,
    log: message => ctx.logger?.info?.(message),
    onRun: (projectId, run) => {
      board.recordRun(projectId, run)
      try { appendFileSync(runsFile, `${JSON.stringify(run)}\n`, 'utf8') } catch { /* 运行记录可丢，审计不可丢 */ }
    },
  })

  /** 视图包声明，按 order 排序。 */
  const getViews = () => {
    const specs = []
    if (!existsSync(viewsDir)) return specs
    for (const entry of readdirSync(viewsDir)) {
      if (!entry.endsWith('.view.json')) continue
      try {
        const spec = JSON.parse(readFileSync(join(viewsDir, entry), 'utf8'))
        specs.push({ ...spec, file: entry })
      } catch { /* 坏视图不阻塞其它页面 */ }
    }
    return specs.sort((a, b) => (a.order ?? 999) - (b.order ?? 999))
  }

  /** 角色策略。 */
  const getRoles = () => {
    const file = join(root, 'policies/roles.yaml')
    if (!existsSync(file)) return []
    try {
      const raw = parseYaml(readFileSync(file, 'utf8'))
      return (raw?.roles ?? []).map(role => ({
        name: String(role.name ?? '未命名角色'),
        scope: String(role.scope ?? '未限定'),
        maxLevel: String(role.maxLevel ?? 'L0'),
        abilities: Array.isArray(role.abilities) ? role.abilities.map(String) : [],
      }))
    } catch {
      return []
    }
  }

  /** 项目运行前置是否就绪（缺 .venv / node_modules 时不允许一键启动）。 */
  const readiness = project => {
    const missing = project.requires.filter(rel => !existsSync(join(project.dir, rel)))
    return { ready: missing.length === 0, missing }
  }

  const viewContext = () => {
    const projects = getProjects()
    const states = board.snapshot(projects)
    // 新鲜度：取所有项目可读数据文件里最新的那个修改时间
    let newest = 0
    for (const project of projects) {
      for (const rel of project.dataFiles) {
        try {
          const stat = statSync(join(project.dir, rel))
          if (stat.mtimeMs > newest) newest = stat.mtimeMs
        } catch { /* 文件可能尚未生成 */ }
      }
    }
    return {
      root,
      projects,
      states,
      roles: getRoles(),
      auditTail: limit => audit.tail(limit),
      freshnessHours: newest === 0 ? null : (Date.now() - newest) / 3_600_000,
    }
  }

  // ── 定时探测：控制室的状态必须自己会走 ──────────────────────────────────
  ctx.effect(() => {
    const tick = () => { board.refresh().catch(() => {}) }
    tick()
    const timer = setInterval(tick, 15_000)
    if (typeof timer.unref === 'function') timer.unref()
    return () => clearInterval(timer)
  }, 'dsh-workbench: probe loop')

  // ── HTTP 接口（客户端面板与外部脚本共用） ────────────────────────────────
  const webServer = ctx.webServer ?? ctx.get?.('webServer')
  if (webServer === undefined || webServer === null) {
    ctx.logger?.warn?.('[dsh-workbench] webServer 不可用，跳过 HTTP 接口')
    return
  }

  const renderProject = project => {
    const states = board.snapshot([project])
    const state = states[project.id]
    const { ready, missing } = readiness(project)
    const owned = runner.pids[project.id] ?? null
    return {
      ...project,
      state: state.state,
      label: state.label,
      health: state.health,
      latencyMs: state.latencyMs,
      error: state.error,
      lastRun: state.lastRun,
      runs: state.runs,
      ready,
      missing,
      // 端口通但没有工作台 pid：很可能占用者是别的进程（例如正在用的生产实例）
      ownedPid: owned === null ? null : owned.pid,
      foreign: state.state === 'running' && owned === null,
    }
  }

  /** 启停 shared path：状态机推进 + 等端口 + 返回结果。 */
  const runControl = async (project, action) => {
    if (action === 'start') board.markStarting(project.id)
    const result = action === 'start' ? await runner.start(project) : await runner.stop(project)
    if (action === 'start' && result.ok) {
      // 等端口真正起来再回报状态，避免界面停在"启动中"又被下一次轮询覆盖
      const deadline = Date.now() + 6000
      do {
        await board.refresh(true)
        if (board.state(project.id)?.state === 'running') break
        await new Promise(resolve => setTimeout(resolve, 400))
      } while (Date.now() < deadline)
    }
    if (action === 'start' && !result.ok) board.markStopped(project.id, result.error)
    if (action === 'stop' && result.ok) board.markStopped(project.id, null)
    await board.refresh(true)
    return result
  }

  const handle = async (req, res) => {
    const url = new URL(req.url ?? '/', 'http://dsh.internal')
    const path = url.pathname.replace(/^\/api\/workbench/, '')
    const method = req.method ?? 'GET'

    if (path === '/health' || path === '') {
      sendJson(res, 200, {
        ok: true,
        plugin: name,
        root,
        projects: getProjects().length,
        views: getViews().length,
        formula: HEALTH_FORMULA,
      })
      return
    }

    if (path === '/bootstrap' && method === 'GET') {
      const projects = getProjects().map(renderProject)
      const running = projects.filter(p => p.state === 'running').length
      sendJson(res, 200, {
        root,
        generatedAt: new Date().toISOString(),
        projects,
        views: getViews(),
        forms: FORMS,
        policy: { roles: getRoles(), formula: HEALTH_FORMULA },
        summary: {
          total: projects.length,
          running,
          degraded: projects.filter(p => p.state === 'degraded').length,
          failed: projects.filter(p => p.state === 'failed').length,
          notReady: projects.filter(p => !p.ready).length,
        },
      })
      return
    }

    if (path === '/projects' && method === 'GET') {
      sendJson(res, 200, { projects: getProjects().map(renderProject) })
      return
    }

    const match = /^\/projects\/([^/]+)(?:\/(start|stop))?$/.exec(path)
    if (match !== null) {
      const id = decodeURIComponent(match[1])
      const project = getProjects().find(p => p.id === id)
      if (project === undefined) { sendJson(res, 404, { error: 'project-not-found', id }); return }

      if (method === 'GET' && match[2] === undefined) {
        sendJson(res, 200, { project: renderProject(project), dir: project.dir })
        return
      }

      if (method === 'POST' && (match[2] === 'start' || match[2] === 'stop')) {
        const action = match[2]
        const body = await readBody(req)
        const level = action === 'start' ? project.levels.start : project.levels.stop
        const intent = String(body.intent ?? body.reason ?? '').trim()

        if (level === 'L3') {
          const row = audit.append({ actor: body.actor ?? 'web', action, project: id, level, intent, ok: false, blocked: 'L3-redline' })
          sendJson(res, 403, { error: 'l3-redline', message: 'L3 动作不由 AI 或页面直接执行，请转人工工单', audit: row.id })
          return
        }
        if (body.confirm !== true) {
          sendJson(res, 428, {
            error: 'confirm-required',
            level,
            impact: action === 'stop'
              ? `将中断 ${project.name} 的在线访问，进行中的请求会失败`
              : `将在 ${project.port ?? '本机'} 端口启动 ${project.name}，持续占用资源直到手动停止`,
            hint: '确认后带 { confirm: true, intent: "为什么做这件事" } 重新提交',
          })
          return
        }
        const { ready, missing } = readiness(project)
        if (!ready) {
          const row = audit.append({ actor: body.actor ?? 'web', action, project: id, level, intent, ok: false, blocked: 'missing-prerequisite' })
          sendJson(res, 409, { error: 'not-ready', missing, audit: row.id, hint: `运行 workbench/scripts/bootstrap.ps1 ${id}` })
          return
        }

        const result = await runControl(project, action)
        const row = audit.append({
          actor: body.actor ?? 'web', action, project: id, level, intent,
          ok: result.ok, error: result.error ?? null, pid: result.pid ?? null,
        })
        sendJson(res, result.ok ? 200 : 500, {
          ok: result.ok,
          error: result.error ?? null,
          pid: result.pid ?? null,
          audit: row.id,
          project: renderProject(project),
        })
        return
      }
    }

    const logMatch = /^\/projects\/([^/]+)\/log$/.exec(path)
    if (logMatch !== null && method === 'GET') {
      const id = decodeURIComponent(logMatch[1])
      const lines = Math.min(400, Number(url.searchParams.get('lines') ?? 80) || 80)
      sendJson(res, 200, { id, ...runner.tailLog(id, lines) })
      return
    }

    if (path === '/views' && method === 'GET') {
      sendJson(res, 200, { views: getViews() })
      return
    }

    const viewMatch = /^\/views\/([^/]+)$/.exec(path)
    if (viewMatch !== null && method === 'GET') {
      const id = decodeURIComponent(viewMatch[1])
      const spec = getViews().find(v => v.id === id)
      if (spec === undefined) { sendJson(res, 404, { error: 'view-not-found', id }); return }
      const started = Date.now()
      const data = computeView(id, viewContext())
      sendJson(res, 200, { spec, data, elapsedMs: Date.now() - started })
      return
    }

    if (path === '/audit' && method === 'GET') {
      const limit = Math.min(500, Number(url.searchParams.get('limit') ?? 80) || 80)
      sendJson(res, 200, { rows: audit.tail(limit) })
      return
    }

    sendJson(res, 404, { error: 'not-found', path })
  }

  webServer.register({ kind: 'prefix', path: '/api/workbench', handler: (req, res) => { handle(req, res).catch(error => sendJson(res, 500, { error: String(error) })) } })

  // ── 模型侧工具：人和 AI 走同一条通道 ────────────────────────────────────
  const tools = ctx.get?.('tools') ?? ctx.tools
  if (tools === undefined || tools === null || typeof tools.register !== 'function') {
    ctx.logger?.warn?.('[dsh-workbench] 工具注册表不可用，仅提供页面')
    return
  }

  const text = value => [{ type: 'text', text: value }]

  ctx.effect(() => tools.register({
    name: 'workbench_projects',
    description: '列出全能工作台登记的全部项目（服务/任务/连接/视图），含状态、健康分与最近运行。'
      + '只读（L0）。回答「哪个项目在掉链子」先调它，再调 workbench_project 看细节。',
    parameters: {
      form: {
        type: 'string',
        enum: ['service', 'job', 'mcp', 'view'],
        description: '只看某一种形态；省略则全部。',
      },
      onlyProblems: { type: 'boolean', description: '只返回非运行中或有异常的条目。' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          summary: { type: 'string' },
          rows: {
            type: 'array',
            items: {
              type: 'object',
              additionalProperties: false,
              required: ['id', 'name', 'form', 'state', 'health', 'owner'],
              properties: {
                id: { type: 'string' },
                name: { type: 'string' },
                form: { type: 'string' },
                state: { type: 'string' },
                health: { type: 'integer' },
                owner: { type: 'string' },
              },
            },
          },
        },
        required: ['summary', 'rows'],
      },
      render: (_args, value) => text(value.summary),
    },
    execute(args) {
      const states = board.snapshot(getProjects())
      let rows = getProjects().map(project => ({
        id: project.id,
        name: project.name,
        form: project.form,
        state: states[project.id]?.label ?? '待运行',
        health: states[project.id]?.health.total ?? 0,
        owner: project.owner,
        error: states[project.id]?.error ?? null,
      }))
      if (typeof args.form === 'string') rows = rows.filter(row => row.form === args.form)
      if (args.onlyProblems === true) rows = rows.filter(row => row.state !== '运行中' || row.error !== null)
      return Promise.resolve({
        summary: rows.length === 0
          ? '没有符合条件的项目。'
          : `共 ${rows.length} 个项目：\n${rows.map(row => `- ${row.name}（${row.id}）· ${row.form} · ${row.state} · 健康分 ${row.health}${row.error ? ` · ${row.error}` : ''}`).join('\n')}`,
        rows: rows.map(({ error, ...row }) => row),
      })
    },
  }), 'dsh-workbench: tool workbench_projects')

  ctx.effect(() => tools.register({
    name: 'workbench_project',
    description: '读取单个项目的详情：健康分构成、依赖、最近 10 次运行、启动前置是否就绪。只读（L0）。',
    parameters: {
      id: { type: 'string', required: true, description: '项目 id，例如 kefu / liveops / coffice-ingest。' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          summary: { type: 'string' },
          detail: { type: 'object', additionalProperties: true },
        },
        required: ['summary', 'detail'],
      },
      render: (_args, value) => text(value.summary),
    },
    execute(args) {
      const project = getProjects().find(item => item.id === args.id)
      if (project === undefined) throw new Error(`未登记的项目：${args.id}`)
      const rendered = renderProject(project)
      const runs = rendered.runs.map(run => `${run.at} ${run.ok ? '成功' : '失败'} ${run.error ?? ''}`.trim())
      return Promise.resolve({
        summary: [
          `${rendered.name}（${rendered.id}）· ${rendered.form} · ${rendered.label}`,
          `健康分 ${rendered.health.total}（可用性 ${rendered.health.parts.availability} / 成功率 ${rendered.health.parts.success} / 时延 ${rendered.health.parts.latency} / 新鲜度 ${rendered.health.parts.freshness}）`,
          `负责人 ${rendered.owner} · 依赖 ${rendered.depends.length ? rendered.depends.join(', ') : '无'}`,
          rendered.ready ? '启动前置就绪' : `缺少运行前置：${rendered.missing.join(', ')}`,
          rendered.error ? `当前异常：${rendered.error}` : '当前无异常',
          `最近运行：${runs.length ? runs.slice(0, 5).join(' | ') : '无记录'}`,
        ].join('\n'),
        detail: {
          id: rendered.id,
          state: rendered.state,
          health: rendered.health,
          depends: rendered.depends,
          missing: rendered.missing,
          lastRun: rendered.lastRun,
        },
      })
    },
  }), 'dsh-workbench: tool workbench_project')

  ctx.effect(() => tools.register({
    name: 'workbench_view',
    description: '读取一个视图包的数据（今日工作台/项目矩阵/店铺全景/客服中心…）。只读（L0）。'
      + '视图 id 见 workbench_projects 之外的 /api/workbench/views；常用：today、projects、shops、kefu、runs。',
    parameters: {
      view: { type: 'string', required: true, description: '视图 id。' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          summary: { type: 'string' },
          data: { type: 'object', additionalProperties: true },
        },
        required: ['summary', 'data'],
      },
      render: (_args, value) => text(value.summary),
    },
    execute(args) {
      const spec = getViews().find(view => view.id === args.view)
      if (spec === undefined) throw new Error(`未知视图：${args.view}`)
      const data = computeView(args.view, viewContext())
      let summary = `${spec.title}：${spec.question}`
      if (data.kind === 'control') {
        summary += `\n共 ${data.summary.total} 个项目，运行中 ${data.summary.running}，降级 ${data.summary.degraded}，失败 ${data.summary.failed}。`
      } else if (data.kind === 'table') {
        summary += `\n${data.rows.length} 行数据。${data.note ?? ''}`
      } else if (data.kind === 'overview') {
        summary += `\n${data.kpis.map(kpi => `${kpi.label} ${kpi.value}`).join(' · ')}`
      } else if (data.kind === 'matrix') {
        summary += `\n${data.rows.length} 个对象 × ${data.columns.length} 项能力。`
      } else if (data.kind === 'governance') {
        summary += `\n${data.groups.length} 组。${data.note ?? ''}`
      } else {
        summary += `\n${data.reason ?? ''}`
      }
      return Promise.resolve({ summary, data })
    },
  }), 'dsh-workbench: tool workbench_view')

  ctx.effect(() => tools.register({
    name: 'workbench_control',
    description: '启动或停止一个服务形态项目（L2，需人确认）。'
      + '调用前必须先把影响面说清楚并得到用户明确同意；调用时 confirm 必须为 true，intent 写用户原话或本次诉求。'
      + '缺 .venv/node_modules 的项目会返回 not-ready，先让用户运行 bootstrap，不要自行安装依赖。'
      + 'L3 动作（付款/开票/删除/跨公司批量改价）永远拒绝执行，只能转人工。',
    parameters: {
      id: { type: 'string', required: true, description: '项目 id。' },
      action: { type: 'string', required: true, enum: ['start', 'stop'], description: 'start 或 stop。' },
      confirm: { type: 'boolean', required: true, description: '必须在用户明确同意后传 true。' },
      intent: { type: 'string', required: true, description: '为什么做这件事，写用户的原话或本次诉求。' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          summary: { type: 'string' },
          ok: { type: 'boolean' },
          auditId: { type: 'string' },
        },
        required: ['summary', 'ok', 'auditId'],
      },
      render: (_args, value) => text(value.summary),
    },
    async execute(args) {
      const project = getProjects().find(item => item.id === args.id)
      if (project === undefined) throw new Error(`未登记的项目：${args.id}`)
      const level = args.action === 'start' ? project.levels.start : project.levels.stop
      if (level === 'L3') {
        const row = audit.append({ actor: 'agent', action: args.action, project: args.id, level, intent: args.intent, ok: false, blocked: 'L3-redline' })
        return { ok: false, auditId: row.id, summary: '该动作属 L3 红线，工作台不执行；已在审计留下工单线索，请人工处理。' }
      }
      if (args.confirm !== true) {
        return { ok: false, auditId: '', summary: '未确认：先向用户说明影响面，得到明确同意后再以 confirm=true 调用。' }
      }
      const { ready, missing } = readiness(project)
      if (!ready) {
        const row = audit.append({ actor: 'agent', action: args.action, project: args.id, level, intent: args.intent, ok: false, blocked: 'missing-prerequisite' })
        return { ok: false, auditId: row.id, summary: `缺少运行前置：${missing.join(', ')}。请用户运行 workbench/scripts/bootstrap.ps1 ${args.id}。` }
      }
      const result = await runControl(project, args.action)
      const row = audit.append({ actor: 'agent', action: args.action, project: args.id, level, intent: args.intent, ok: result.ok, error: result.error ?? null, pid: result.pid ?? null })
      return {
        ok: result.ok,
        auditId: row.id,
        summary: result.ok
          ? `${project.name} 已${args.action === 'start' ? '启动' : '停止'}（pid ${result.pid ?? '—'}）。审计 ${row.id}。`
          : `${project.name} ${args.action} 失败：${result.error}。审计 ${row.id}。`,
      }
    },
  }), 'dsh-workbench: tool workbench_control')

  ctx.logger?.info?.(`[dsh-workbench] 已挂载 root=${root} projects=${getProjects().length} views=${getViews().length}`)
}
