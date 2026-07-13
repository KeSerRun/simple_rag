"""RAG 问答查询接口(支持流式 SSE)"""

import asyncio
import json
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from base.logger import logger
from .deps import auth_required, system

router = APIRouter(prefix="/api", tags=["query"])


@router.get("/styles")
async def list_styles():
    """返回可用的回答风格列表（由 backend/prompts/style/ 自动发现）。"""
    skills = system.rag_qa.context_builder.skills
    styles = []  # 初始化一个空列表，用于存储筛选后的风格
    for name, skill in skills.items():
        if "/style/" in skill.source.replace("\\", "/"):
            styles.append({
                "value": name,              # 风格的值（用于前端提交）
                "label": name,              # 风格的显示标签
                "description": skill.description or "",  # 风格的描述，如果没有则为空字符串
            })
    styles.sort(key=lambda s: (s["value"] != "default", s["label"]))
    return JSONResponse(content={"styles": styles})


@router.get("/workflows")
async def list_workflows():
    """返回可用工作流列表（由 backend/prompts/workflow/ 自动发现）。"""
    workflows = system.rag_qa.workflow_router.get_workflow_list()
    return JSONResponse(content={"workflows": workflows})


# ===== SSE（Server-Sent Events）流式响应包装器 =====
def _sse_wrapper(generator):
    """把普通字符串生成器包装成 SSE `data: ...\n\n` 流。"""
    for item in generator:
        yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"


# ===== 处理用户问答请求的接口（核心接口） =====
@router.post("/query")
@auth_required
async def query(request: Request):
    """处理用户查询,返回答案。检索范围限定为当前用户自己的分区"""
    try:  # try 块开始，用于捕获可能发生的异常
        # ===== 解析前端传来的 JSON 请求体 =====
        data = await request.json()      # 使用 await 异步获取请求体中的 JSON 数据
        session_id = data.get("session_id")  # 从 JSON 中获取会话 ID（用于保持对话上下文）
        question = data.get("question")      # 从 JSON 中获取用户提出的问题
        stream = data.get("stream", False)   # 从 JSON 中获取是否使用流式响应，默认为 False
        style = data.get("style") or None    # 从 JSON 中获取回答风格，如果前端传空字符串或 null，统一转为 None
        workflow = data.get("workflow") or None  # 从 JSON 中获取工作流名称（Auto=None）

        username = request.state.user["username"]

        # ===== 参数校验 =====
        if not session_id or not question:  # 如果缺少 session_id 或 question
            raise HTTPException(status_code=400, detail="Missing session_id or question")

        # ===== 会话级锁：防止并发请求污染状态 =====
        lock = system.session_manager.get_lock(session_id)

        # ===== 根据是否流式选择不同的响应方式 =====
        if stream:
            def _stream_with_lock():
                with lock:
                    yield from _sse_wrapper(
                        system.run_agent(session_id, question, partition=username, style=style, workflow=workflow, stream=True)
                    )
            return StreamingResponse(
                _stream_with_lock(),
                media_type="text/event-stream",
            )
        def _run_sync():
            with lock:
                return system.run_agent(session_id, question, partition=username, style=style, workflow=workflow, stream=False)
        answer = await asyncio.to_thread(_run_sync)
        return JSONResponse(content={"answer": answer})

    # ===== 异常处理 =====
    except json.JSONDecodeError:  # 捕获 JSON 解析错误（前端传的不是合法的 JSON）
        logger.error("查询请求 JSON 格式无效")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== 中断生成接口 =====
@router.post("/query/cancel")
@auth_required
async def cancel_query(request: Request):
    """中断当前正在进行的生成。"""
    try:
        data = await request.json()
        session_id = data.get("session_id")
        if not session_id:
            raise HTTPException(status_code=400, detail="Missing session_id")
        system.cancel_generation(session_id)
        return JSONResponse(content={"message": "已发送中断信号"})
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消生成失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
