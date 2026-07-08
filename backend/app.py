# =============================================================================
# FastAPI 应用主入口文件
# 作用: 创建 FastAPI 应用实例、装配中间件、挂载前端静态资源、注册所有业务路由
# 整个后端服务的启动点，所有请求都从这里经过
# =============================================================================

# ===== 标准库导入 =====
import os  # 导入 os 模块，用于操作文件和路径，比如拼接路径、判断文件是否存在
import time  # 导入 time 模块，用于获取当前时间戳，这里用来记录服务启动时间
import threading  # 导入 threading 模块，用于创建线程锁，保证多线程环境下的数据安全

# ===== FastAPI 相关导入 =====
from fastapi import FastAPI, HTTPException, Request  # 导入 FastAPI 主类、HTTP 异常类、请求对象类
from fastapi.middleware.cors import CORSMiddleware  # 导入跨域中间件，允许前端跨域请求后端接口
from fastapi.responses import HTMLResponse, JSONResponse  # 导入响应类：HTMLResponse 返回 HTML 页面，JSONResponse 返回 JSON 数据
from fastapi.staticfiles import StaticFiles  # 导入静态文件挂载类，用于让 FastAPI 托管前端构建产物（JS/CSS/图片等）

# ===== 项目内部模块导入 =====
from base.config import conf  # 从项目的配置文件模块导入 conf 对象，里面存放了所有配置项（如 index.html 路径等）
from base.logger import logger, log_http  # 从日志模块导入: logger 用来打印日志, log_http 用来记录 HTTP 请求日志

# ===== 注册业务路由 =====
# 从 api 包中导入各个业务模块，每个模块内部都有一个 APIRouter 对象，路由前缀都是 /api
# 这些模块分别负责：管理员功能、登录认证、文档管理、历史记录、智能问答、会话管理
from api import admin, auth, documents, history, query, sessions
from api.auth import create_superusers  # 从认证模块导入创建超级管理员的函数，启动时调用


# ===== 请求统计类（内存计数器，用于 Dashboard 仪表盘展示）========================================
class RequestStats:
    """
    线程安全的请求统计累加器
    作用: 在内存中记录总共处理了多少请求、出错了多少次、每种 HTTP 方法分别有多少次
    这些数据会被管理后台的仪表盘页面读取和展示
    """

    def __init__(self):
        """
        初始化方法，创建 RequestStats 实例时自动调用
        这里初始化了线程锁、请求总数、错误总数、按 HTTP 方法分类的计数器、启动时间
        """
        self._lock = threading.Lock()  # 创建一把线程锁，防止多线程同时修改计数器导致数据错乱
        self.total_requests = 0  # 记录从服务启动以来总共处理了多少次请求，初始为 0
        self.total_errors = 0  # 记录从服务启动以来发生了多少次错误（HTTP 状态码 >= 400），初始为 0
        self.by_method: dict[str, int] = {}  # 用字典记录每种 HTTP 方法（GET/POST/PUT/DELETE 等）分别有多少次请求
        self.start_time = time.time()  # 记录服务启动时的时间戳，用于计算服务运行时长

    def record(self, method: str, path: str, status_code: int):
        """
        记录一次请求
        每次有请求处理完毕，就调用这个方法更新统计数据

        参数:
            method: HTTP 方法，比如 "GET"、"POST"
            path: 请求的路径，比如 "/api/health"
            status_code: HTTP 状态码，比如 200 表示成功，404 表示未找到，500 表示服务器错误
        """
        with self._lock:  # 用 with 语句获取线程锁，确保同一时刻只有一个线程能修改计数器
            self.total_requests += 1  # 请求总数加 1，表示又处理了一个请求
            if status_code >= 400:  # 如果状态码 >= 400（表示客户端错误或服务器错误）
                self.total_errors += 1  # 错误总数加 1
            # 获取当前 HTTP 方法对应的请求次数，如果没有则默认为 0，然后加 1 后再存回去
            self.by_method[method.upper()] = self.by_method.get(method.upper(), 0) + 1


# ===== 创建一个全局唯一的请求统计实例 =====
# 这个实例会在整个应用生命周期内工作，记录所有经过的请求
request_stats = RequestStats()

# ===== 将统计实例注入到 admin 模块 =====
# 把 request_stats 赋值给 admin 模块的 request_stats 属性
# 这样 admin 模块里的仪表盘接口就能读取统计数据，展示在管理后台页面上
admin.request_stats = request_stats


# ===== 创建 FastAPI 应用实例 =====
# app 是整个后端服务的核心对象，所有路由、中间件、生命周期事件都注册在它上面
app = FastAPI()

# ===== 添加 CORS 跨域中间件 =====
# CORS 全称"跨域资源共享"，用于解决前端页面在浏览器中请求不同域名/端口时的跨域问题
# 如果不配置这个中间件，前端（比如运行在 3000 端口的 Vue 开发服务器）无法请求后端 API
app.add_middleware(
    CORSMiddleware,  # 告诉 FastAPI 使用 CORS 中间件
    # 允许所有来源跨域访问，生产环境建议改成具体的前端域名，比如 ["http://localhost:3000"]
    # 当前开发阶段用 "*" 通配符表示允许任何域名访问，方便调试
    allow_origins=["*"],
    allow_credentials=True,  # 允许跨域请求携带 Cookie 等凭证信息
    allow_methods=["*"],  # 允许所有 HTTP 方法（GET、POST、PUT、DELETE 等）
    allow_headers=["*"],  # 允许所有请求头
)

# ===== HTTP 请求日志中间件 =====
# 这个中间件拦截所有 HTTP 请求，在请求处理完毕后记录日志
# @app.middleware("http") 是 FastAPI 提供的装饰器语法，将一个函数注册为 HTTP 中间件
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    HTTP 请求日志记录中间件
    每个请求经过这个中间件时，会先继续往下执行（调用 call_next），
    等拿到响应结果后，再记录日志和统计数据。

    参数:
        request: FastAPI 的 Request 对象，包含了请求的方法、路径、参数等信息
        call_next: 下一个处理环节的异步函数，调用它才能继续处理请求并拿到响应

    返回:
        response: 经过后续处理得到的响应对象
    """
    # 调用 call_next，让请求继续往下流转（经过路由处理等），然后拿到响应结果
    # await 表示这是一个异步操作，需要等待结果
    response = await call_next(request)
    # 默认用户名为 "-"，表示未登录或匿名用户
    username = "-"
    # 检查请求状态中是否有 user 信息（认证中间件会在登录后把用户信息存到 request.state.user 里）
    if hasattr(request.state, "user") and request.state.user:
        # 如果有用户信息，就从字典中取出 username，如果没有则仍然显示 "-"
        username = request.state.user.get("username", "-")
    # 调用 log_http 函数，把请求的 HTTP 方法、路径、状态码、用户名记录到日志文件中
    log_http(request.method, request.url.path, response.status_code, username)
    # 更新请求统计数据（这里排除了 admin 自身对 dashboard 的请求）——不过当前并没有排除逻辑
    request_stats.record(request.method, request.url.path, response.status_code)
    # 将响应返回给上一级中间件或客户端
    return response

# ===== 注册业务路由 =====
# 将各个业务模块中的路由注册到 FastAPI 应用上
# 每个模块内部都定义了一个 APIRouter 对象（比如 admin.router），里面包含了该模块的所有接口
# .include_router() 方法会把这些接口注册到 FastAPI 应用的路由表中
app.include_router(admin.router)  # 注册管理员相关路由，比如用户管理、仪表盘数据等
app.include_router(auth.router)  # 注册认证相关路由，比如登录、登出、注册等
app.include_router(sessions.router)  # 注册会话相关路由，比如创建/管理聊天会话
app.include_router(history.router)  # 注册历史记录相关路由，比如查看聊天历史
app.include_router(query.router)  # 注册智能问答相关路由，比如发起问答请求
app.include_router(documents.router)  # 注册文档管理相关路由，比如上传文档、查看文档列表

# ===== 前端构建产物探测（先读取 HTML 内容，静态资源挂载延后以避免路由被拦截）========================
# 获取 index.html 文件的绝对路径
# os.path.dirname(__file__) 获取当前文件（app.py）所在目录的路径
# conf.index_file 是从配置文件中读取的 index.html 相对路径
# os.path.join 将两个路径拼接成一个完整路径
# os.path.normpath 标准化路径（把正反斜杠统一）
index_path = os.path.normpath(os.path.join(os.path.dirname(__file__), conf.index_file))

# 获取前端构建产物的"dist"目录的绝对路径
# 前端项目构建后，所有文件会打包到 dist 目录下
dist_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "dist"))

# 获取 dist/assets 目录的路径，这里面存放前端构建后的 JS、CSS、图片等静态资源
assets_path = os.path.join(dist_path, "assets")

# 初始化 html_content 变量，默认为 None
# 如果找到了 index.html 文件，就读取其内容存到这个变量中
html_content = None

# 判断 index.html 文件是否存在
if os.path.exists(index_path):
    # 如果存在，用日志记录找到 index.html 的信息，并输出路径方便调试
    logger.debug(f"找到 index.html: {index_path}")
    # 以只读模式打开 index.html 文件，并指定编码为 UTF-8（支持中文等字符）
    with open(index_path, "r", encoding="utf-8") as f:
        # 读取文件的全部内容，保存到 html_content 变量中
        html_content = f.read()
else:
    # 如果 index.html 不存在，记录一条警告日志
    logger.warning(
        f"未找到前端构建产物 {index_path},/index 与静态资源将不可用。"
        "运行 `cd frontend && npm run build` 后重启即可启用。"
    )


# ===== 健康检查接口 =====
# 定义一个 GET 请求接口，路径为 /api/health
# 前端或其他监控系统可以定期调用这个接口，检查后端服务是否正常运行
@app.get("/api/health")
async def health_check():
    """
    健康检查接口
    用于检测后端服务是否正常运行，相当于一个"心跳"接口
    不依赖任何外部服务，只要应用在运行就能返回正常状态

    返回:
        JSON 格式的响应，内容为 {"status": "healthy"}，状态码默认为 200
    """
    # 返回一个 JSON 响应，表明服务运行正常
    return JSONResponse(content={"status": "healthy"})


# ===== 首页路由 =====
# 定义一个 GET 请求接口，路径为 /index
# 访问这个路径会返回前端构建的首页 HTML 内容
# 如果前端还没有构建，则返回 404 错误提示用户先构建前端
@app.get("/index")
async def index():
    """
    返回前端首页 HTML 页面
    当用户访问 /index 时，返回存储在 html_content 变量中的 HTML 内容

    如果 html_content 为 None（说明前端没有构建），就返回 404 错误

    返回:
        成功: HTML 格式的页面内容，状态码 200
        失败: JSON 格式的错误信息，状态码 404
    """
    # 检查 html_content 是否为 None（即 index.html 文件不存在或未读取成功）
    if html_content is None:
        # 如果不存在，抛出一个 HTTP 404 异常，告诉用户需要先构建前端项目
        raise HTTPException(status_code=404, detail="frontend not built; run `cd frontend && npm run build`")
    # 如果存在，以 HTML 格式返回页面内容，状态码为 200（成功）
    return HTMLResponse(content=html_content, status_code=200)


# ===== 挂载前端静态资源 =====
# 这段代码放在所有路由注册的后面，目的是避免 / 路径的静态文件挂载截胡已注册的 API 路由
# 也就是说，先让 API 路由注册好，然后再挂载静态文件，这样请求进来时会先匹配到 API 路由
# ===== 判断是否挂载静态资源 =====
# 条件1: html_content 不为 None（说明 index.html 存在）
# 条件2: assets 目录确实是一个目录（os.path.isdir 判断路径是否为有效的目录）
if html_content is not None and os.path.isdir(assets_path):
    # 挂载 /assets 路径，将 assets 目录下的静态文件（JS、CSS、图片等）对外提供访问
    # 这样前端页面中引用的 /assets/xxx.js 就能被正确加载
    app.mount("/assets", StaticFiles(directory=assets_path), name="assets")
    # 挂载根路径 /，将 dist 目录下所有文件对外提供访问
    # html=False 表示不把 index.html 作为默认首页（因为首页由上面的 /index 路由单独处理）
    # 这个挂载用于提供前端中用到的其他静态资源
    app.mount("/", StaticFiles(directory=dist_path, html=False), name="frontend_root")
    # 记录日志，说明前端静态资源已成功挂载
    logger.debug(f"已挂载前端构建产物: {dist_path}")
# 如果 index.html 存在但 assets 目录不存在（说明前端构建不完整或目录结构变了）
elif html_content is not None:
    # 记录警告日志，告诉用户 assets 目录没找到，静态资源无法正常加载
    logger.warning(
        f"未找到前端构建产物 {dist_path} 下的 assets 目录,静态资源将不可用。"
        "运行 `cd frontend && npm run build` 后重启即可启用。"
    )


# ===== 程序主入口 =====
# 判断当前文件是否作为主程序运行（而不是被其他文件导入）
# __name__ 是 Python 内置变量，当文件直接运行时值为 "__main__"
if __name__ == "__main__":
    # 调用创建超级管理员的函数
    # 该函数会读取配置文件中的超级管理员用户名和密码，如果数据库中还没有就创建
    # 这样每次启动服务时都能确保超级管理员账号存在
    create_superusers()
    # 从日志模块再次导入 logger（虽然是重复导入，但 Python 会缓存模块，不影响性能）
    from base.logger import logger
    # 打印主页地址的日志，方便开发者点击访问
    # 这里写死了 127.0.0.1 和 11000 端口，实际生产环境可能需要从配置读取
    logger.info(f"主页地址: http://127.0.0.1:11000/index")
    # 导入 uvicorn（ASGI 服务器，用于运行 FastAPI 应用）
    import uvicorn
    # 使用 uvicorn 启动 FastAPI 应用
    # app: 要运行的 FastAPI 应用实例
    # host="0.0.0.0": 监听所有网络接口，这样局域网内其他设备也能访问
    # port=11000: 监听 11000 端口
    uvicorn.run(app, host="0.0.0.0", port=11000)
