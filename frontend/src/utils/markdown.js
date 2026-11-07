/**
 * 极简 Markdown 渲染器。
 *
 * 后端 answer 是 Markdown（含加粗、列表、表格）。项目不引入 markdown 依赖，
 * 这里只实现「展示够用」的子集，且严格「先转义、后生成标签」，
 * 因此可以安全地交给 v-html。
 */

const ESCAPE_MAP = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}

const TABLE_SEPARATOR = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$/
const RULE = /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/
const HEADING = /^(#{1,6})\s+(.*)$/
const UNORDERED = /^\s*[-*+]\s+/
const ORDERED = /^\s*\d+[.)]\s+/
const QUOTE = /^\s*>\s?/

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ESCAPE_MAP[char])
}

/** 行内：`code` 与 **加粗**。参数必须是已转义的文本。 */
function renderInline(escaped) {
  return escaped
    .split(/(`[^`\n]+`)/g)
    .map((segment, index) => {
      if (index % 2 === 1) {
        return `<code>${segment.slice(1, -1)}</code>`
      }
      return segment.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    })
    .join('')
}

function splitRow(line) {
  let text = line.trim()
  if (text.startsWith('|')) text = text.slice(1)
  if (text.endsWith('|')) text = text.slice(0, -1)
  return text.split('|').map((cell) => cell.trim())
}

function renderTable(header, rows) {
  const head = header
    .map((cell) => `<th>${renderInline(escapeHtml(cell))}</th>`)
    .join('')
  const body = rows
    .map((row) => {
      const cells = header
        .map((_, column) => `<td>${renderInline(escapeHtml(row[column] ?? ''))}</td>`)
        .join('')
      return `<tr>${cells}</tr>`
    })
    .join('')
  return `<div class="md-table"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`
}

function isBlockStart(line) {
  return (
    RULE.test(line) ||
    HEADING.test(line) ||
    line.trim().startsWith('|') ||
    QUOTE.test(line) ||
    UNORDERED.test(line) ||
    ORDERED.test(line)
  )
}

function renderList(items, tag) {
  const body = items
    .map((item) => `<li>${renderInline(escapeHtml(item.trim()))}</li>`)
    .join('')
  return `<${tag}>${body}</${tag}>`
}

/**
 * 把 Markdown 源文本渲染成安全 HTML。
 * @param {string} source
 * @returns {string}
 */
export function renderMarkdown(source) {
  const text = String(source ?? '').replace(/\r\n?/g, '\n')
  if (!text.trim()) return ''

  const lines = text.split('\n')
  const html = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]

    if (!line.trim()) {
      index += 1
      continue
    }

    if (RULE.test(line)) {
      html.push('<hr />')
      index += 1
      continue
    }

    const heading = HEADING.exec(line)
    if (heading) {
      const level = Math.min(heading[1].length + 2, 6)
      html.push(`<h${level}>${renderInline(escapeHtml(heading[2].trim()))}</h${level}>`)
      index += 1
      continue
    }

    if (line.trim().startsWith('|') && TABLE_SEPARATOR.test(lines[index + 1] ?? '')) {
      const header = splitRow(line)
      index += 2
      const rows = []
      while (index < lines.length && lines[index].trim().startsWith('|')) {
        rows.push(splitRow(lines[index]))
        index += 1
      }
      html.push(renderTable(header, rows))
      continue
    }

    if (QUOTE.test(line)) {
      const buffer = []
      while (index < lines.length && QUOTE.test(lines[index])) {
        buffer.push(lines[index].replace(QUOTE, ''))
        index += 1
      }
      html.push(`<blockquote>${renderInline(escapeHtml(buffer.join(' ')))}</blockquote>`)
      continue
    }

    if (UNORDERED.test(line)) {
      const items = []
      while (index < lines.length && UNORDERED.test(lines[index])) {
        items.push(lines[index].replace(UNORDERED, ''))
        index += 1
      }
      html.push(renderList(items, 'ul'))
      continue
    }

    if (ORDERED.test(line)) {
      const items = []
      while (index < lines.length && ORDERED.test(lines[index])) {
        items.push(lines[index].replace(ORDERED, ''))
        index += 1
      }
      html.push(renderList(items, 'ol'))
      continue
    }

    const buffer = []
    while (index < lines.length) {
      const current = lines[index]
      if (!current.trim() || (buffer.length > 0 && isBlockStart(current))) break
      buffer.push(current.trim())
      index += 1
    }
    if (buffer.length === 0) {
      // 理论上不可达：避免任何情况下死循环。
      index += 1
      continue
    }
    html.push(`<p>${buffer.map((item) => renderInline(escapeHtml(item))).join('<br />')}</p>`)
  }

  return html.join('\n')
}
