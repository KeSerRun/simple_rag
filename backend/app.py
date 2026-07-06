"""FastAPI 入口:装配中间件、挂载前端构建产物、注册各业务路由"""
import os
import time
import threading

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from base.config import conf
from base.logger import logger, log_http

# 注册业务路由(各文件内含 APIRouter,前缀均为 /api)
from api import admin, auth, documents, history, query, sessions
from api.auth import create_superusers


# ─── 请求统计（内存计数器，用于 Dashboard）────────────────────
class RequestStats:
    """线程安全的请求统计累加器"""

    def __init__(self):
        self._lock = threading.Lock()
        self.total_requests = 0
        self.total_errors = 0
        self.by_method: dict[str, int] = {}
        self.start_time = time.time()

    def record(self, method: str, path: str, status_code: int):
        with self._lock:
            self.total_requests += 1
            if status_code >= 400:
                self.total_errors += 1
            self.by_method[method.upper()] = self.by_method.get(method.upper(), 0) + 1


request_stats = RequestStats()

# 注入到 admin 模块供仪表盘使用
admin.request_stats = request_stats


# 创建 FastAPI 应用实例
app = FastAPI()

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    # 生产环境建议指定具体域名，如 ["http://localhost:3000"]
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# HTTP 请求日志中间件
@app.middleware("http")
async def log_requests(request: Request, call_next):
    response = await call_next(request)
    username = "-"
    if hasattr(request.state, "user") and request.state.user:
        username = request.state.user.get("username", "-")
    log_http(request.method, request.url.path, response.status_code, username)
    # 更新请求统计（排除 admin 自身对 dashboard 的请求）
    request_stats.record(request.method, request.url.path, response.status_code)
    return response

# 注册业务路由
app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(sessions.router)
app.include_router(history.router)
app.include_router(query.router)
app.include_router(documents.router)

# ─── 前端构建产物探测（仅读取 html_content，挂载延后以避免路由被拦截）─────
index_path = os.path.normpath(os.path.join(os.path.dirname(__file__), conf.index_file))
dist_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "dist"))
assets_path = os.path.join(dist_path, "assets")

html_content = None
if os.path.exists(index_path):
    logger.info(f"找到 index.html: {index_path}")
    with open(index_path, "r", encoding="utf-8") as f:
        html_content = f.read()
else:
    logger.warning(
        f"未找到前端构建产物 {index_path},/index 与静态资源将不可用。"
        "运行 `cd frontend && npm run build` 后重启即可启用。"
    )


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return JSONResponse(content={"status": "healthy"})


@app.get("/index")
async def index():
    """根路径,返回主页 HTML 内容(若前端未构建则返回 404 提示)"""
    if html_content is None:
        raise HTTPException(status_code=404, detail="frontend not built; run `cd frontend && npm run build`")
    return HTMLResponse(content=html_content, status_code=200)


# ─── 挂载前端静态资源（放在所有路由之后，避免 / 挂载截胡已注册的路由）──────
if html_content is not None and os.path.isdir(assets_path):
    app.mount("/assets", StaticFiles(directory=assets_path), name="assets")
    app.mount("/", StaticFiles(directory=dist_path, html=False), name="frontend_root")
    logger.info(f"已挂载前端构建产物: {dist_path}")
elif html_content is not None:
    logger.warning(
        f"未找到前端构建产物 {dist_path} 下的 assets 目录,静态资源将不可用。"
        "运行 `cd frontend && npm run build` 后重启即可启用。"
    )


if __name__ == "__main__":
    # 启动时根据配置文件中的超级管理员用户名和密码创建超级管理员账户
    create_superusers()
    from base.logger import logger
    logger.info(f"主页地址: http://127.0.0.1:11000/index")
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=11000)
