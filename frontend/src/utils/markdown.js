import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import katexPlugin from '@vscode/markdown-it-katex'

const md = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
  typographer: true,
  highlight(str, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(str, { language: lang }).value
      } catch { /* ignore */ }
    }
    return ''
  },
})

md.use(katexPlugin.default || katexPlugin, {
  throwOnError: false,
  errorColor: '#cc0000',
  strict: false,
})

const FENCE_RE = /^[ \t]{0,3}(?:```|~~~)/

/** 修补 LLM 常见的粗体/斜体星号泄露 */
function sanitizeOrphanAsterisks(text) {
  const lines = text.split('\n')
  let inFenced = false
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (FENCE_RE.test(line)) { inFenced = !inFenced; continue }
    if (inFenced) continue
    if (/^[ \t]{4,}/.test(line)) continue
    for (const suffix of ['***', '**', '*']) {
      const escaped = suffix.replace(/\*/g, '\\*')
      const trailing = line.match(RegExp(`${escaped}(\\s*)$`))
      if (!trailing) continue
      const rest = line.slice(0, line.length - trailing[0].length)
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

/** 归一化标准 LaTeX 分隔符: \[...\] → $$...$$, \(...\) → $...$ */
function normalizeLatexDelimiters(text) {
  text = text.replace(/\\\[([\s\S]+?)\\\]/g, (_, inner) => `$$${inner}$$`)
  text = text.replace(/\\\(([\s\S]+?)\\\)/g, (_, inner) => `$${inner}$`)
  return text
}

/** LaTeX 命令 → Unicode 手写字符替换 */
const LATEX_TO_UNICODE = new Map([
  ['\\alpha', 'α'], ['\\beta', 'β'], ['\\gamma', 'γ'], ['\\delta', 'δ'],
  ['\\epsilon', 'ε'], ['\\varepsilon', 'ε'], ['\\zeta', 'ζ'], ['\\eta', 'η'],
  ['\\theta', 'θ'], ['\\vartheta', 'θ'], ['\\iota', 'ι'], ['\\kappa', 'κ'],
  ['\\lambda', 'λ'], ['\\mu', 'μ'], ['\\nu', 'ν'], ['\\xi', 'ξ'],
  ['\\pi', 'π'], ['\\varpi', 'ϖ'], ['\\rho', 'ρ'], ['\\varrho', 'ϑ'],
  ['\\sigma', 'σ'], ['\\varsigma', 'ς'], ['\\tau', 'τ'], ['\\upsilon', 'υ'],
  ['\\phi', 'φ'], ['\\varphi', 'φ'], ['\\chi', 'χ'], ['\\psi', 'ψ'],
  ['\\omega', 'ω'],
  ['\\Gamma', 'Γ'], ['\\Delta', 'Δ'], ['\\Theta', 'Θ'], ['\\Lambda', 'Λ'],
  ['\\Xi', 'Ξ'], ['\\Pi', 'Π'], ['\\Sigma', 'Σ'], ['\\Phi', 'Φ'],
  ['\\Psi', 'Ψ'], ['\\Omega', 'Ω'],
  ['\\infty', '∞'], ['\\partial', '∂'], ['\\nabla', '∇'],
  ['\\dots', '…'], ['\\cdots', '…'], ['\\vdots', '⋮'], ['\\ddots', '⋱'],
  ['\\to', '→'], ['\\rightarrow', '→'], ['\\leftarrow', '←'],
  ['\\Rightarrow', '⇒'], ['\\Leftarrow', '⇐'], ['\\mapsto', '↦'],
  ['\\approx', '≈'], ['\\sim', '∼'], ['\\simeq', '≃'], ['\\equiv', '≡'],
  ['\\cong', '≅'], ['\\neq', '≠'], ['\\propto', '∝'], ['\\perp', '⊥'],
  ['\\mid', '∣'], ['\\parallel', '∥'],
  ['\\times', '×'], ['\\div', '÷'], ['\\pm', '±'], ['\\mp', '∓'],
  ['\\cdot', '·'], ['\\circ', '∘'],
  ['\\cup', '∪'], ['\\cap', '∩'], ['\\subset', '⊂'], ['\\supset', '⊃'],
  ['\\subseteq', '⊆'], ['\\supseteq', '⊇'],
  ['\\wedge', '∧'], ['\\vee', '∨'], ['\\oplus', '⊕'], ['\\otimes', '⊗'],
  ['\\forall', '∀'], ['\\exists', '∃'], ['\\neg', '¬'], ['\\emptyset', '∅'],
  ['\\in', '∈'], ['\\notin', '∉'], ['\\ni', '∋'],
  ['\\angle', '∠'], ['\\triangle', '△'], ['\\surd', '√'],
  ['\\ell', 'ℓ'], ['\\aleph', 'ℵ'], ['\\hbar', 'ℏ'],
  ['\\Re', 'ℜ'], ['\\Im', 'ℑ'],
  ['\\imath', 'ı'], ['\\jmath', 'ȷ'],
])

const LATEX_REPLACERS = Array.from(LATEX_TO_UNICODE.entries())
  .sort((a, b) => b[0].length - a[0].length)
  .map(([cmd, unicode]) => ({ pattern: new RegExp(cmd.replace(/\\/g, '\\\\').replace(/\$/g, '\\$'), 'g'), unicode }))

function replaceLatexWithUnicode(text) {
  for (const { pattern, unicode } of LATEX_REPLACERS) {
    text = text.replace(pattern, unicode)
  }
  return text
}

/** 剥离 LaTeX 纯文本命令 */
const TEXT_COMMANDS = [
  'text', 'mathrm', 'mathbf', 'textit', 'mathit', 'mathsf', 'mathtt',
  'mathcal', 'mathbb', 'mathfrak', 'operatorname',
]

function stripLatexTextCommands(text) {
  for (const cmd of TEXT_COMMANDS) {
    const pattern = new RegExp(`\\\\${cmd}(\\{)`, 'g')
    let match
    while ((match = pattern.exec(text)) !== null) {
      const start = match.index + match[0].length - 1
      const end = findMatchingBrace(text, start)
      if (end === -1) continue
      const inner = text.slice(start + 1, end)
      text = text.slice(0, match.index) + inner + text.slice(end + 1)
      pattern.lastIndex = 0
    }
  }
  for (const cmd of TEXT_COMMANDS) {
    text = text.replace(
      new RegExp(`\\\\${cmd}([A-Za-z0-9\\u4e00-\\u9fff]+)`, 'g'),
      (_, arg) => arg
    )
  }
  text = text.replace(/\\displaystyle|\\textstyle|\\limits|\\nolimits/g, '')
  return text
}

function findMatchingBrace(text, openPos) {
  if (text[openPos] !== '{') return -1
  let depth = 1
  for (let i = openPos + 1; i < text.length; i++) {
    if (text[i] === '{') depth++
    else if (text[i] === '}') {
      depth--
      if (depth === 0) return i
    }
  }
  return -1
}

/** 在 $$ 块内部修复 \frac 缺花括号 */
function fixupFracInMath(text) {
  return text.replace(/\$\$([\s\S]+?)\$\$/g, function(_, inner) {
    var s = inner
    // 1) \frac\max{...} → \frac{\max}{...}
    s = s.replace(/\\frac\\([a-zA-Z]+)/g, '\\frac{\\$1}')
    // 2) \fracBV → \frac{BV}
    s = s.replace(/\\frac([A-Za-z0-9]+)/g, '\\frac{$1}')
    // 3) \frac{...}_{...} → \frac{...}{_{...}}
    s = s.replace(/\\frac(\{[^}]*\})_{([^}]*)}/g, '\\frac{$1}{$2}')
    return '$$' + s + '$$'
  })
}

export function renderMarkdown(text) {
  if (!text) return ''
  try {
    var normalized = sanitizeOrphanAsterisks(text)
    normalized = normalizeLatexDelimiters(normalized)
    normalized = stripLatexTextCommands(normalized)
    normalized = fixupFracInMath(normalized)
    normalized = replaceLatexWithUnicode(normalized)
    return md.render(normalized)
  } catch {
    return md.utils.escapeHtml(text)
  }
}
