"""管理后台 API - 数据库（向量存储）统计与系统数据上传"""
# ===== 上面是模块文档字符串 =====
# 这个文件是管理后台的API路由，提供数据库（向量存储）的统计信息查询、切块详情查看、
# 文档完整性检查、系统数据上传和删除等功能。

# ===== 导入 Python 内置模块 =====
import glob      # 导入 glob 模块，用于文件路径模式匹配（比如查找符合某个模式的所有文件）
import os        # 导入 os 模块，用于操作系统相关的功能（文件路径、目录操作等）
import shutil    # 导入 shutil 模块，用于高级文件操作（比如删除整个目录树）
import uuid as _uuid  # 导入 uuid 模块并重命名为 _uuid，用于生成唯一标识符（上传任务 ID）
from pathlib import Path  # 从 pathlib 导入 Path 类，用面向对象的方式操作文件路径

# ===== 导入项目内部模块 =====
from . import router           # 从当前包（admin 目录）导入 router 对象，用于注册 API 路由
from . import SYSTEM_PARTITION, _upload_tasks  # 从当前包导入系统分区常量 和 上传任务字典（用于跟踪上传状态）
from ..deps import admin_required, auth_required, system  # 从父级 deps 模块导入：管理员权限校验、认证校验、系统实例
from base.config import conf    # 从 base.config 导入配置对象 conf，读取项目配置（如向量存储目录）
from base.logger import logger  # 从 base.logger 导入日志记录器 logger，用于输出日志信息

# ===== 导入 FastAPI 相关模块 =====
from fastapi import File, HTTPException, Query, Request, UploadFile  # 导入 FastAPI 的常用工具：文件上传、HTTP 异常、查询参数、请求对象、上传文件类
from fastapi.responses import JSONResponse  # 从 fastapi.responses 导入 JSONResponse，用于返回 JSON 格式的响应


# ===== API 路由：获取向量数据库统计信息 =====
@router.get("/database")          # 注册一个 GET 请求的路由，路径为 /database
@auth_required                    # 装饰器：要求用户必须经过身份认证才能访问
@admin_required                   # 装饰器：要求用户必须是管理员才能访问
async def get_database_stats(request: Request):  # 定义异步函数 get_database_stats，参数是 FastAPI 的 Request 对象
    """向量库统计: 总切块数、按分区/来源分布、嵌入维度"""  # 函数的文档字符串，说明这个接口的功能
    try:  # 开始 try 异常捕获，防止程序崩溃
        vs = system.vector_store  # 从全局 system 对象中获取向量存储实例，赋值给变量 vs
        if not vs:  # 如果向量存储实例不存在（None 或空）
            return JSONResponse(content={  # 返回一个 JSON 响应，告知前端向量存储未初始化
                "available": False,         # 字段：可用状态为 false
                "message": "向量存储未初始化",  # 字段：提示信息
            })

        metadata = vs.metadata or []      # 获取向量存储的元数据列表（每个切块的信息），如果没有则设为空列表
        dense_vectors = vs.dense_vectors or []  # 获取稠密向量列表（每个切块的向量表示），如果没有则设为空列表

        # ===== 总体统计 =====
        total_chunks = len(metadata)        # 计算总共有多少个切块（chunk），即元数据的数量
        total_vectors = len(dense_vectors)  # 计算总共有多少个向量，即稠密向量的数量

        # ===== 按分区（partition）统计 =====
        by_partition = {}  # 创建一个空字典，用于存储按分区维度的统计数据
        for m in metadata:  # 遍历每一条元数据
            p = m.get("partition", "default")  # 获取该元数据所属的分区名，如果没有则默认为 "default"
            by_partition.setdefault(p, {"chunks": 0, "sources": set()})  # 如果该分区还没有记录，初始化一个字典：切块数0，来源集合空
            by_partition[p]["chunks"] += 1  # 该分区的切块数加1
            if m.get("source"):  # 如果元数据中有来源（source）字段
                by_partition[p]["sources"].add(m["source"])  # 将来源名称加入该分区的来源集合（set 自动去重）
        by_partition_summary = {  # 构建一个可以序列化为 JSON 的分区统计摘要（把 set 转成 list）
            p: {"chunks": v["chunks"], "sources": sorted(v["sources"])}  # 对每个分区：记录切块数和排序后的来源列表
            for p, v in by_partition.items()  # 遍历 by_partition 字典中的每个分区
        }

        # ===== 按来源（source）统计 =====
        by_source = {}  # 创建一个空字典，用于存储按来源维度的统计数据
        for m in metadata:  # 遍历每一条元数据
            s = m.get("source", "unknown")  # 获取该元数据的来源，如果没有则设为 "unknown"
            by_source.setdefault(s, {"chunks": 0, "partitions": set()})  # 如果该来源还没有记录，初始化字典：切块数0，分区集合空
            by_source[s]["chunks"] += 1  # 该来源的切块数加1
            if m.get("partition"):  # 如果元数据中有分区字段
                by_source[s]["partitions"].add(m["partition"])  # 将分区名加入该来源的分区集合

        # ===== 将 set 转为 list 以支持 JSON 序列化 =====
        # 因为 Python 的 set 类型不能直接序列化为 JSON，需要转成 list
        for v in by_source.values():  # 遍历 by_source 中的每个值
            v["partitions"] = sorted(v["partitions"])  # 把分区集合转为排序后的列表
        for v in by_partition.values():  # 遍历 by_partition 中的每个值
            if isinstance(v.get("sources"), set):  # 如果 sources 字段还是 set 类型（安全处理）
                v["sources"] = sorted(v["sources"])  # 转为排序后的列表

        # ===== 构建并返回最终统计结果 =====
        return JSONResponse(content={  # 返回 JSON 格式的响应
            "available": True,         # 字段：向量存储可用
            "embedding_model": vs.embedding_model if vs else None,  # 嵌入模型的名称（如果有向量存储）
            "embedding_dimension": vs.dimension if vs else None,    # 嵌入向量的维度（如果有向量存储）
            "total_chunks": total_chunks,        # 总切块数
            "total_vectors": total_vectors,      # 总向量数
            "partitions_count": len(by_partition),  # 分区数量
            "sources_count": len(by_source),        # 来源数量
            "chunk_types": sorted({m.get("chunk_type", "") for m in metadata if m.get("chunk_type")}),  # 所有切块类型（去重并排序）
            "by_partition": by_partition_summary,  # 按分区统计的详细信息
            "by_source": by_source,                # 按来源统计的详细信息
        })
    except Exception as e:  # 捕获所有异常
        logger.error(f"获取数据库统计失败: {e}")  # 记录错误日志
        raise HTTPException(status_code=500, detail=str(e))  # 抛出 HTTP 500 错误，返回服务器内部错误


# ===== API 路由：获取切块（chunk）详情列表 =====
@router.get("/database/chunks")  # 注册 GET 请求，路径为 /database/chunks
@auth_required                   # 需要身份认证
@admin_required                  # 需要管理员权限
async def get_chunks(            # 定义异步函数 get_chunks
    request: Request,            # 请求对象
    page: int = Query(1, ge=1),  # 查询参数：页码，默认第1页，最小值1
    page_size: int = Query(20, ge=1, le=200),  # 查询参数：每页条数，默认20条，范围1~200
    partition: str = Query(None),  # 查询参数：按分区名过滤，可选
    source: str = Query(None),     # 查询参数：按来源过滤，可选
    chunk_type: str = Query(None), # 查询参数：按切块类型过滤，可选
    parent_id: str = Query(None),  # 查询参数：按父文档ID过滤，可选
    query_text: str = Query(None), # 查询参数：按文本内容搜索过滤，可选
):
    """切块详情列表（分页, 可过滤 partition/source/chunk_type/parent_id）"""  # 函数文档字符串
    try:  # try 异常捕获
        vs = system.vector_store  # 获取向量存储实例
        if not vs or not vs.metadata:  # 如果向量存储不存在或者没有元数据
            return JSONResponse(content={"total": 0, "items": [], "page": page, "page_size": page_size})  # 返回空结果

        metadata = vs.metadata  # 获取所有元数据列表

        # ===== 应用过滤条件 =====
        filtered = metadata  # 初始过滤后的列表等于全部元数据
        if partition:  # 如果指定了分区过滤条件
            filtered = [m for m in filtered if m.get("partition") == partition]  # 只保留分区匹配的元数据
        if source:  # 如果指定了来源过滤条件
            filtered = [m for m in filtered if m.get("source") == source]  # 只保留来源匹配的元数据
        if chunk_type:  # 如果指定了切块类型过滤条件
            filtered = [m for m in filtered if m.get("chunk_type") == chunk_type]  # 只保留类型匹配的元数据
        if parent_id:  # 如果指定了父文档ID过滤条件
            filtered = [m for m in filtered if m.get("parent_id") == parent_id]  # 只保留父ID匹配的元数据
        if query_text:  # 如果指定了文本搜索条件
            q = query_text.lower()  # 将搜索关键词转为小写（不区分大小写匹配）
            filtered = [m for m in filtered if q in (m.get("text") or "").lower()]  # 只保留文本中包含关键词的元数据

        # ===== 分页处理 =====
        total = len(filtered)  # 过滤后的总数量
        start = (page - 1) * page_size  # 计算起始索引（第1页从0开始）
        end = start + page_size         # 计算结束索引
        items = filtered[start:end]     # 截取当前页的数据

        # ===== 简化返回数据（避免传输过多无用信息） =====
        simplified = []  # 创建空列表，存放简化后的数据
        for m in items:  # 遍历当前页的每个元数据
            text = (m.get("text") or "")[:200]  # 获取文本内容，最多取前200个字符（避免返回过长）
            simplified.append({  # 将简化后的字典添加到列表
                "id": m.get("id", ""),              # 切块ID
                "parent_id": m.get("parent_id", ""), # 父文档ID
                "text": text,                        # 文本内容（截断版）
                "source": m.get("source", ""),       # 来源
                "partition": m.get("partition", ""), # 分区
                "chunk_type": m.get("chunk_type", ""), # 切块类型
                "page": m.get("page"),               # 页码（可能为None）
                "parent_chunk_size": len(m.get("parent_text", "")),  # 父文本的长度
            })

        return JSONResponse(content={  # 返回分页结果
            "total": total,        # 总记录数
            "page": page,          # 当前页码
            "page_size": page_size, # 每页大小
            "items": simplified,   # 当前页的数据列表
        })
    except Exception as e:  # 捕获异常
        logger.error(f"获取切块详情失败: {e}")  # 记录错误日志
        raise HTTPException(status_code=500, detail=str(e))  # 返回500错误


# ===== API 路由：列出所有分区及统计信息 =====
@router.get("/database/partitions")  # 注册 GET 请求，路径为 /database/partitions
@auth_required                        # 需要身份认证
@admin_required                       # 需要管理员权限
async def get_partitions(request: Request):  # 定义异步函数 get_partitions，参数为请求对象
    """列出所有分区及每个分区的文档/切块数"""  # 函数文档字符串
    try:  # try 异常捕获
        vs = system.vector_store  # 获取向量存储实例
        if not vs or not vs.metadata:  # 如果没有向量存储或没有元数据
            return JSONResponse(content={"partitions": []})  # 返回空分区列表

        partitions = {}  # 创建一个空字典，存放各分区信息
        for m in vs.metadata:  # 遍历每条元数据
            p = m.get("partition", "default")  # 获取分区名，默认 "default"
            partitions.setdefault(p, {"partition": p, "chunks": 0, "sources": set()})  # 如果分区还不存在，初始化它
            partitions[p]["chunks"] += 1  # 该分区的切块数加1
            if m.get("source"):  # 如果有来源信息
                partitions[p]["sources"].add(m["source"])  # 把来源加入集合

        # ===== 构建返回结果（将 set 转为 list） =====
        result = [  # 构建最终结果列表
            {"partition": k, "chunks": v["chunks"], "sources": sorted(v["sources"])}  # 每个分区的信息
            for k, v in partitions.items()  # 遍历所有分区
        ]
        result.sort(key=lambda x: -x["chunks"])  # 按切块数从大到小排序（负号表示降序）

        return JSONResponse(content={"partitions": result})  # 返回 JSON 响应
    except Exception as e:  # 捕获异常
        logger.error(f"获取分区列表失败: {e}")  # 记录错误日志
        raise HTTPException(status_code=500, detail=str(e))  # 返回500错误


# ===== API 路由：检查文档完整性 =====
@router.get("/database/check_integrity")  # 注册 GET 请求，路径为 /database/check_integrity
@auth_required                             # 需要身份认证
@admin_required                            # 需要管理员权限
async def check_integrity(request: Request):  # 定义异步函数 check_integrity
    """检查文档完整性：验证元数据中的文件/图片是否真实存在于磁盘。"""  # 函数文档字符串
    try:  # try 异常捕获
        vs = system.vector_store  # 获取向量存储实例
        if not vs or not vs.metadata:  # 如果没有向量存储或没有元数据
            return JSONResponse(content={  # 返回提示信息
                "available": False,  # 字段：不可用
                "message": "向量存储未初始化或无数据",  # 字段：提示消息
            })

        metadata = vs.metadata  # 获取所有元数据
        uploads_base = Path(conf.vector_store_dir) / "uploads"  # 获取上传文件的根目录路径

        # ===== 按 (partition, source) 分组统计 =====
        docs: dict[tuple[str, str], dict] = {}  # 创建一个字典，键是 (分区, 来源) 元组，值是文档信息字典
        for m in metadata:  # 遍历每条元数据
            key = (m.get("partition", "") or "", m.get("source", "") or "")  # 用 (分区, 来源) 作为唯一键
            if not key[1]:  # 如果 source 为空（第二个元素为空字符串）
                continue   # 跳过这条元数据，不纳入检查
            if key not in docs:  # 如果这个键还没出现过
                docs[key] = {"chunks": 0, "images": 0, "image_records": [], "text_chunks": 0}  # 初始化文档统计信息
            docs[key]["chunks"] += 1  # 文档的总切块数加1
            ct = (m.get("chunk_type") or "").strip()  # 获取切块类型并去除首尾空白
            ip = (m.get("img_path") or "").strip()     # 获取图片路径并去除首尾空白
            if ct in ("image", "chart") and ip:  # 如果切块类型是图片或图表，并且图片路径不为空
                docs[key]["images"] += 1           # 图片数量加1
                docs[key]["image_records"].append(ip)  # 记录图片路径
            else:  # 否则（文本切块或其他类型）
                docs[key]["text_chunks"] += 1  # 文本切块数量加1

        # ===== 初始化统计变量 =====
        total_images = 0      # 图片总数
        healthy_images = 0    # 正常的图片数
        missing_images = 0    # 缺失的图片数
        issues = []           # 问题列表，记录所有发现的问题
        healthy_docs = 0      # 正常的文档数

        # ===== 遍历每个文档，检查完整性 =====
        for (partition, source), info in docs.items():  # 遍历每个文档（分区和来源）
            stem = Path(source).stem  # 获取源文件的主文件名（不含扩展名）
            doc_issues = []  # 记录当前文档的问题

            # ---- 检查①：原始文件是否存在 ----
            source_file = uploads_base / partition / source  # 构建源文件的完整路径
            source_exists = source_file.exists()  # 检查源文件是否真实存在于磁盘
            if not source_exists:  # 如果源文件不存在
                doc_issues.append(f"原文件缺失")  # 添加"原文件缺失"问题

            # ---- 检查②：chunk_out 目录是否存在 ----
            chunk_dir = uploads_base / partition / "chunk_out" / stem  # 构建 chunk_out 目录路径（MinerU 解析后的产物）
            chunk_exists = chunk_dir.is_dir()  # 检查该目录是否真实存在且是一个目录
            if not chunk_exists:  # 如果目录不存在
                # 尝试用 glob 模糊匹配（目录名可能多了 _ 等后缀，比如 filename_1 而不是 filename）
                fuzzy_dirs = sorted(glob.glob(str(uploads_base / partition / "chunk_out" / f"{stem}*")))  # 用通配符匹配类似名字的目录
                if fuzzy_dirs:  # 如果模糊匹配找到了目录
                    chunk_dir = Path(fuzzy_dirs[0])  # 使用匹配到的第一个目录
                    chunk_exists = True  # 标记为存在
                    doc_issues.append(f"chunk_out 目录名不精确 (实际: {chunk_dir.name})")  # 记录一个警告
                else:  # 模糊匹配也没找到
                    doc_issues.append(f"chunk_out 目录缺失")  # 记录目录缺失问题

            # ---- 检查③：图片文件完整性 ----
            img_missing_count = 0  # 统计当前文档中缺失的图片数量
            img_hash_mismatch = 0  # 统计文件名不完全匹配的图片数量
            for img_path in info["image_records"]:  # 遍历该文档的所有图片记录
                total_images += 1  # 总图片数加1
                if not chunk_exists:  # 如果 chunk_out 目录都不存在
                    missing_images += 1  # 也就无法检查图片，直接记为缺失
                    continue  # 跳过后续检查

                expected = chunk_dir / img_path  # 构建期望的图片完整路径
                # 精确匹配：查找完全符合条件的文件
                candidates = glob.glob(str(expected))  # 用 glob 尝试精确匹配
                # 前缀匹配：如果精确匹配没找到，尝试前缀匹配（文件名可能多了后缀或编码）
                if not candidates:  # 如果精确匹配没有结果
                    candidates = sorted(glob.glob(str(expected) + "*"))  # 在路径末尾加*做前缀匹配
                if candidates:  # 如果找到了候选文件
                    healthy_images += 1  # 正常图片数加1
                    # 检查文件名是否完全匹配（与记录的路径名一模一样）
                    if Path(candidates[0]).name != Path(img_path).name:  # 如果找到的文件名和记录的不完全一致
                        img_hash_mismatch += 1  # 记录为哈希不匹配（文件名有差异）
                else:  # 彻底没有找到任何匹配的文件
                    missing_images += 1  # 缺失图片数加1
                    img_missing_count += 1  # 当前文档缺失图片数加1

            # ===== 严重级别判断 =====
            severity = "healthy"  # 默认为健康状态
            if doc_issues:  # 如果有任何问题
                # 判断是否有严重问题（"缺失"且不是"不精确"的问题，即文件或目录完全缺失）
                has_critical = any("缺失" in i and "不精确" not in i for i in doc_issues)
                severity = "critical" if has_critical else "warning"  # 有关键问题就是 critical，否则是 warning

            if doc_issues:  # 如果有问题，添加到问题列表
                issues.append({  # 添加一个问题记录
                    "source": source,          # 来源文件名
                    "partition": partition,    # 分区名
                    "chunks": info["chunks"],  # 总切块数
                    "text_chunks": info["text_chunks"],  # 文本切块数
                    "image_count": info["images"],        # 图片数量
                    "severity": severity,       # 严重级别
                    "source_exists": source_exists,  # 源文件是否存在
                    "chunk_exists": chunk_exists,    # chunk 目录是否存在
                    "img_missing_count": img_missing_count,  # 缺失图片数
                    "img_hash_mismatch": img_hash_mismatch,  # 图片名不匹配数
                    "issues": doc_issues,  # 具体问题描述列表
                })
            else:  # 没有问题
                healthy_docs += 1  # 健康文档数加1

        # ===== 返回完整性检查结果 =====
        return JSONResponse(content={  # 返回 JSON 响应
            "available": True,              # 字段：检查可用
            "total_documents": len(docs),   # 总文档数
            "healthy": healthy_docs,        # 健康文档数
            "problematic": len(issues),     # 有问题的文档数
            "total_chunks": len(metadata),  # 总切块数
            "total_images": total_images,   # 总图片数
            "healthy_images": healthy_images,  # 正常图片数
            "missing_images": missing_images,  # 缺失图片数
            "issues": issues,  # 问题详情列表
        })
    except Exception as e:  # 捕获异常
        logger.error(f"完整性检查失败: {e}")  # 记录错误日志
        raise HTTPException(status_code=500, detail=str(e))  # 返回500错误


# ===== 系统数据上传功能 =====
# ─── 系统数据上传 ─────────────────────────────────────────────

# ===== API 路由：列出所有系统级文档 =====
@router.get("/database/system_docs")  # 注册 GET 请求，路径为 /database/system_docs
@auth_required                         # 需要身份认证
@admin_required                        # 需要管理员权限
async def list_system_docs(request: Request):  # 定义异步函数 list_system_docs
    """列出所有系统级文档"""  # 函数文档字符串
    try:  # try 异常捕获
        docs = system.vector_store.get_documents_by_partition(partition=SYSTEM_PARTITION) or []  # 从向量库中获取系统分区的所有文档
        # ===== 获取每个文档的 chunk 数 =====
        doc_chunks = {}  # 创建一个字典，用于存储每个文档的切块数量
        if system.vector_store.metadata:  # 如果有元数据
            for m in system.vector_store.metadata:  # 遍历所有元数据
                src = m.get("source", "")  # 获取元数据的来源（文档名）
                if m.get("partition") == SYSTEM_PARTITION and src:  # 如果是系统分区且有来源名
                    doc_chunks[src] = doc_chunks.get(src, 0) + 1  # 该文档的切块计数加1
        items = []  # 创建结果列表
        for d in sorted(docs):  # 遍历排序后的文档名列表
            items.append({"name": d, "chunks": doc_chunks.get(d, 0)})  # 添加文档名和其切块数
        return JSONResponse(content={"documents": items})  # 返回 JSON 响应
    except Exception as e:  # 捕获异常
        logger.error(f"获取系统文档列表失败: {e}")  # 记录错误日志
        raise HTTPException(status_code=500, detail=str(e))  # 返回500错误


# ===== API 路由：上传系统级数据文档 =====
@router.post("/database/upload")  # 注册 POST 请求，路径为 /database/upload
@auth_required                    # 需要身份认证
@admin_required                   # 需要管理员权限
async def upload_system_data(request: Request, files: list[UploadFile] = File(...)):  # 定义异步函数 upload_system_data，接收文件列表参数
    """上传系统级数据文档（后台处理，不阻塞）"""  # 函数文档字符串
    from rag.vector_store import process_documents_from_dir  # 在函数内部导入处理文档的函数（避免循环导入）

    if not files:  # 如果没有上传文件
        raise HTTPException(status_code=400, detail="未提供文件")  # 返回400错误，提示未提供文件

    import threading as _threading  # 在函数内部导入 threading 模块（用于后台线程处理）
    task_id = "upload_" + _uuid.uuid4().hex[:8]  # 生成一个唯一的任务ID：前缀 "upload_" + UUID的16进制前8位
    total = len(files)  # 获取文件总数
    tasks = []  # 创建一个列表，存放 (文件名, 保存路径) 的元组

    # ===== 遍历上传的文件，保存到磁盘 =====
    for file in files:  # 遍历每一个上传的文件
        content = await file.read()  # 异步读取文件内容（await 等待读取完成）
        if not content:  # 如果文件内容为空
            continue  # 跳过这个文件，不处理

        # ===== 丢弃目录层级，只保留基础文件名 =====
        # 防止用户上传包含路径的文件名（如 "../../恶意文件"），只取文件名
        filename = os.path.basename(file.filename)  # 获取文件的基础名（去掉所有目录路径）
        save_dir = f"{conf.vector_store_dir}/uploads/{SYSTEM_PARTITION}"  # 构建保存目录：向量存储目录/uploads/系统分区
        save_path = os.path.normpath(os.path.join(save_dir, filename))  # 构建完整保存路径并规范化（处理../等相对路径）
        if not save_path.startswith(os.path.normpath(save_dir)):  # 安全检查：确保保存路径仍在目标目录内（防止路径穿越攻击）
            logger.warning(f"非法文件路径: {filename}")  # 记录警告日志
            continue  # 跳过这个文件

        os.makedirs(os.path.dirname(save_path), exist_ok=True)  # 创建目录（如果不存在），exist_ok=True 表示目录已存在也不报错
        with open(save_path, "wb") as f:  # 以二进制写入模式打开文件
            f.write(content)  # 将上传的文件内容写入磁盘

        tasks.append((filename, save_path))  # 将 (文件名, 保存路径) 添加到任务列表

    # ===== 注册任务状态 =====
    _upload_tasks[task_id] = {  # 在全局上传任务字典中注册这个任务
        "filenames": [t[0] for t in tasks],  # 所有上传的文件名列表
        "status": "processing",  # 任务状态：处理中
        "total": len(tasks),    # 总文件数
        "success": 0,           # 成功处理的文件数（初始为0）
        "fail": 0,              # 处理失败的文件数（初始为0）
    }

    # ===== 后台逐文件向量化 =====
    # 定义一个内部函数 _worker，在后台线程中执行
    def _worker():
        task = _upload_tasks[task_id]  # 获取当前任务的状态字典
        for fname, fpath in tasks:  # 遍历所有需要处理的文件
            try:  # 尝试处理每个文件
                # 第一步：删除该文件在向量库中已有的旧数据（防止重复）
                system.vector_store.delete_documents_by_sources([fname], partition=SYSTEM_PARTITION)
                # 第二步：将文件内容存入向量库（解析、切块、嵌入）
                system.vector_store.store_documents_from_dir(fpath, partition=SYSTEM_PARTITION)
                task["success"] += 1  # 成功计数加1
                logger.info(f"系统数据上传成功: {fname}")  # 记录成功日志
            except Exception as e:  # 如果处理出错
                task["fail"] += 1  # 失败计数加1
                logger.error(f"系统数据上传失败 ({fname}): {e}")  # 记录失败日志
        task["status"] = "finished"  # 所有文件处理完成，更新任务状态为"finished"

    # 创建一个后台线程来执行 _worker 函数，daemon=True 表示主线程结束时该线程也会结束
    _threading.Thread(target=_worker, daemon=True).start()

    # ===== 立即返回响应（不等待后台处理完成） =====
    return JSONResponse(content={  # 返回 JSON 响应
        "task_id": task_id,  # 任务ID，前端可以用这个ID查询处理状态
        "message": f"已接收 {total} 个文件，后台向量化处理中",  # 提示消息
        "files": tasks,  # 接收到的文件列表
    })


# ===== API 路由：查询上传任务状态 =====
@router.get("/database/upload/status")  # 注册 GET 请求，路径为 /database/upload/status
@auth_required                           # 需要身份认证
@admin_required                          # 需要管理员权限
async def get_upload_status(request: Request):  # 定义异步函数 get_upload_status
    """查询最近的上传任务状态"""  # 函数文档字符串
    # 返回最近一个未完成的或刚完成的任务

    # ---- 查找正在处理的任务 ----
    active = {k: v for k, v in _upload_tasks.items() if v["status"] == "processing"}  # 筛选出所有状态为"processing"的任务
    if active:  # 如果有正在处理的任务
        tid, task = list(active.items())[-1]  # 取最近的一个（字典遍历顺序即插入顺序）
        return JSONResponse(content={"task_id": tid, "status": "processing", "task": task})  # 返回处理中的状态

    # ---- 查找最近完成的任务 ----
    finished = {k: v for k, v in _upload_tasks.items() if v["status"] == "finished"}  # 筛选出所有已完成的任务
    if finished:  # 如果有已完成的任务
        tid, task = list(finished.items())[-1]  # 取最近完成的一个
        return JSONResponse(content={"task_id": tid, "status": "finished", "task": task})  # 返回已完成的状态

    # ---- 没有任何任务 ----
    return JSONResponse(content={"status": "idle"})  # 返回空闲状态


# ===== API 路由：删除文档 =====
@router.delete("/database/delete")  # 注册 DELETE 请求，路径为 /database/delete
@auth_required                       # 需要身份认证
@admin_required                      # 需要管理员权限
async def delete_document(request: Request, source: str = Query(...), partition: str = Query(...)):  # 定义异步函数 delete_document，需要 source 和 partition 参数
    """删除指定分区中的指定文档（系统数据或用户数据）"""  # 函数文档字符串
    try:  # try 异常捕获
        if not source or not partition:  # 如果 source 或 partition 参数为空
            raise HTTPException(status_code=400, detail="缺少参数 source 或 partition")  # 返回400错误，参数缺失

        # ===== 从向量库删除 =====
        # 调用向量存储的方法，删除指定分区中指定来源的所有向量数据
        system.vector_store.delete_documents_by_sources([source], partition=partition)

        # ===== 清理源文件和缓存 =====
        upload_dir = f"{conf.vector_store_dir}/uploads/{partition}"  # 构建上传目录路径
        file_path = os.path.join(upload_dir, source)  # 构建源文件的完整路径
        if os.path.isfile(file_path):  # 如果该文件存在且是一个普通文件
            os.remove(file_path)  # 删除该文件
            logger.info(f"已删除源文件: {file_path}")  # 记录删除日志

        # ===== 清理 MinerU chunk_out 产物 =====
        # MinerU 解析文档后会生成一个 chunk_out 目录，里面包含处理后的图片等资源
        chunk_out = os.path.join(upload_dir, "chunk_out", Path(source).stem)  # 构建 chunk_out 子目录路径
        if os.path.isdir(chunk_out):  # 如果该目录存在
            shutil.rmtree(chunk_out)  # 递归删除整个目录（包含所有子文件和子目录）
            logger.info(f"已删除 chunk 目录: {chunk_out}")  # 记录删除日志

        logger.info(f"管理员删除文档: source={source}, partition={partition}")  # 记录管理员删除操作日志
        return JSONResponse(content={"message": f"文档 '{source}' 已从 {partition} 删除"})  # 返回删除成功的响应
    except Exception as e:  # 捕获异常
        logger.error(f"删除文档失败: {e}")  # 记录错误日志
        raise HTTPException(status_code=500, detail=str(e))  # 返回500错误
