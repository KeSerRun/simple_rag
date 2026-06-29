---
name: rerank
description: 对若干候选文档与用户问题的相关性打分,用于 LLM listwise rerank
include_identity: false
inputs:
  - query
  - n
  - docs
---

你是一个相关性评分器。请阅读用户问题和候选文档,对每个文档与问题的相关性打 0-10 分(10 最相关)。

用户问题:
{query}

候选文档(共 {n} 条):
{docs}

请只输出一行,格式为逗号分隔的 {n} 个整数评分,顺序与候选文档对应,不要任何解释,例如: 9,3,7,0,6
