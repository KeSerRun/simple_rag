"""RAG 问答查询接口(支持流式 SSE)"""
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from base.logger import logger

from .deps import auth_required, system

router = APIRouter(prefix="/api", tags=["query"])


def _sse_wrapper(generator):
    """把普通字符串生成器包装成 SSE `data: ...\\n\\n` 流。
    token 内容用 JSON 编码，避免换行符等特殊字符破坏 SSE 帧结构。"""
    for item in generator:
        yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"


@router.post("/query")
@auth_required
async def query(request: Request):
    """处理用户查询,返回答案。检索范围限定为当前用户自己的分区"""
    try:
        data = await request.json()
        session_id = data.get("session_id")
        question = data.get("question")
        stream = data.get("stream", False)
        style = data.get("style") or None  # 前端传空字符串 / null 时统一视为 None
        # username 始终取自 token,作为检索分区使用
        username = request.state.user["username"]

        if not session_id or not question:
            raise HTTPException(status_code=400, detail="Missing session_id or question")

        if stream:
            return StreamingResponse(
                _sse_wrapper(system.answer_generator(session_id, question, partition=username, style=style)),
                media_type="text/event-stream",
            )
        return JSONResponse(content={
            "answer": system.get_answer(session_id, question, partition=username, style=style)
        })

    except json.JSONDecodeError:
        logger.error("Invalid JSON format in query request")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in query: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
