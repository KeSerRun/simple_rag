---
name: backtracking
description: 从极端具体的用户问题中提取关键信息,改写为更适合检索的回溯问题
include_identity: false
inputs:
  - query
---

你是一个聪明的助手,可以提取用户问题中的关键信息,并组织为一段更加简洁的回溯问题。
请根据用户的问题生成一个简洁、相关的回溯问题。

用户的问题是:
{query}

请生成一个适合用于检索的回溯问题。
