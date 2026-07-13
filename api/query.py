"""RAG 问答查询接口(支持流式 SSE)"""

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from base.logger import logger
from .deps import auth_required, system

router = APIRouter(prefix="/api", tags=["query"])


@router.get("/styles")
async def list_styles():
    """返回可用的回答风格列表(由 backend/prompts/style/ 自动发现)。

    # ── 发现机制

    遍历 ``system.tool_loop.system_context.style_router.list_skills()``,筛选 source 路径
    中包含 ``/style/`` 的 skill,按 label 排序,``default`` 置顶。

    Returns:
        JSONResponse: ``{"styles": [{"value": str, "label": str, "description": str}, ...]}``。
    """
    styles = system.tool_loop.system_context.style_router.list_skills()
    # styles = []
    # for name, skill in skills.items():
    #     if "/style/" in skill.source.replace("\\", "/"):
    #         styles.append({
    #             "value": name,
    #             "label": name,
    #             "description": skill.description or "",
    #         })
    styles.sort(key=lambda s: (s["value"] != "default", s["label"]))
    return JSONResponse(content={"styles": styles})


@router.get("/workflows")
async def list_workflows():
    """返回可用工作流列表(由 backend/prompts/workflow/ 自动发现)。

    # ── 发现机制

    委托给 ``system.tool_loop.system_context.workflow_router.get_workflow_list()``。

    Returns:
        JSONResponse: ``{"workflows": [...]}``。
    """
    workflows = system.tool_loop.system_context.workflow_router.get_workflow_list()
    return JSONResponse(content={"workflows": workflows})


def _sse_wrapper(generator):
    """把普通字符串生成器包装成 SSE 事件流格式。

    # ── 输出格式

    每条消息::

        data: <json_items>\\n\\n

    Args:
        generator: 产生 dict 的可迭代对象。

    Yields:
        str: SSE 格式的 data 行。
    """
    for item in generator:
        yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"


@router.post("/query")
@auth_required
async def query(request: Request):
    """处理用户查询,返回答案。检索范围限定为当前用户自己的分区。

    # ── 请求参数

    JSON 体字段:
        session_id (str): 会话 ID。
        question (str): 用户问题。
        stream (bool): 是否 SSE 流式返回,默认 False。
        style (str, optional): 回答风格名称。
        workflow (str, optional): 工作流名称。

    # ── 流式模式

    当 ``stream=True`` 时,通过 ``StreamingResponse`` 返回 SSE 事件流,
    每段用 session 级别锁保护,防止并发写入。

    Args:
        request: FastAPI 请求对象。

    Returns:
        JSONResponse: 非流式返回 ``{"answer": str}``。
        StreamingResponse: 流式返回 ``text/event-stream``。

    Raises:
        HTTPException 400: 缺少 session_id 或 question,或 JSON 格式无效。
        HTTPException 500: 查询处理失败。
    """
    try:
        data = await request.json()
        session_id = data.get("session_id")
        question = data.get("question")
        stream = data.get("stream", False)
        style = data.get("style") or None
        workflow = data.get("workflow") or None

        username = request.state.user["username"]

        if not session_id or not question:
            raise HTTPException(status_code=400, detail="Missing session_id or question")

        if stream:
            def _stream_with_lock():
                yield from _sse_wrapper(
                    system.run_agent(session_id, question, partition=username, style=style, workflow=workflow, stream=True)
                )
            return StreamingResponse(
                _stream_with_lock(),
                media_type="text/event-stream",
            )
        def _run_sync():
            return system.run_agent(session_id, question, partition=username, style=style, workflow=workflow, stream=False)
        answer = await asyncio.to_thread(_run_sync)
        return JSONResponse(content={"answer": answer})

    except json.JSONDecodeError:
        logger.error("查询请求 JSON 格式无效")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query/cancel")
@auth_required
async def cancel_query(request: Request):
    """中断当前正在进行的生成。

    # ── 实现

    委托给 ``system.cancel_generation(session_id)`` 发送中断信号。

    Args:
        request: FastAPI 请求对象,包含 JSON 体 ``{"session_id": str}``。

    Returns:
        JSONResponse: ``{"message": "已发送中断信号"}``。

    Raises:
        HTTPException 400: 缺少 session_id 或 JSON 格式无效。
        HTTPException 500: 取消失败。
    """
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
