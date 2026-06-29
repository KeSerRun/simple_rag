---
name: query-classifier
description: 结合对话上下文判断用户查询是否需要从知识库中检索
include_identity: false
inputs:
  - needed
  - generic
  - context
---

根据以下上下文，判断用户是否需要从知识库中检索专业资料才能回答。只输出标签名，不要解释。

- **{needed}**：查询涉及专业知识、文档内容、上传文件中的信息，必须检索知识库
- **{generic}**：问候、闲聊、纯常识问题，无需检索也可回答

## 判断线索

- 如果上下文中有 `<operation：upload files: ...>` 标记且用户问题与文件内容相关 → {needed}
- 如果用户只是打招呼、闲聊、问通用常识 → {generic}

{context}
