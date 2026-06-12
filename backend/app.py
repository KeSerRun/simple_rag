# 导入 FastAPI 框架和相关模块
from fastapi import FastAPI, HTTPException, Request, Header
# 导入 StreamResponse 用于流式响应
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse
# 导入 StaticFiles 用于提供静态文件服务
from fastapi.staticfiles import StaticFiles
# 导入文件上传相关模块
from fastapi import FastAPI, File, UploadFile
#  导入 CORS 中间件用于处理跨域请求
from fastapi.middleware.cors import CORSMiddleware
# 导入json模块用于处理JSON数据
import json
# 导入集成系统类
from main import IntegratedSystem
# 导入配置对象
from base.config import conf
# 导入类型提示模块
from typing import List
# 导入文件系统模块
import os
# 导入 jwt 模块用于处理 JSON Web Tokens
import jwt
# 导入 functools 模块中的 wraps 函数用于创建装饰器
from functools import wraps
# 导入日志模块
from base.logger import logger

# 创建 FastAPI 应用实例
app = FastAPI()

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    # 生产环境建议指定具体域名，如 ["http://localhost:3000"]
    allow_origins=["*"],  
    allow_credentials=True,
    # 允许所有方法，包括 OPTIONS
    allow_methods=["*"],  
    # 允许所有请求头
    allow_headers=["*"],  
)

# 定义请求拦截器装饰器函数, 仅适用于POST请求
def interceptor(func):
    """一个装饰器函数，用于在调用被装饰的函数之前执行一些操作"""
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        # 在这里可以添加一些预处理逻辑，例如日志记录、权限检查等
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return JSONResponse(content={"message": "Unauthorized"}, status_code=401)
        token = auth_header.split(" ")[1] if auth_header else None
        payload = jwt.decode(token.encode('utf-8'), conf.jwt_secret_key, algorithms=['HS256'])
        if payload.get("role") != "admin":
            return JSONResponse(content={"message": "Unauthorized"}, status_code=401)
        # 从请求中获取 JSON 数据, await 关键字用于等待异步操作完成
        # 调用被装饰的函数，并等待其完成
        result = await func(request, *args, **kwargs)
        # 在这里可以添加一些后处理逻辑，例如结果处理、日志记录等
        return result
    return wrapper

# 创建集成系统实例
system = IntegratedSystem()

# 从文件中读入html主页
index_path = os.path.normpath(os.path.join(os.path.dirname(__file__), conf.index_file))
with open(index_path, "r", encoding="utf-8") as f:
    html_content = f.read()

# 定义静态文件目录路径，指向前端构建产物
dist_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))

# 挂载 /assets 目录
app.mount("/assets", StaticFiles(directory=os.path.join(dist_path, "assets")), name="assets")

# 包装生成器对象，使其满足 SSE 输出的格式要求
def sse_wrapper(generator):
    for item in generator:
        yield f"data: {item}\n\n"

@app.post("/api/register")
async def register(request: Request):
    """处理用户注册"""
    try:
        # 从请求中获取 JSON 数据, await 关键字用于等待异步操作完成
        data = await request.json()
        # 获取 username
        username = data.get("username")
        # 获取 password
        password = data.get("password")

        if not username or not password:
            raise HTTPException(status_code=400, detail="Missing username or password")
        if system.mysql_client.insert_user(username, password):
            return JSONResponse(content={"message": "Registration successful"})
        else:
            raise HTTPException(status_code=400, detail="Username already exists")

    except json.JSONDecodeError:
        logger.error("Invalid JSON format in register request")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except Exception as e:
        logger.error(f"Error in register: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# 启动时根据配置文件中的超级管理员用户名和密码创建超级管理员账户
def create_superusers():
    for superuser_username, superuser_password in zip(conf.superuser_usernames, conf.superuser_passwords):
        try:
            system.mysql_client.insert_user(superuser_username, superuser_password, role="admin")
            logger.info(f"Superuser '{superuser_username}' created successfully.")
        except Exception as e:
            logger.error(f"Error creating superuser '{superuser_username}': {str(e)}")

@app.post("/api/login")
async def login(request: Request):
    """处理用户登录"""
    try:
        # 从请求中获取 JSON 数据, await 关键字用于等待异步操作完成
        data = await request.json()
        # 获取 username 
        username = data.get("username")
        # 获取 password
        password = data.get("password")

        if not username or not password:
            raise HTTPException(status_code=400, detail="Missing username or password")

        # 验证用户凭据，如果验证成功则返回登录成功的响应，否则返回 401 错误
        if result := system.mysql_client.check_user_credentials(username, password):
            # 在这里可以生成并返回一个 JWT token 或其他认证信息
            token = jwt.encode({"username": result['username'], "role": result['role']}, conf.jwt_secret_key, algorithm="HS256")
            # 将 token 返回给客户端，客户端可以在后续请求中使用该 token 进行认证
            return JSONResponse(content={"message": "Login successful", "user": {"username": result['username'], "role": result['role']}, "token": token})
        else:
            raise HTTPException(status_code=401, detail="Invalid credentials")

    except json.JSONDecodeError:
        logger.error("Invalid JSON format in login request")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except Exception as e:
        logger.error(f"Error in login: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/create_session")
async def create_session(request: Request):
    """创建用户会话"""
    try:
        # 从请求中获取 JSON 数据, await 关键字用于等待异步操作完成
        data = await request.json()
        # 获取 session_id 
        session_id = data.get("session_id")
        # 获取 username
        username = data.get("username")

        if not session_id or not username:
            raise HTTPException(status_code=400, detail="Missing session_id or username")
        
        # 在 MySQL 数据库中创建一个新的会话记录，关联 session_id 和 username
        if system.mysql_client.insert_session(session_id, username):
            return JSONResponse(content={"message": "Session created successfully"})
        else:
            raise HTTPException(status_code=400, detail="Failed to create session")

    except json.JSONDecodeError:
        logger.error("Invalid JSON format in create_session request")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except Exception as e:
        logger.error(f"Error in create_session: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/query")
async def query(request: Request):
    """处理用户查询，返回答案"""
    try:
        # 从请求中获取 JSON 数据, await 关键字用于等待异步操作完成
        data = await request.json()
        # 获取 session_id 
        session_id = data.get("session_id")
        # 获取用户查询的问题文本
        question = data.get("question")
        # 获取是否启用流式输出的参数，默认为 False
        stream = data.get("stream", False) 
        # 获取用户名，以用户名为分区标识进行检索
        username = data.get("username") 
        # 如果 session_id 或 question 为空，则抛出 HTTP 400 错误
        if not session_id or not question:
            raise HTTPException(status_code=400, detail="Missing session_id or question")

        '''
        返回一个 StreamingResponse，使用 answer_generator 作为内容生成器
        SSE（Server-Sent Events）是一种服务器向客户端推送实时更新的技术，适用于需要持续更新数据的场景，如聊天应用、实时通知等。
        在这个例子中，answer_generator 是一个生成器函数，它会逐步生成答案的不同部分。
        StreamingResponse 会将这些部分逐步发送给客户端，而不是等待整个答案生成完成后一次性发送。
        这使得客户端能够更快地接收到答案的第一部分，并在后续部分生成时持续接收更新，从而提升用户体验。
        '''
        if stream:
            return StreamingResponse(sse_wrapper(system.answer_generator(session_id, question)), media_type="text/event-stream")
        else:
            return JSONResponse(content={"answer": system.get_answer(session_id, question)})

    except json.JSONDecodeError:
        logger.error("Invalid JSON format in query request")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except Exception as e:
        logger.error(f"Error in query: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/add_documents")
@interceptor
async def add_documents(request: Request):
    """添加文档到检索器"""
    try:
        data = await request.json()
        # 获取用户名
        username = data.get("username")
        # 获取文档路径
        documents_path = data.get("documents_path")
        # 如果文档路径列表为空，则抛出 HTTP 400 错误
        if not documents_path or not username:
            raise HTTPException(status_code=400, detail="No documents or username provided")
        # 处理文档路径，支持单个文件路径或目录路径
        documents_path = f"{conf.milvus_vector_store_path}/tmp/{username}/{data.get("documents_path", None)}"
        # 将文档添加到向量数据库中，供后续检索使用
        system.vector_store.store_documents_from_dir(documents_path)
        # 返回成功响应
        return JSONResponse(content={"message": "Documents added successfully"})
    except json.JSONDecodeError:
        logger.error("Invalid JSON format in add_documents request")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except Exception as e:
        logger.error(f"Error in add_documents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/clear_history")
async def clear_history(request: Request):
    """清除会话历史记录"""
    try:
        # 从请求中获取 JSON 数据, await 关键字用于等待异步操作完成
        data = await request.json()
        # 获取 session_id 
        session_id = data.get("session_id")
        # 如果 session_id 为空，则抛出 HTTP 400 错误
        if not session_id:
            raise HTTPException(status_code=400, detail="No session_id provided")
        # 清除 MySQL 数据库中与该 session_id 相关的历史记录
        system.mysql_client.delete_session_history(session_id)
        # 返回成功响应
        return JSONResponse(content={"message": "Session history cleared successfully"})
    except json.JSONDecodeError:
        logger.error("Invalid JSON format in clear_history request")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except Exception as e:
        logger.error(f"Error in clear_history: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/clear_documents")
@interceptor
async def clear_documents(request: Request):
    """清除用户文档"""
    try:
        # 从请求中获取 JSON 数据, await 关键字用于等待异步操作完成
        data = await request.json()
        # 获取 username
        username = data.get("username")
        # 如果 username 为空，则抛出 HTTP 400 错误
        if not username:
            raise HTTPException(status_code=400, detail="No username provided")
        # 清除向量数据库中与该 username 相关的文档
        system.vector_store.delete_documents_by_partition()
        # 返回成功响应
        return JSONResponse(content={"message": "User documents cleared successfully"})
    except json.JSONDecodeError:
        logger.error("Invalid JSON format in clear_documents request")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except Exception as e:
        logger.error(f"Error in clear_documents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/clear_chosed_documents")
@interceptor
async def clear_chosed_documents(request: Request):
    """清除选中的文档"""
    try:
        # 从请求中获取 JSON 数据
        data = await request.json()
        # 获取 username
        username = data.get("username")
        # 获取 sources
        sources = data.get("sources")
        # 如果 username 或 sources 为空，则抛出 HTTP 400 错误
        if not username or not sources:
            raise HTTPException(status_code=400, detail="No username or sources provided")
        # 清除向量数据库中与该 username 和 sources 相关的文档
        system.vector_store.delete_documents_by_sources(sources=sources)
        # 返回成功响应
        return JSONResponse(content={"message": "Selected documents cleared successfully"})
    except json.JSONDecodeError:
        logger.error("Invalid JSON format in clear_chosed_documents request")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except Exception as e:
        logger.error(f"Error in clear_chosed_documents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/history/{session_id}")
async def get_history(session_id: str):
    """获取会话历史记录"""
    try:
        # 从 MySQL 数据库中获取与该 session_id 相关的历史记录
        history = system.mysql_client.get_session_history(session_id)
        # 返回历史记录
        return JSONResponse(content={"history": history})
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON format in get_history: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except Exception as e:
        logger.error(f"Error in get_history: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sessions/{username}")
async def get_sessions(username: str):
    """获取用户相关的会话ID列表"""
    try:
        # 从 MySQL 数据库中获取与该 username 相关的会话列表
        sessions = system.mysql_client.fetch_sessions_by_username(username)
        # 返回会话列表
        return JSONResponse(content={"sessions": sessions})
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON format in get_sessions: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except Exception as e:
        logger.error(f"Error in get_sessions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话及相关数据"""
    try:
        # 从 MySQL 数据库中删除与该 session_id 相关的会话记录
        system.mysql_client.delete_session(session_id)
        # 从 MySQL 数据库中删除与该 session_id 相关的历史记录
        system.mysql_client.delete_session_history(session_id)
        # 返回成功响应
        return JSONResponse(content={"message": "Session and related data deleted successfully"})
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON format in delete_session: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except Exception as e:
        logger.error(f"Error in delete_session: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload")
@interceptor
async def upload_file(
    # HTTP 请求对象
    request: Request,
    # 上传文件列表
    files: List[UploadFile] = File(...),
    # X-Session-ID
    x_session_id: str = Header(None, alias="X-Session-ID"),
    # Username
    username: str = Header(None, alias="Username")
):
    try:
        # 获取 session_id，优先从请求头中获取，如果请求头中没有，则从 cookies 中获取
        session_id = x_session_id or request.cookies.get("session_id")
        # 获取 username，优先从请求头中获取，如果请求头中没有，则从 cookies 中获取
        username = username or request.cookies.get("username")
        # 如果 session_id 或 username 为空，则抛出 HTTP 400 错误
        if not session_id or not username:
            raise HTTPException(status_code=400, detail="缺少 session_id 或 username")

        results = []
        for file in files:
            # 读取上传的文件内容
            content = await file.read()
            # 定义文件保存路径
            save_path = f"{conf.milvus_vector_store_path}/tmp/{username}/{file.filename}"
            # 确保保存文件的目录存在，如果不存在则创建
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            # 将文件内容保存到指定路径
            with open(save_path, "wb") as f:
                f.write(content)
            
            # 返回结果
            results.append({
                "filename": file.filename,
                "size": len(content),
                "content_type": file.content_type
            })
        return JSONResponse(content={"files": results})
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON format in upload_file: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except Exception as e:
        logger.error(f"Error in upload_file: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# 上传文件并直接添加到向量数据库中
@app.post('/api/upload_embeddings')
@interceptor
async def upload_embeddings(
    # HTTP 请求对象
    request: Request,
    # 上传文件列表
    files: List[UploadFile] = File(...),
    # X-Session-ID
    x_session_id: str = Header(None, alias="X-Session-ID"),
    # Username
    username: str = Header(None, alias="Username")
):
    try:
        # 获取 session_id，优先从请求头中获取，如果请求头中没有，则从 cookies 中获取
        session_id = x_session_id or request.cookies.get("session_id")
        # 获取 username，优先从请求头中获取，如果请求头中没有，则从 cookies 中获取
        username = username or request.cookies.get("username")
        # 如果 session_id 或 username 为空，则抛出 HTTP 400 错误
        if not session_id or not username:
            raise HTTPException(status_code=400, detail="缺少 session_id 或 username")
        results = []
        for file in files:
            # 读取上传的文件内容
            content = await file.read()
            # 定义文件保存路径
            save_path = f"{conf.milvus_vector_store_path}/tmp/{username}/{file.filename}"
            # 确保保存文件的目录存在，如果不存在则创建
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            # 将文件内容保存到指定路径
            with open(save_path, "wb") as f:
                f.write(content)
            # 返回结果
            results.append({
                "filename": file.filename,
                "size": len(content),
                "content_type": file.content_type
            })
            system.vector_store.store_documents_from_dir(save_path)
        return JSONResponse(content={"files": results})
    
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON format in upload_embeddings: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except Exception as e:
        logger.error(f"Error in upload_embeddings: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/documents/{username}")
async def get_documents(username: str, request: Request=None):
    """获取用户相关的文档列表"""
    try:
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return JSONResponse(content={"message": "Unauthorized"}, status_code=401)
        token = auth_header.split(" ")[1] if auth_header else None
        payload = jwt.decode(token.encode('utf-8'), conf.jwt_secret_key, algorithms=['HS256'])
        if payload.get("role") != "admin":
            return JSONResponse(content={"message": "Unauthorized"}, status_code=401)
        # 从向量数据库中获取与该 username 相关的文档列表
        documents = system.vector_store.get_documents_by_partition()
        # 返回文档列表
        return JSONResponse(content={"documents": documents})
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON format in get_documents: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except Exception as e:
        logger.error(f"Error in get_documents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/health")
async def health_check():
    """健康检查"""
    try:
        return JSONResponse(content={"status": "healthy"})
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON format in health_check: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except Exception as e:
        logger.error(f"Error in health_check: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# 定义全局 HTTP 异常处理器，捕获所有 HTTPException 异常并返回 JSON 格式的错误响应
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """全局 HTTP 异常处理器"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

@app.get('/index')
async def index():
    """根路径，返回主页HTML内容"""
    try:
        return HTMLResponse(content=html_content, status_code=200)
    except Exception as e:
        logger.error(f"Error in index: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    

if __name__ == "__main__":
    # 启动时根据配置文件中的超级管理员用户名和密码创建超级管理员账户
    create_superusers()
    # 导入 uvicorn 异步服务器用于运行 FastAPI 应用
    import uvicorn
    # 启动 FastAPI 应用，监听在 11000 端口
    uvicorn.run(app, host="0.0.0.0", port=11000)