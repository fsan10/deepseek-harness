/**
 * 项目注册表：扫描 workbench/projects/<id>/project.yaml，校验并归一。
 *
 * project.yaml 是唯一真源；registry.json 只是扫描产物，任何进程都不得回写它。
 * 校验失败不静默跳过——坏条目以 `problems` 显式出现在控制室里。
 */
import { readFileSync, readdirSync, statSync, existsSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { parseYaml } from './yaml.js'

/** 四种项目形态，启动语义完全不同。 */
export const FORMS = {
  service: { label: '服务', hint: '常驻进程，可启停、看健康' },
  job: { label: '任务', hint: '跑一次看上次，无端口' },
  mcp: { label: '连接', hint: 'MCP/外部连接，看调用与连接态' },
  view: { label: '视图', hint: '只读投影页，无进程' },
}

const REQUIRED = ['id', 'name', 'form', 'owner']

function normalize(raw, dir) {
  const problems = []
  for (const key of REQUIRED) {
    if (raw[key] === undefined || raw[key] === null || raw[key] === '') problems.push(`缺少 ${key}`)
  }
  if (raw.form !== undefined && !FORMS[raw.form]) problems.push(`form 必须是 ${Object.keys(FORMS).join('/')}`)
  if (raw.form === 'service' && !raw.port && !raw.url) problems.push('service 形态需要 port 或 url')
  if (raw.port !== undefined && !Number.isInteger(raw.port)) problems.push('port 必须是整数')

  const health = raw.health ?? {}
  const runtime = raw.runtime ?? {}
  const levels = raw.levels ?? {}
  return {
    id: String(raw.id ?? dir),
    name: String(raw.name ?? dir),
    form: raw.form ?? 'service',
    domain: String(raw.domain ?? '未分类'),
    owner: String(raw.owner ?? '未指定'),
    description: String(raw.description ?? ''),
    source: raw.source ? String(raw.source) : '',
    port: Number.isInteger(raw.port) ? raw.port : null,
    url: raw.url ? String(raw.url) : (raw.port ? `http://127.0.0.1:${raw.port}` : null),
    health: {
      path: health.path ? String(health.path) : null,
      timeoutMs: Number.isFinite(health.timeoutMs) ? health.timeoutMs : 1200,
    },
    runtime: {
      start: runtime.start ? String(runtime.start) : null,
      stop: runtime.stop ? String(runtime.stop) : null,
      command: runtime.command ? String(runtime.command) : null,
      args: Array.isArray(runtime.args) ? runtime.args.map(String) : [],
      cwd: runtime.cwd ? String(runtime.cwd) : '.',
    },
    depends: Array.isArray(raw.depends) ? raw.depends.map(String) : [],
    requires: Array.isArray(raw.requires) ? raw.requires.map(String) : [],
    capabilities: Array.isArray(raw.capabilities) ? raw.capabilities.map(String) : [],
    tags: Array.isArray(raw.tags) ? raw.tags.map(String) : [],
    split: Array.isArray(raw.split) ? raw.split.map(String) : [],
    schedule: raw.schedule ? String(raw.schedule) : null,
    dataFiles: Array.isArray(raw.dataFiles) ? raw.dataFiles.map(String) : [],
    levels: {
      start: levels.start ?? 'L2',
      stop: levels.stop ?? 'L2',
      read: levels.read ?? 'L0',
      write: levels.write ?? 'L2',
    },
    dir,
    problems,
  }
}

/**
 * 扫描注册表。目录不存在时返回空表而不是抛错——工作台要能在空工作区里打开。
 * @param {string} projectsDir 绝对路径。
 * @returns {{projects: object[], scannedAt: string, problems: object[]}}
 */
export function scanProjects(projectsDir) {
  const projects = []
  if (!existsSync(projectsDir)) return { projects, scannedAt: new Date().toISOString(), problems: [] }

  for (const entry of readdirSync(projectsDir, { withFileTypes: true })) {
    if (!entry.isDirectory() || entry.name.startsWith('.')) continue
    const dir = join(projectsDir, entry.name)
    const manifest = join(dir, 'project.yaml')
    if (!existsSync(manifest)) continue
    try {
      const stat = statSync(manifest)
      const raw = parseYaml(readFileSync(manifest, 'utf8')) ?? {}
      const project = normalize({ ...raw, id: raw.id ?? entry.name }, dir)
      project.manifestMtime = stat.mtimeMs
      projects.push(project)
    } catch (error) {
      projects.push({
        id: entry.name,
        name: entry.name,
        form: 'service',
        domain: '未分类',
        owner: '未指定',
        description: 'project.yaml 解析失败',
        port: null,
        url: null,
        dir,
        problems: [String(error && error.message ? error.message : error)],
        health: { path: null, timeoutMs: 1200 },
        runtime: { start: null, stop: null, cwd: '.' },
        depends: [], capabilities: [], tags: [], split: [], dataFiles: [],
        levels: { start: 'L2', stop: 'L2', read: 'L0', write: 'L2' },
      })
    }
  }
  projects.sort((a, b) => a.id.localeCompare(b.id))
  return {
    projects,
    scannedAt: new Date().toISOString(),
    problems: projects.filter(p => p.problems.length > 0).map(p => ({ id: p.id, problems: p.problems })),
  }
}

/**
 * 写入只读索引（供人查看与外部脚本消费）。
 * @param {string} projectsDir 项目根。
 * @param {object} registry 扫描结果。
 */
export function writeIndex(projectsDir, registry) {
  try {
    writeFileSync(join(projectsDir, 'registry.json'), JSON.stringify({
      scannedAt: registry.scannedAt,
      count: registry.projects.length,
      projects: registry.projects.map(p => ({
        id: p.id, name: p.name, form: p.form, domain: p.domain, owner: p.owner,
        port: p.port, url: p.url, depends: p.depends, split: p.split, problems: p.problems,
      })),
    }, null, 2), 'utf8')
  } catch {
    // 索引是副产品：只读文件系统或并发写入失败不应影响控制室
  }
}
