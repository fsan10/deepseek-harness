/**
 * 审计流水：一次调用一行 JSONL，永不改写历史行。
 *
 * 记录自然语言原始诉求（intent）而不只是参数——事后回放时，人当时说了什么
 * 比工具参数更能解释「为什么这么做」。
 */
import { appendFileSync, existsSync, mkdirSync, readFileSync } from 'node:fs'
import { dirname } from 'node:path'

export class Audit {
  /** @param {string} file 审计文件绝对路径。 */
  constructor(file) {
    this.file = file
    mkdirSync(dirname(file), { recursive: true })
  }

  /**
   * 追加一条审计。
   * @param {object} entry 审计字段。
   * @returns {object} 补齐 id/at 后的条目。
   */
  append(entry) {
    const row = {
      id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
      at: new Date().toISOString(),
      actor: entry.actor ?? 'web',
      ...entry,
    }
    try {
      appendFileSync(this.file, `${JSON.stringify(row)}\n`, 'utf8')
    } catch {
      // 审计不可写时不能让业务动作静默失败；调用方会收到 ok=false 的结果
      return { ...row, persisted: false }
    }
    return { ...row, persisted: true }
  }

  /**
   * 读取最近若干条。
   * @param {number} limit 条数上限。
   * @returns {object[]} 由新到旧。
   */
  tail(limit = 100) {
    if (!existsSync(this.file)) return []
    const lines = readFileSync(this.file, 'utf8').split('\n').filter(Boolean)
    const rows = []
    for (let i = lines.length - 1; i >= 0 && rows.length < limit; i--) {
      try { rows.push(JSON.parse(lines[i])) } catch { /* 半行写入直接跳过 */ }
    }
    return rows
  }

  /**
   * 统计窗口内的写操作次数，用于会话预算。
   * @param {number} windowMs 时间窗。
   * @param {string} actor 调用方标识。
   */
  writesWithin(windowMs, actor = null) {
    const since = Date.now() - windowMs
    return this.tail(500).filter(row => {
      if (row.level !== 'L2' && row.level !== 'L3') return false
      if (actor !== null && row.actor !== actor) return false
      return Date.parse(row.at) >= since
    }).length
  }
}
