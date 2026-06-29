import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'

const md = new MarkdownIt({
  html: false,        // XSS 安全：不渲染原始 HTML
  breaks: true,       // 单个换行 → <br>
  linkify: true,      // 自动识别链接
  typographer: true,  // 智能引号
  highlight(str, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(str, { language: lang }).value
      } catch {
        /* ignore */
      }
    }
    return '' // 让 markdown-it 用 <code> 包裹
  },
})

/**
 * 渲染 Markdown → HTML，失败时返回转义原文
 */
export function renderMarkdown(text) {
  if (!text) return ''
  try {
    return md.render(text)
  } catch {
    return md.utils.escapeHtml(text)
  }
}
