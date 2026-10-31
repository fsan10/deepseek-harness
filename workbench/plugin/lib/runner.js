/**
 * 运行时执行器：只调用项目自己声明的脚本，不猜启动命令。
 *
 * 关键约束（来自项目控制室设计）：
 *  - 控制面不做「进程的爹」：子进程分离启动，pid 落盘，宿主重启后清理孤儿。
 *  - 启停是 L2 动作：调用方必须先拿到确认，执行结果全部进审计。
 */
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, openSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

function readJson(file, fallback) {
  try { return JSON.parse(readFileSync(file, 'utf8')) } catch { return fallback }
}

/** 是否仍存活（signal 0 只做存在性检查）。 */
function alive(pid) {
  if (!pid) return false
  try { process.kill(pid, 0); return true } catch { return false }
}

export class Runner {
  /**
   * @param {{varDir: string, onRun: (projectId: string, run: object) => void, log?: (msg: string) => void}} options 运行目录与回调。
   */
  constructor(options) {
    this.varDir = options.varDir
    this.onRun = options.onRun
    this.log = options.log ?? (() => {})
    this.pidFile = join(this.varDir, 'pids.json')
    this.pids = readJson(this.pidFile, {})
    mkdirSync(this.varDir, { recursive: true })
    this.cleanupOrphans()
  }

  /** 宿主重启后，丢弃已经不在的 pid；仍存活的保留（可能是用户在别处启动的）。 */
  cleanupOrphans() {
    let changed = false
    for (const [id, entry] of Object.entries(this.pids)) {
      if (!alive(entry.pid)) { delete this.pids[id]; changed = true }
    }
    if (changed) this.savePids()
  }

  savePids() {
    try { writeFileSync(this.pidFile, JSON.stringify(this.pids, null, 2), 'utf8') } catch { /* 只影响孤儿清理，不阻断启停 */ }
  }

  /**
   * 启动一个服务形态项目。
   * @param {object} project 注册表条目。
   * @returns {Promise<{ok: boolean, pid?: number, error?: string}>}
   */
  async start(project) {
    const started = Date.now()
    if (!project.runtime.start && !project.runtime.command) {
      return this.finish(project, started, false, 'project.yaml 未声明 runtime.command 或 runtime.start')
    }
    const script = project.runtime.start ? join(project.dir, project.runtime.start) : null
    if (script !== null && !existsSync(script)) {
      return this.finish(project, started, false, `启动脚本不存在：${project.runtime.start}`)
    }
    const existing = this.pids[project.id]
    if (existing && alive(existing.pid)) {
      return { ok: true, pid: existing.pid, already: true }
    }

    const cwd = join(project.dir, project.runtime.cwd)
    // 相对路径的可执行文件按项目目录解析（spawn 的 cwd 选项不影响可执行文件查找）
    const rawCommand = project.runtime.command
    const resolved = rawCommand === null
      ? null
      : /[\\/]/.test(rawCommand) ? join(project.dir, rawCommand) : rawCommand
    // 优先用声明的 command/args 直接拉起；只有脚本声明时才交给系统 shell
    const command = resolved !== null
      ? [resolved, project.runtime.args]
      : script.endsWith('.ps1')
        ? ['powershell', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script]]
        : script.endsWith('.sh')
          ? ['bash', [script]]
          : [script, []]

    try {
      // 子进程输出落到 var/logs/<id>.log：分离启动后没有终端，日志是唯一证据
      const logDir = join(this.varDir, 'logs')
      mkdirSync(logDir, { recursive: true })
      const logPath = join(logDir, `${project.id}.log`)
      const log = openSync(logPath, 'a')
      const child = spawn(command[0], command[1], {
        cwd: existsSync(cwd) ? cwd : project.dir,
        detached: true,
        stdio: ['ignore', log, log],
        windowsHide: true,
      })
      child.unref()
      const pid = child.pid
      this.pids[project.id] = { pid, startedAt: new Date().toISOString(), script: project.runtime.start, logPath }
      this.savePids()
      this.log(`[runner] ${project.id} 启动 pid=${pid} log=${logPath}`)
      return this.finish(project, started, true, undefined, pid)
    } catch (error) {
      return this.finish(project, started, false, String(error && error.message ? error.message : error))
    }
  }

  /**
   * 读取一个项目的启动日志尾部。
   * @param {string} projectId 项目 id。
   * @param {number} lines 行数。
   */
  tailLog(projectId, lines = 60) {
    const entry = this.pids[projectId]
    const file = entry?.logPath ?? join(this.varDir, 'logs', `${projectId}.log`)
    if (!existsSync(file)) return { path: file, text: '' }
    const rows = readFileSync(file, 'utf8').split('\n')
    return { path: file, text: rows.slice(-lines).join('\n') }
  }

  /**
   * 停止一个服务形态项目（整棵进程树）。
   * @param {object} project 注册表条目。
   */
  async stop(project) {
    const started = Date.now()
    const entry = this.pids[project.id]
    if (!entry || !alive(entry.pid)) {
      delete this.pids[project.id]
      this.savePids()
      return this.finish(project, started, true, '进程已不在，已清理 pid 记录')
    }
    const ok = await new Promise(resolve => {
      const args = process.platform === 'win32'
        ? ['/PID', String(entry.pid), '/T', '/F']
        : ['-TERM', String(entry.pid)]
      const killer = spawn(process.platform === 'win32' ? 'taskkill' : 'kill', args, { stdio: 'ignore', windowsHide: true })
      killer.on('exit', code => resolve(code === 0))
      killer.on('error', () => resolve(false))
    })
    if (ok) {
      delete this.pids[project.id]
      this.savePids()
    }
    return this.finish(project, started, ok, ok ? undefined : '停止命令返回失败')
  }

  finish(project, started, ok, error, pid) {
    const run = {
      id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`,
      projectId: project.id,
      action: 'runtime',
      ok,
      error: error ?? null,
      pid: pid ?? null,
      durationMs: Date.now() - started,
      at: new Date().toISOString(),
    }
    this.onRun(project.id, run)
    return { ok, pid, error, run }
  }
}
