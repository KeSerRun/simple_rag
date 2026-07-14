# 提示词系统

> 位置：`prompts/` — LLM 身份、回答风格、工作流

## 目录结构

```
prompts/
├── identity.md          # 系统身份设定
├── style/               # 回答风格 (SkillLoader)
│   ├── default/
│   │   └── SKILL.md
│   ├── buffett/
│   │   └── SKILL.md
│   ├── elon-musk/
│   │   └── SKILL.md
│   ├── steve-jobs/
│   │   └── SKILL.md
│   ├── trump/
│   │   └── SKILL.md
│   └── zhangxuefeng/
│       └── SKILL.md
└── workflow/            # 工作流 (WorkflowRouter)
    ├── Briefing.md       # 简报
    ├── Comparison.md     # 对比分析
    ├── DeepResearch.md   # 深度研究
    ├── Autoplan.md       # 自动规划
    └── USstocks.md       # 美股分析
```

## identity.md — 系统身份

所有对话的 system prompt 基础。设定 LLM 的角色、能力和行为规范。

## Style — 回答风格

每类 skill 文件带 frontmatter：

```markdown
---
name: buffett
description: 用巴菲特的口吻回答
include_identity: true
inputs:
  - query
---
正文模板，支持 {query} 变量替换。
```

- 通过 `list_skills()` 获取可用风格列表
- `get_skill(name)` 获取具体模板
- `include_identity`: 是否在拼接时包含 identity

## Workflow — 工作流

多步骤执行指令，供 LLM 按步骤完成复杂任务。

```markdown
---
name: DeepResearch
description: 深度研究某个主题
max_tool_iter: 30
always_load: false
---
第一步：搜索知识库概览
第二步：联网补充最新信息
...
```

### 工作流文件字段

| 字段 | 说明 |
|------|------|
| `name` | 工作流名称 |
| `description` | 一句话描述 |
| `max_tool_iter` | 可选，覆盖全局工具迭代上限 |
| `always_load` | 是否无条件注入 system prompt |

## SkillLoader 与 WorkflowRouter

两个加载器均在 `agent/context.py` 中实现：

| 类 | 扫描目录 | 文件格式 | 主要接口 |
|----|---------|---------|---------|
| `SkillLoader` | `prompts/style/` | 扁平/嵌套 `.md` + frontmatter | `list_skills()`, `get_skill(name)` |
| `WorkflowRouter` | `prompts/workflow/` | 扁平 `.md` + frontmatter | `get_workflow_content(name)`, `get_workflow_summaries()`, `get_workflow_list()` |
