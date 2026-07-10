import { unified } from 'unified'
import remarkParse from 'remark-parse'
import remarkMath from 'remark-math'
import remarkGfm from 'remark-gfm'
import remarkBreaks from 'remark-breaks'
import remarkRehype from 'remark-rehype'
import rehypeKatex from 'rehype-katex'
import rehypeHighlight from 'rehype-highlight'
import rehypeStringify from 'rehype-stringify'
import { visit } from 'unist-util-visit'

const FENCE_RE = /^[ \t]{0,3}(?:```|~~~)/

/** 修补 LLM 常见的粗体/斜体/删除线孤立标记泄露 */
function sanitizeOrphanAsterisks(text) {
  const lines = text.split('\n')
  let inFenced = false
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (FENCE_RE.test(line)) { inFenced = !inFenced; continue }
    if (inFenced) continue
    if (/^[ \t]{4,}/.test(line)) continue
    // 全局移除 ~~ 禁用删除线（LLM 中文输出中可能意外出现）
    lines[i] = line.replace(/~~/g, '')
    const clean = lines[i]
    if (!clean) continue
    for (const suffix of ['***', '**', '*']) {
      const escaped = suffix.replace(/\*/g, '\\*')
      const trailing = clean.match(RegExp(`${escaped}(\\s*)$`))
      if (!trailing) continue
      const rest = clean.slice(0, clean.length - trailing[0].length)
      let count = 0
      let inBacktick = false
      for (let j = 0; j < rest.length; j++) {
        if (rest[j] === '`') { inBacktick = !inBacktick; continue }
        if (inBacktick) continue
        if (rest.slice(j, j + suffix.length) === suffix) {
          count++
          j += suffix.length - 1
        }
      }
      if (count % 2 === 0) {
        lines[i] = rest + trailing[1]
        break
      }
    }
  }
  return lines.join('\n')
}

/** rehype 插件：删除删除线（~~）渲染 */
function rehypeRemoveDel() {
  return (tree) => {
    visit(tree, 'element', (node, index, parent) => {
      if (node.tagName === 'del' && parent && typeof index === 'number') {
        // 将 <del> 内容展开为纯文本，删除 <del> 标签
        parent.children.splice(index, 1, ...(node.children || []))
      }
    })
  }
}

/** rehype 插件：将 .katex-display 包裹在横向滚动的 div 中 */
function rehypeWrapKatex() {
  return (tree) => {
    visit(tree, 'element', (node, index, parent) => {
      if (
        node.tagName === 'span' &&
        node.properties?.className?.includes('katex-display') &&
        parent &&
        typeof index === 'number'
      ) {
        parent.children[index] = {
          type: 'element',
          tagName: 'div',
          properties: {
            class: 'katex-scroll-wrap',
            style: 'overflow-x:auto;max-width:100%;-webkit-overflow-scrolling:touch;',
          },
          children: [node],
        }
      }
    })
  }
}

const processor = unified()
  .use(remarkParse)
  .use(remarkMath)
  .use(remarkGfm)
  .use(remarkBreaks)
  .use(remarkRehype, { allowDangerousHtml: false })
  .use(rehypeKatex, { throwOnError: false, strict: false })
  .use(rehypeRemoveDel)   // 删除 ~...~ 渲染
  .use(rehypeWrapKatex)  // 在 KaTeX 之后包裹滚动容器
  .use(rehypeHighlight)
  .use(rehypeStringify)

export function renderMarkdown(text) {
  if (!text) return ''
  try {
    // 确保标题前有换行，避免 remarkBreaks 吃掉 heading 标记
    const withHeadingBreaks = text.replace(/(\n)(#{1,6}\s)/g, '\n\n$2')
    const normalized = sanitizeOrphanAsterisks(withHeadingBreaks)
    const result = processor.processSync(normalized)
    return String(result)
  } catch {
    return ''
  }
}
