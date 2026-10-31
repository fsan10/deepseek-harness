/**
 * 只读 SQLite 访问：工作台只读取项目自己的本地库，绝不写回。
 *
 * 用 Node 内建 node:sqlite（22.5+）。不可用时降级为 `null`，
 * 调用方必须把「数据未接入」显式呈现给用户，而不是伪造 0。
 */
import { existsSync, statSync } from 'node:fs'

let sqlite = null
let sqliteError = null
try {
  // 实验特性：加载失败不能让整个宿主插件挂掉
  sqlite = await import('node:sqlite')
} catch (error) {
  sqliteError = String(error && error.message ? error.message : error)
}

const cache = new Map()

/**
 * 打开一个只读库（带 mtime 缓存）。
 * @param {string} file 数据库绝对路径。
 * @returns {{db: object|null, error: string|null}}
 */
export function openDb(file) {
  if (sqlite === null) return { db: null, error: `node:sqlite 不可用：${sqliteError ?? 'unknown'}` }
  if (!existsSync(file)) return { db: null, error: `数据库不存在：${file}` }
  let mtime = 0
  try { mtime = statSync(file).mtimeMs } catch { /* 继续用缓存 */ }
  const cached = cache.get(file)
  if (cached && cached.mtime === mtime) return { db: cached.db, error: null }
  try {
    const db = new sqlite.DatabaseSync(file, { readOnly: true })
    cache.set(file, { db, mtime })
    return { db, error: null }
  } catch (error) {
    return { db: null, error: String(error && error.message ? error.message : error) }
  }
}

/**
 * 查询并返回对象数组。
 * @param {string} file 数据库路径。
 * @param {string} sql SQL（只允许 SELECT）。
 * @param {object} fallback 失败时的返回值。
 * @returns {{rows: object[], error: string|null}}
 */
export function query(file, sql, fallback = []) {
  const { db, error } = openDb(file)
  if (db === null) return { rows: fallback, error }
  try {
    return { rows: db.prepare(sql).all(), error: null }
  } catch (err) {
    return { rows: fallback, error: String(err && err.message ? err.message : err) }
  }
}

/**
 * 单值查询（取第一行第一列）。
 * @param {string} file 数据库路径。
 * @param {string} sql SQL。
 * @param {unknown} fallback 失败时的返回值。
 */
export function scalar(file, sql, fallback = null) {
  const { rows, error } = query(file, sql, [])
  if (error !== null) return { value: fallback, error }
  const row = rows[0]
  if (row === undefined) return { value: fallback, error: null }
  return { value: Object.values(row)[0], error: null }
}
