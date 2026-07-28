"""健康检查接口：返回各外部依赖的完整状态。"""

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from base.health import run_all
from .deps import system

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/check")
async def health_check():
    """完整依赖健康检查。

    依次检测 Chat API、Embedding API、MinerU、向量库，
    汇总各组件状态和延迟。

    Returns:
        JSON::

            {
              "status": "healthy" | "degraded" | "unhealthy",
              "checks": {
                "chat":       { "status": ..., "latency_ms": ... },
                "embedding":  { "status": ..., "latency_ms": ..., "dimension": ... },
                "mineru":     { "status": ..., "note": ... },
                "vector_store": { "status": ..., "chunks": ..., "dimension": ... }
              }
            }
    """
    loop = asyncio.get_running_loop()

    def _sync():
        return run_all(
            chat_client=system.chat_client,
            embed_client=system.embed_client,
            vector_store=system.vector_store,
        )

    result = await loop.run_in_executor(None, _sync)
    return JSONResponse(content=result)
