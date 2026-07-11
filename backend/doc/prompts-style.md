# 回答风格 Skills

`prompts/style/` 下每个子目录对应一种回答风格，每个风格是一个独立的 `SKILL.md` 文件。

## 目录结构

```
style/
├── README.md           ← 本文档
├── default/            ← 默认风格
├── buffett/            ← 巴菲特视角
├── elon-musk/          ← 埃隆·马斯克视角
├── steve-jobs/         ← 史蒂夫·乔布斯视角
├── trump/              ← 特朗普视角
└── zhangxuefeng/       ← 张雪峰视角
```

## SKILL.md 规范

### 文件格式

每个 `SKILL.md` 必须包含 YAML frontmatter 和 Markdown 正文：

```markdown
---
name: style-name
description: |
  简短描述该风格的特点（前端下拉框显示此项）
---

## 风格要求：风格名称

风格的具体要求和规则，使用 Markdown 编写。
```

### Frontmatter 字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | 是 | 风格唯一标识，用于前后端通信（如 `buffett`） |
| `description` | 是 | 中文描述，前端下拉框显示为此值，建议 10-30 字 |

`description` 支持单行和 `|` 多行两种 YAML 语法。

### 内容规范

1. **仅包含回答方式和性格特征** — 描述该人物的思维模型、表达风格、价值观，不要包含调用工具、搜索数据、联网查询等指令
2. **以用户为中心** — 风格应控制的是「如何回答」，而非「回答什么」
3. **可叠加** — style 内容会被追加到 system message 的 identity.md 之后，与 identity.md 中的工具规则和回答规则叠加生效
4. **Markdown 格式** — 使用标准 Markdown 编写，支持标题、列表、表格、代码块等
5. **不重复 identity.md** — 不要在 style 中重复 identity.md 已有的工具使用规则、引用格式要求等

### 添加新风格

1. 在 `style/` 下创建新目录，如 `my-style/`
2. 创建 `SKILL.md`，按要求填写 frontmatter 和正文
3. 重启后端，前端下拉框会自动出现新选项

无需修改任何 Python 代码或前端文件。

### 示例

```markdown
---
name: my-style
description: |
  我的风格描述
---

## 风格要求：我的风格

1. **第一条规则**：描述
2. **第二条规则**：描述
```

## 技术说明

- Style 文件通过 `ContextBuilder` 自动加载，注册名由 frontmatter 的 `name` 字段决定
- 前端通过 `GET /api/styles` 获取可用风格列表，`label` 字段取自 `description`
- 选中风格后，该 `description` 对应的内容注入到 system message 尾部
- `name: default` 不会被注入（作为"无额外风格"的兜底）
