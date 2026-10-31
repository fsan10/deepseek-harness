/**
 * 极简 YAML 读取器：只覆盖 project.yaml 需要的子集。
 *
 * 支持：注释、缩进映射、`-` 序列、行内数组 `[a, b]`、单双引号字符串、
 * true/false/null/数字。不支持锚点、多行块标量、复杂流式映射。
 * 不引入第三方向依赖——宿主 profile 里不一定装得到 yaml 包。
 */

/** 去掉引号外的 `#` 注释。 */
function stripComment(line) {
  let quote = null
  for (let i = 0; i < line.length; i++) {
    const ch = line[i]
    if (quote !== null) {
      if (ch === quote) quote = null
      continue
    }
    if (ch === '"' || ch === "'") { quote = ch; continue }
    if (ch === '#' && (i === 0 || line[i - 1] === ' ' || line[i - 1] === '\t')) {
      return line.slice(0, i)
    }
  }
  return line
}

/** 标量转换：引号、布尔、null、数字，否则原样字符串。 */
function coerce(raw) {
  const value = raw.trim()
  if (value === '') return null
  if (/^"(.*)"$/s.test(value)) return value.slice(1, -1).replace(/\\"/g, '"').replace(/\\n/g, '\n')
  if (/^'(.*)'$/s.test(value)) return value.slice(1, -1).replace(/''/g, "'")
  if (value === 'true') return true
  if (value === 'false') return false
  if (value === 'null' || value === '~') return null
  if (/^-?\d+(\.\d+)?$/.test(value)) return Number(value)
  if (value.startsWith('[') && value.endsWith(']')) {
    const inner = value.slice(1, -1).trim()
    if (inner === '') return []
    return inner.split(',').map(part => coerce(part))
  }
  return value
}

/** 拆出 `key:` 与冒号后的剩余内容；key 支持引号。 */
function splitKey(text) {
  let quote = null
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]
    if (quote !== null) {
      if (ch === quote) quote = null
      continue
    }
    if (ch === '"' || ch === "'") { quote = ch; continue }
    if (ch === ':') return [text.slice(0, i).trim().replace(/^["']|["']$/g, ''), text.slice(i + 1).trim()]
  }
  return null
}

function parseBlock(lines, start, indent) {
  const first = lines[start]
  const isSeq = first.text.startsWith('- ') || first.text === '-'
  const out = isSeq ? [] : {}
  let i = start

  while (i < lines.length) {
    const line = lines[i]
    if (line.indent < indent) break
    if (line.indent > indent) throw new Error(`缩进错误（第 ${line.no} 行）：期望 ${indent} 空格`)

    if (isSeq) {
      if (!line.text.startsWith('-')) break
      const rest = line.text.slice(1).trim()
      if (rest === '') {
        const [value, next] = parseBlock(lines, i + 1, nextIndent(lines, i + 1, indent))
        out.push(value)
        i = next
        continue
      }
      const pair = splitKey(rest)
      if (pair !== null) {
        // 序列里的行内映射起始：后续同层缩进的键都属于这条记录
        const itemIndent = indent + 2
        const synthetic = [{ text: rest, indent: itemIndent, no: line.no }]
        let j = i + 1
        while (j < lines.length && lines[j].indent >= itemIndent) {
          synthetic.push(lines[j])
          j++
        }
        const [value] = parseBlock(synthetic, 0, itemIndent)
        out.push(value)
        i = j
        continue
      }
      out.push(coerce(rest))
      i++
      continue
    }

    const pair = splitKey(line.text)
    if (pair === null) throw new Error(`无法解析（第 ${line.no} 行）：${line.text}`)
    const [key, rest] = pair
    if (rest !== '') {
      out[key] = coerce(rest)
      i++
      continue
    }
    const next = i + 1
    if (next >= lines.length || lines[next].indent <= indent) {
      out[key] = null
      i = next
      continue
    }
    const [value, after] = parseBlock(lines, next, nextIndent(lines, next, indent))
    out[key] = value
    i = after
  }
  return [out, i]
}

function nextIndent(lines, index, parentIndent) {
  if (index >= lines.length) return parentIndent + 2
  return lines[index].indent
}

/**
 * 解析 YAML 文本。
 * @param {string} text 文件内容。
 * @returns {unknown} 顶层值（通常是对象）。
 */
export function parseYaml(text) {
  const lines = []
  text.split(/\r?\n/).forEach((raw, index) => {
    const withoutComment = stripComment(raw)
    if (withoutComment.trim() === '') return
    const indent = withoutComment.length - withoutComment.trimStart().length
    lines.push({ text: withoutComment.trim(), indent, no: index + 1 })
  })
  if (lines.length === 0) return {}
  const [value] = parseBlock(lines, 0, lines[0].indent)
  return value
}
