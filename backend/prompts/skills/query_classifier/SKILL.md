---
name: query_classifier
description: 判断用户查询是否需要从知识库中检索专业资料才能回答
include_identity: false
inputs:
  - needed
  - generic
  - query
---

你是一个查询意图分类器。判断下面这条用户查询是否需要从知识库中检索专业资料才能回答。

可选标签(只能从中二选一,直接输出标签词,不要解释):
- {needed}: 查询涉及具体业务/专业领域知识,需要从知识库中检索资料
- {generic}: 通用闲聊、常识、寒暄,或大模型自身知识即可回答

用户查询:
{query}

请直接输出标签词,不要任何解释。
