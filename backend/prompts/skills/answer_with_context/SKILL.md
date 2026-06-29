---
name: answer_with_context
description: 基于知识库上下文生成最终答案
include_identity: true
inputs:
  - context
  - query
---

知识库中的信息如下:
{context}

用户的问题是:
{query}
