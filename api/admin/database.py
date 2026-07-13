"""管理后台 API - 数据库（向量存储）统计与系统数据上传"""
import glob
import os
import shutil
import threading as _threading
import uuid as _uuid
from pathlib import Path

from . import router, SYSTEM_PARTITION, _upload_tasks
from ..deps import admin_required, auth_required, system
from base.config import conf
from base.logger import logger

from fastapi import File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse


@router.get("/database")
@auth_required                    # 装饰器：要求用户必须经过身份认证才能访问
@admin_required                   # 装饰器：要求用户必须是管理员才能访问
async def get_database_stats(request: Request):
    """向量库统计: 总切块数、按分区/来源分布、嵌入维度"""
    try:
        vs = system.vector_store
        if not vs:
            return JSONResponse(content={
                "available": False,         # 字段：可用状态为 false
                "message": "向量存储未初始化",
            })
        metadata = vs.metadata or []
        dense_vectors = vs.dense_vectors or []

        # ===== 总体统计 =====
        total_chunks = len(metadata)        # 计算总共有多少个切块（chunk），即元数据的数量
        total_vectors = len(dense_vectors)  # 计算总共有多少个向量，即稠密向量的数量

        # ===== 按分区（partition）统计 =====
        by_partition = {}
        for m in metadata:
            p = m.get("partition", "default")
            by_partition.setdefault(p, {"chunks": 0, "sources": set()})
            by_partition[p]["chunks"] += 1
            if m.get("source"):
                by_partition[p]["sources"].add(m["source"])  # 将来源名称加入该分区的来源集合（set 自动去重）
        by_partition_summary = {
            p: {"chunks": v["chunks"], "sources": sorted(v["sources"])}  # 对每个分区：记录切块数和排序后的来源列表
            for p, v in by_partition.items()  # 遍历 by_partition 字典中的每个分区
        }

        # ===== 按来源（source）统计 =====
        by_source = {}
        for m in metadata:
            s = m.get("source", "unknown")
            by_source.setdefault(s, {"chunks": 0, "partitions": set()})
            by_source[s]["chunks"] += 1
            if m.get("partition"):
                by_source[s]["partitions"].add(m["partition"])  # 将分区名加入该来源的分区集合

        # ===== 将 set 转为 list 以支持 JSON 序列化 =====
        # 因为 Python 的 set 类型不能直接序列化为 JSON，需要转成 list
        for v in by_source.values():  # 遍历 by_source 中的每个值
            v["partitions"] = sorted(v["partitions"])  # 把分区集合转为排序后的列表
        for v in by_partition.values():  # 遍历 by_partition 中的每个值
            if isinstance(v.get("sources"), set):
                v["sources"] = sorted(v["sources"])


        return JSONResponse(content={
            "available": True,
            "embedding_model": vs.embedding_model if vs else None,
            "embedding_dimension": vs.dimension if vs else None,
            "total_chunks": total_chunks,
            "total_vectors": total_vectors,
            "partitions_count": len(by_partition),
            "sources_count": len(by_source),
            "chunk_types": sorted({m.get("chunk_type", "") for m in metadata if m.get("chunk_type")}),  # 所有切块类型（去重并排序）
            "by_partition": by_partition_summary,  # 按分区统计的详细信息
            "by_source": by_source,                # 按来源统计的详细信息
        })
    except Exception as e:
        logger.error(f"获取数据库统计失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/database/chunks")  # 注册 GET 请求，路径为 /database/chunks
@auth_required
@admin_required
async def get_chunks(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    partition: str = Query(None),
    source: str = Query(None),
    chunk_type: str = Query(None),
    parent_id: str = Query(None),
    query_text: str = Query(None),
):
    """切块详情列表（分页, 可过滤 partition/source/chunk_type/parent_id）"""
    try:
        vs = system.vector_store
        if not vs or not vs.metadata:
            return JSONResponse(content={"total": 0, "items": [], "page": page, "page_size": page_size})

        metadata = vs.metadata

        # ===== 应用过滤条件 =====
        filtered = metadata  # 初始过滤后的列表等于全部元数据
        if partition:
            filtered = [m for m in filtered if m.get("partition") == partition]  # 只保留分区匹配的元数据
        if source:
            filtered = [m for m in filtered if m.get("source") == source]  # 只保留来源匹配的元数据
        if chunk_type:
            filtered = [m for m in filtered if m.get("chunk_type") == chunk_type]  # 只保留类型匹配的元数据
        if parent_id:
            filtered = [m for m in filtered if m.get("parent_id") == parent_id]  # 只保留父ID匹配的元数据
        if query_text:
            q = query_text.lower()  # 将搜索关键词转为小写（不区分大小写匹配）
            filtered = [m for m in filtered if q in (m.get("text") or "").lower()]  # 只保留文本中包含关键词的元数据

        # ===== 分页处理 =====
        total = len(filtered)
        start = (page - 1) * page_size  # 计算起始索引（第1页从0开始）
        end = start + page_size
        items = filtered[start:end]


        simplified = []  # 创建空列表，存放简化后的数据
        for m in items:  # 遍历当前页的每个元数据
            text = (m.get("text") or "")[:200]
            simplified.append({  # 将简化后的字典添加到列表
                "id": m.get("id", ""),
                "parent_id": m.get("parent_id", ""),
                "text": text,
                "source": m.get("source", ""),
                "partition": m.get("partition", ""),
                "chunk_type": m.get("chunk_type", ""),
                "page": m.get("page"),               # 页码（可能为None）
                "parent_chunk_size": len(m.get("parent_text", "")),
            })

        return JSONResponse(content={
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": simplified,
        })
    except Exception as e:
        logger.error(f"获取切块详情失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== API 路由：列出所有分区及统计信息 =====
@router.get("/database/partitions")  # 注册 GET 请求，路径为 /database/partitions
@auth_required
@admin_required
async def get_partitions(request: Request):
    """列出所有分区及每个分区的文档/切块数"""
    try:
        vs = system.vector_store
        if not vs or not vs.metadata:
            return JSONResponse(content={"partitions": []})

        partitions = {}
        for m in vs.metadata:
            p = m.get("partition", "default")
            partitions.setdefault(p, {"partition": p, "chunks": 0, "sources": set()})
            partitions[p]["chunks"] += 1
            if m.get("source"):
                partitions[p]["sources"].add(m["source"])


        result = [
            {"partition": k, "chunks": v["chunks"], "sources": sorted(v["sources"])}
            for k, v in partitions.items()
        ]
        result.sort(key=lambda x: -x["chunks"])  # 按切块数从大到小排序（负号表示降序）

        return JSONResponse(content={"partitions": result})
    except Exception as e:
        logger.error(f"获取分区列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/database/check_integrity")  # 注册 GET 请求，路径为 /database/check_integrity
@auth_required
@admin_required
async def check_integrity(request: Request):
    """检查文档完整性：验证元数据中的文件/图片是否真实存在于磁盘。"""
    try:
        vs = system.vector_store
        if not vs or not vs.metadata:
            return JSONResponse(content={
                "available": False,
                "message": "向量存储未初始化或无数据",
            })

        metadata = vs.metadata
        uploads_base = Path(conf.data_dir) / "uploads"

        # ===== 按 (partition, source) 分组统计 =====
        docs: dict[tuple[str, str], dict] = {}
        for m in metadata:
            key = (m.get("partition", "") or "", m.get("source", "") or "")  # 用 (分区, 来源) 作为唯一键
            if not key[1]:
                continue
            if key not in docs:
                docs[key] = {"chunks": 0, "images": 0, "image_records": [], "text_chunks": 0}
            docs[key]["chunks"] += 1
            ct = (m.get("chunk_type") or "").strip()
            ip = (m.get("img_path") or "").strip()
            if ct in ("image", "chart") and ip:
                docs[key]["images"] += 1
                docs[key]["image_records"].append(ip)
            else:
                docs[key]["text_chunks"] += 1

        # ===== 初始化统计变量 =====
        total_images = 0
        healthy_images = 0
        missing_images = 0
        issues = []           # 问题列表，记录所有发现的问题
        healthy_docs = 0


        for (partition, source), info in docs.items():  # 遍历每个文档（分区和来源）
            stem = Path(source).stem
            doc_issues = []


            source_file = uploads_base / partition / source  # 构建源文件的完整路径
            source_exists = source_file.exists()
            if not source_exists:
                doc_issues.append(f"原文件缺失")  # 添加"原文件缺失"问题


            chunk_dir = uploads_base / partition / "chunk_out" / stem
            chunk_exists = chunk_dir.is_dir()
            if not chunk_exists:
                # 尝试用 glob 模糊匹配（目录名可能多了 _ 等后缀，比如 filename_1 而不是 filename）
                fuzzy_dirs = sorted(glob.glob(str(uploads_base / partition / "chunk_out" / f"{stem}*")))  # 用通配符匹配类似名字的目录
                if fuzzy_dirs:
                    chunk_dir = Path(fuzzy_dirs[0])
                    chunk_exists = True
                    doc_issues.append(f"chunk_out 目录名不精确 (实际: {chunk_dir.name})")
                else:
                    doc_issues.append(f"chunk_out 目录缺失")


            img_missing_count = 0  # 统计当前文档中缺失的图片数量
            img_hash_mismatch = 0  # 统计文件名不完全匹配的图片数量
            for img_path in info["image_records"]:  # 遍历该文档的所有图片记录
                total_images += 1
                if not chunk_exists:
                    missing_images += 1
                    continue

                expected = chunk_dir / img_path  # 构建期望的图片完整路径
                # 精确匹配：查找完全符合条件的文件
                candidates = glob.glob(str(expected))  # 用 glob 尝试精确匹配

                if not candidates:
                    candidates = sorted(glob.glob(str(expected) + "*"))  # 在路径末尾加*做前缀匹配
                if candidates:
                    healthy_images += 1

                    if Path(candidates[0]).name != Path(img_path).name:
                        img_hash_mismatch += 1  # 记录为哈希不匹配（文件名有差异）
                else:  # 彻底没有找到任何匹配的文件
                    missing_images += 1
                    img_missing_count += 1  # 当前文档缺失图片数加1

            # ===== 严重级别判断 =====
            severity = "healthy"
            if doc_issues:
                # 判断是否有严重问题（"缺失"且不是"不精确"的问题，即文件或目录完全缺失）
                has_critical = any("缺失" in i and "不精确" not in i for i in doc_issues)
                severity = "critical" if has_critical else "warning"

            if doc_issues:
                issues.append({
                    "source": source,
                    "partition": partition,
                    "chunks": info["chunks"],
                    "text_chunks": info["text_chunks"],
                    "image_count": info["images"],
                    "severity": severity,
                    "source_exists": source_exists,
                    "chunk_exists": chunk_exists,    # chunk 目录是否存在
                    "img_missing_count": img_missing_count,
                    "img_hash_mismatch": img_hash_mismatch,
                    "issues": doc_issues,
                })
            else:
                healthy_docs += 1


        return JSONResponse(content={
            "available": True,
            "total_documents": len(docs),
            "healthy": healthy_docs,
            "problematic": len(issues),
            "total_chunks": len(metadata),
            "total_images": total_images,
            "healthy_images": healthy_images,
            "missing_images": missing_images,
            "issues": issues,
        })
    except Exception as e:
        logger.error(f"完整性检查失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== 系统数据上传功能 =====
# ─── 系统数据上传 ─────────────────────────────────────────────

# ===== API 路由：列出所有系统级文档 =====
@router.get("/database/system_docs")  # 注册 GET 请求，路径为 /database/system_docs
@auth_required
@admin_required
async def list_system_docs(request: Request):
    """列出所有系统级文档"""
    try:
        docs = system.vector_store.get_documents_by_partition(partition=SYSTEM_PARTITION) or []

        doc_chunks = {}
        if system.vector_store.metadata:
            for m in system.vector_store.metadata:
                src = m.get("source", "")
                if m.get("partition") == SYSTEM_PARTITION and src:
                    doc_chunks[src] = doc_chunks.get(src, 0) + 1  # 该文档的切块计数加1
        items = []
        for d in sorted(docs):  # 遍历排序后的文档名列表
            items.append({"name": d, "chunks": doc_chunks.get(d, 0)})  # 添加文档名和其切块数
        return JSONResponse(content={"documents": items})
    except Exception as e:
        logger.error(f"获取系统文档列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===== API 路由：上传系统级数据文档 =====
@router.post("/database/upload")  # 注册 POST 请求，路径为 /database/upload
@auth_required
@admin_required
async def upload_system_data(request: Request, files: list[UploadFile] = File(...)):
    """上传系统级数据文档（后台处理，不阻塞）"""
    from rag.vector_store import process_documents_from_dir

    if not files:
        raise HTTPException(status_code=400, detail="未提供文件")

    task_id = "upload_" + _uuid.uuid4().hex[:8]
    total = len(files)
    tasks = []

    # ===== 遍历上传的文件，保存到磁盘 =====
    for file in files:
        content = await file.read()  # 异步读取文件内容（await 等待读取完成）
        if not content:
            continue

        # ===== 丢弃目录层级，只保留基础文件名 =====
        # 防止用户上传包含路径的文件名（如 "../../恶意文件"），只取文件名
        filename = os.path.basename(file.filename)
        save_dir = f"{conf.data_dir}/uploads/{SYSTEM_PARTITION}"  # 构建保存目录：向量存储目录/uploads/系统分区
        save_path = os.path.normpath(os.path.join(save_dir, filename))  # 构建完整保存路径并规范化（处理../等相对路径）
        if not save_path.startswith(os.path.normpath(save_dir)):
            logger.warning(f"非法文件路径: {filename}")
            continue

        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, "wb") as f:  # 以二进制写入模式打开文件
            f.write(content)  # 将上传的文件内容写入磁盘

        tasks.append((filename, save_path))  # 将 (文件名, 保存路径) 添加到任务列表

    # ===== 注册任务状态 =====
    _upload_tasks[task_id] = {
        "filenames": [t[0] for t in tasks],
        "status": "processing",
        "total": len(tasks),
        "success": 0,
        "fail": 0,
        "failures": [],
    }

    # ===== 后台逐文件向量化（MinerU 并发数由 mineru_max_concurrency 控制） =====
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    _mineru_sem = threading.Semaphore(
        getattr(conf, 'mineru_max_concurrency', 3)
    )

    def _process_one(fname, fpath):
        """处理单个文件：删除旧数据 → 解析入库（受 MinerU 并发限制）"""
        system.vector_store.delete_documents_by_sources([fname], partition=SYSTEM_PARTITION)
        with _mineru_sem:
            system.vector_store.store_documents_from_dir(fpath, partition=SYSTEM_PARTITION)
        return fname

    def _worker():
        task = _upload_tasks[task_id]
        with ThreadPoolExecutor(max_workers=conf.mineru_max_concurrency) as pool:
            futures = {pool.submit(_process_one, fname, fpath): fname for fname, fpath in tasks}
            for future in as_completed(futures):
                fname = futures[future]
                try:
                    future.result()
                    task["success"] += 1
                    logger.info(f"系统数据上传成功: {fname}")
                except Exception as e:
                    task["fail"] += 1
                    task.setdefault("failures", []).append(fname)
                    logger.error(f"系统数据上传失败 ({fname}): {e}")
        task["status"] = "finished"


    _threading.Thread(target=_worker, daemon=True).start()


    return JSONResponse(content={
        "task_id": task_id,
        "message": f"已接收 {total} 个文件，后台向量化处理中",
        "files": tasks,
    })


# ===== API 路由：查询上传任务状态 =====
@router.get("/database/upload/status")  # 注册 GET 请求，路径为 /database/upload/status
@auth_required
@admin_required
async def get_upload_status(request: Request):
    """查询最近的上传任务状态"""


    # ---- 查找正在处理的任务 ----
    active = {k: v for k, v in _upload_tasks.items() if v["status"] == "processing"}  # 筛选出所有状态为"processing"的任务
    if active:
        tid, task = list(active.items())[-1]
        return JSONResponse(content={"task_id": tid, "status": "processing", "task": task})

    # ---- 查找最近完成的任务 ----
    finished = {k: v for k, v in _upload_tasks.items() if v["status"] == "finished"}  # 筛选出所有已完成的任务
    if finished:
        tid, task = list(finished.items())[-1]
        return JSONResponse(content={"task_id": tid, "status": "finished", "task": task})

    # ---- 没有任何任务 ----
    return JSONResponse(content={"status": "idle"})


# ===== API 路由：删除文档 =====
@router.delete("/database/delete")  # 注册 DELETE 请求，路径为 /database/delete
@auth_required
@admin_required
async def delete_document(request: Request, source: str = Query(...), partition: str = Query(...)):
    """删除指定分区中的指定文档（系统数据或用户数据）"""
    try:
        if not source or not partition:
            raise HTTPException(status_code=400, detail="缺少参数 source 或 partition")

        # ===== 从向量库删除 =====

        system.vector_store.delete_documents_by_sources([source], partition=partition)

        # ===== 清理源文件和缓存 =====
        upload_dir = f"{conf.data_dir}/uploads/{partition}"
        file_path = os.path.join(upload_dir, source)  # 构建源文件的完整路径
        if os.path.isfile(file_path):
            os.remove(file_path)
            logger.info(f"已删除源文件: {file_path}")

        # ===== 清理 MinerU chunk_out 产物 =====

        chunk_out = os.path.join(upload_dir, "chunk_out", Path(source).stem)  # 构建 chunk_out 子目录路径
        if os.path.isdir(chunk_out):
            shutil.rmtree(chunk_out)  # 递归删除整个目录（包含所有子文件和子目录）
            logger.info(f"已删除 chunk 目录: {chunk_out}")

        logger.info(f"管理员删除文档: source={source}, partition={partition}")
        return JSONResponse(content={"message": f"文档 '{source}' 已从 {partition} 删除"})
    except Exception as e:
        logger.error(f"删除文档失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/database/batch_delete")
@auth_required
@admin_required
async def batch_delete_documents(request: Request):
    """批量删除指定分区中的多个文档"""
    try:
        body = await request.json()
        sources = body.get("sources", [])
        partition = body.get("partition", "")

        if not sources or not partition:
            raise HTTPException(status_code=400, detail="缺少参数 sources 或 partition")

        deleted = []
        errors = []

        for source in sources:
            try:
                system.vector_store.delete_documents_by_sources([source], partition=partition)

                upload_dir = f"{conf.data_dir}/uploads/{partition}"
                file_path = os.path.join(upload_dir, source)
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    logger.info(f"已删除源文件: {file_path}")

                chunk_out = os.path.join(upload_dir, "chunk_out", Path(source).stem)
                if os.path.isdir(chunk_out):
                    shutil.rmtree(chunk_out)
                    logger.info(f"已删除 chunk 目录: {chunk_out}")

                deleted.append(source)
            except Exception as e:
                errors.append({"source": source, "error": str(e)})
                logger.error(f"批量删除失败 ({source}): {e}")

        logger.info(f"管理员批量删除文档: partition={partition}, 成功={len(deleted)}, 失败={len(errors)}")
        return JSONResponse(content={
            "message": f"成功删除 {len(deleted)} 个文档",
            "deleted": deleted,
            "errors": errors,
        })
    except Exception as e:
        logger.error(f"批量删除文档失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
