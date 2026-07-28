# ── FastAPI 应用入口 ──────────────────────────────────────────────
"""FastAPI 应用入口：路由挂载、中间件、静态文件服务。

启动后端 HTTP 服务，注册管理、认证、会话、历史、查询、文档路由，
注入请求日志中间件与统计累加器。
"""

import glob
import mimetypes
import os
import time
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import jwt
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from base.config import conf
from base.logger import logger, log_http, configure_third_party_logging

from api import admin, auth, documents, health_check, history, query, sessions
from api.auth import create_superusers


# ── 请求统计 ──────────────────────────────────────────────────────


class RequestStats:
    """线程安全的请求统计累加器。

    在内存中记录请求总数、错误数、按 HTTP 方法分类的计数器，
    供管理后台仪表盘读取和展示。

    Attributes:
        _lock: 线程锁。
        total_requests: 总请求数。
        total_errors: 总错误数（状态码 >= 400）。
        by_method: 按 HTTP 方法统计的请求数字典。
        start_time: 应用启动时间戳。
    """

    def __init__(self):
        """初始化 RequestStats 实例。"""
        self._lock = threading.Lock()
        self.total_requests = 0
        self.total_errors = 0
        self.by_method: dict[str, int] = {}
        self.start_time = time.time()

    def record(self, method: str, path: str, status_code: int):
        """记录一次请求。

        每次请求处理完毕后调用此方法更新统计数据。

        Args:
            method: HTTP 方法（如 "GET"、"POST"）。
            path: 请求路径（如 "/api/health"）。
            status_code: HTTP 状态码（200 表示成功，>=400 计为错误）。
        """
        with self._lock:
            self.total_requests += 1
            if status_code >= 400:
                self.total_errors += 1
            self.by_method[method.upper()] = self.by_method.get(method.upper(), 0) + 1


request_stats = RequestStats()

admin.request_stats = request_stats


# ── 应用初始化 ────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """应用生命周期管理：启动时注入彩色日志到 uvicorn。"""
    configure_third_party_logging()
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """HTTP 请求日志记录中间件。

    在每个请求完成后记录日志和统计数据。

    Args:
        request: FastAPI Request 对象。
        call_next: 下一个处理环节的异步函数。

    Returns:
        响应对象。
    """
    response = await call_next(request)
    username = "-"
    if hasattr(request.state, "user") and request.state.user:
        username = request.state.user.get("username", "-")
    log_http(request.method, request.url.path, response.status_code, username)
    request_stats.record(request.method, request.url.path, response.status_code)
    return response


# ── 路由注册 ──────────────────────────────────────────────────────

app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(sessions.router)
app.include_router(history.router)
app.include_router(query.router)
app.include_router(documents.router)
app.include_router(health_check.router)

dist_path = conf.dist_dir
assets_path = conf.assets_dir
index_path = conf.index_file

html_content = None

if os.path.exists(index_path):
    logger.debug(f"找到 index.html: {index_path}")
    with open(index_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    # 桌面端注入标记，供前端判断是否隐藏登录/用户管理
    if conf.desktop_mode:
        html_content = html_content.replace(
            '</head>',
            '<script>window.__DESKTOP__=true</script></head>'
        )
else:
    logger.warning(
        f"未找到前端构建产物 {index_path},/index 与静态资源将不可用。"
        "运行 `cd frontend && npm run build` 后重启即可启用。"
    )


# ── 路由 ──────────────────────────────────────────────────────────


@app.get("/api/health")
async def health_check():
    """健康检查接口。

    用于检测后端服务是否正常运行，相当于一个"心跳"接口。
    不依赖任何外部服务，只要应用在运行就能返回正常状态。

    Returns:
        JSON 格式的响应 {"status": "healthy"}，状态码 200。
    """
    return JSONResponse(content={"status": "healthy"})


@app.get("/images/{img_name:path}")
async def serve_root_image(request: Request, img_name: str, token: str = Query(None)):
    """搜索并返回图片。处理 LLM 输出的 /images/hash.jpg 格式。

    Args:
        request: FastAPI 请求对象。
        img_name: 图片文件名（可包含子路径）。
        token: 可选 JWT token 查询参数。

    Returns:
        图片文件的 FileResponse。

    Raises:
        HTTPException 401: token 无效。
        HTTPException 404: 图片未找到。
    """
    auth_token = token
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        auth_token = auth_header.split(" ", 1)[1]
    if not auth_token:
        raise HTTPException(status_code=401, detail="missing token")
    try:
        jwt.decode(auth_token.encode("utf-8"), conf.jwt_secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid token")

    img_name = img_name.rstrip("/")
    if img_name.startswith("images/"):
        img_name = img_name[7:]

    search_pattern = str(Path(conf.data_dir) / "uploads" / "*" / "chunk_out" / "*" / "images" / img_name)
    candidates = glob.glob(search_pattern)
    if not candidates:
        raise HTTPException(status_code=404, detail="image not found")

    target = Path(candidates[0]).resolve()
    media_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return FileResponse(path=str(target), media_type=media_type)


@app.get("/")
async def index():
    """返回前端首页 HTML。

    Returns:
        HTMLResponse 内容。

    Raises:
        HTTPException 404: 前端未构建。
    """
    if html_content is None:
        raise HTTPException(status_code=404, detail="frontend not built; run `cd frontend && npm run build`")
    return HTMLResponse(content=html_content, status_code=200)


# ── 静态文件挂载 ──────────────────────────────────────────────────

if html_content is not None and os.path.isdir(assets_path):
    app.mount("/assets", StaticFiles(directory=assets_path), name="assets")
    app.mount("/", StaticFiles(directory=dist_path, html=False), name="frontend_root")
    logger.debug(f"已挂载前端构建产物: {dist_path}")
elif html_content is not None:
    logger.warning(
        f"未找到前端构建产物 {dist_path} 下的 assets 目录,静态资源将不可用。"
        "运行 `cd frontend && npm run build` 后重启即可启用。"
    )


# ── 主入口 ────────────────────────────────────────────────────────

if __name__ == "__main__":
    create_superusers()
    from base.logger import logger
    logger.info(f"主页地址: http://127.0.0.1:11000 (Press CTRL+RIGHT-CLICK to enter)")
    import uvicorn
    from base.logger import get_uvicorn_log_config
    uvicorn.run(app, host="0.0.0.0", port=11000, log_config=get_uvicorn_log_config())
