# ===== 文件说明 =====
# 这个文件是 RAG（检索增强生成）系统的问答接口模块
# 它提供 HTTP API 接口，让前端可以发送问题并获取答案
# 支持普通响应和流式 SSE（Server-Sent Events）响应
"""RAG 问答查询接口(支持流式 SSE)"""

# ===== 导入 Python 标准库 =====
import json  # 导入 json 模块，用于处理 JSON 格式的数据（序列化/反序列化）
import os    # 导入 os 模块，用于与操作系统交互（如文件路径、环境变量等）

# ===== 导入 FastAPI 相关组件 =====
from fastapi import APIRouter, HTTPException, Request  # 导入路由、HTTP 异常类和请求对象
from fastapi.responses import JSONResponse, StreamingResponse  # 导入 JSON 响应和流式响应类

# ===== 导入项目内部模块 =====
from base.logger import logger  # 从 base 包导入日志记录器，用于记录日志信息

# ===== 导入当前包的依赖模块 =====
from .deps import auth_required, system  # 从当前包下的 deps.py 导入认证装饰器和系统实例

# ===== 创建路由对象 =====
# APIRouter 是 FastAPI 的路由器，用于将不同的 API 接口组织在一起
# prefix="/api" 表示所有通过此路由注册的接口路径前都会自动加上 /api
# tags=["query"] 用于在 API 文档中分组显示
router = APIRouter(prefix="/api", tags=["query"])


# ===== 获取回答风格列表的接口 =====
@router.get("/styles")  # 使用 GET 方法注册路由，路径为 /api/styles
async def list_styles():  # 定义异步函数，用于处理获取风格列表的请求
    """返回可用的回答风格列表（由 backend/prompts/style/ 自动发现）。"""
    # 从系统实例的 RAG 问答模块中获取上下文构建器，再获取所有可用的 skill（技能/风格）
    skills = system.rag_qa.context_builder.skills
    styles = []  # 初始化一个空列表，用于存储筛选后的风格
    # 遍历 skills 字典，name 是风格名称, skill 是风格对象
    for name, skill in skills.items():
        # 将 skill.source 中的反斜杠替换为正斜杠，然后判断是否包含 "/style/"
        # 只有来自 style 目录的才算作"回答风格"
        if "/style/" in skill.source.replace("\\", "/"):
            # 将符合条件的风格信息添加到 styles 列表中
            styles.append({
                "value": name,              # 风格的值（用于前端提交）
                "label": name,              # 风格的显示标签
                "description": skill.description or "",  # 风格的描述，如果没有则为空字符串
            })
    # 默认排第一：将名为 "default" 的风格排到最前面
    # key=lambda s: (s["value"] != "default", s["label"]) 的意思是：
    # 先按"是否不是 default"排序（False 即 default 排前面），再按标签字母顺序排序
    styles.sort(key=lambda s: (s["value"] != "default", s["label"]))
    # 返回 JSON 格式的响应，包含 styles 列表
    return JSONResponse(content={"styles": styles})


# ===== SSE（Server-Sent Events）流式响应包装器 =====
def _sse_wrapper(generator):  # 定义私有函数，用于将生成器包装成 SSE 格式
    """把普通字符串生成器包装成 SSE `data: ...\n\n` 流。
    token 内容用 JSON 编码，避免换行符等特殊字符破坏 SSE 帧结构。"""
    # 遍历生成器产生的每一个数据项
    for item in generator:
        # 将每个数据项用 json.dumps 编码为 JSON 字符串（确保中文不乱码）
        # 然后按照 SSE 协议格式包装：以 "data: " 开头，以两个换行符结尾
        yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"


# ===== 处理用户问答请求的接口（核心接口） =====
@router.post("/query")  # 使用 POST 方法注册路由，路径为 /api/query
@auth_required          # 使用认证装饰器，要求用户必须登录才能访问此接口
async def query(request: Request):  # 定义异步函数，参数是 FastAPI 的 Request 对象
    """处理用户查询,返回答案。检索范围限定为当前用户自己的分区"""
    try:  # try 块开始，用于捕获可能发生的异常
        # ===== 解析前端传来的 JSON 请求体 =====
        data = await request.json()      # 使用 await 异步获取请求体中的 JSON 数据
        session_id = data.get("session_id")  # 从 JSON 中获取会话 ID（用于保持对话上下文）
        question = data.get("question")      # 从 JSON 中获取用户提出的问题
        stream = data.get("stream", False)   # 从 JSON 中获取是否使用流式响应，默认为 False
        style = data.get("style") or None    # 从 JSON 中获取回答风格，如果前端传空字符串或 null，统一转为 None

        # ===== 获取当前用户信息 =====
        # username 始终取自 JWT token，作为检索分区的依据
        # 这样不同用户只能检索到自己上传的文档
        username = request.state.user["username"]

        # ===== 参数校验 =====
        if not session_id or not question:  # 如果缺少 session_id 或 question
            # 抛出 HTTP 400 错误（请求参数不合法）
            raise HTTPException(status_code=400, detail="Missing session_id or question")

        # ===== 根据是否流式选择不同的响应方式 =====
        if stream:  # 如果前端请求使用流式响应
            # 返回 StreamingResponse（流式 HTTP 响应）
            return StreamingResponse(
                # 调用 system.answer_generator 获取流式生成器，并用 _sse_wrapper 包装成 SSE 格式
                # session_id: 会话ID，question: 用户问题，partition=username: 按用户名分区检索
                # style=style: 指定回答风格
                _sse_wrapper(system.answer_generator(session_id, question, partition=username, style=style)),
                media_type="text/event-stream",  # 设置媒体类型为 SSE 流
            )
        # 非流式模式：直接返回完整的 JSON 响应
        return JSONResponse(content={
            # 调用 system.get_answer 获取完整的回答内容
            "answer": system.get_answer(session_id, question, partition=username, style=style)
        })

    # ===== 异常处理 =====
    except json.JSONDecodeError:  # 捕获 JSON 解析错误（前端传的不是合法的 JSON）
        logger.error("查询请求 JSON 格式无效")
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
