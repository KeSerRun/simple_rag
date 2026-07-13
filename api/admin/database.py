"""管理后台 API - 数据库(向量存储)统计与系统数据上传"""
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
@auth_required
@admin_required
async def get_database_stats(request: Request):
    """向量库统计: 总切块数、按分区/来源分布、嵌入维度。

    Args:
        request: FastAPI 请求对象。

    Returns:
        JSONResponse: 包含 available / total_chunks / total_vectors / by_partition / by_source 等字段。
        向量存储未初始化时返回 ``{"available": False}``。

    Raises:
        HTTPException 500: 统计失败。
    """
    try:
        vs = system.vector_store
        if not vs:
            return JSONResponse(content={
                "available": False,
                "message": "向量存储未初始化",
            })
        metadata = vs.metadata or []
        dense_vectors = vs.dense_vectors or []

        total_chunks = len(metadata)
        total_vectors = len(dense_vectors)

        by_partition = {}
        for m in metadata:
            p = m.get("partition", "default")
            by_partition.setdefault(p, {"chunks": 0, "sources": set()})
            by_partition[p]["chunks"] += 1
            if m.get("source"):
                by_partition[p]["sources"].add(m["source"])
        by_partition_summary = {
            p: {"chunks": v["chunks"], "sources": sorted(v["sources"])}
            for p, v in by_partition.items()
        }

        by_source = {}
        for m in metadata:
            s = m.get("source", "unknown")
            by_source.setdefault(s, {"chunks": 0, "partitions": set()})
            by_source[s]["chunks"] += 1
            if m.get("partition"):
                by_source[s]["partitions"].add(m["partition"])

        for v in by_source.values():
            v["partitions"] = sorted(v["partitions"])
        for v in by_partition.values():
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
            "chunk_types": sorted({m.get("chunk_type", "") for m in metadata if m.get("chunk_type")}),
            "by_partition": by_partition_summary,
            "by_source": by_source,
        })
    except Exception as e:
        logger.error(f"获取数据库统计失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/database/chunks")
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
    """切块详情列表(分页,可过滤)。

    # ── 过滤条件

    - partition: 按分区名过滤
    - source: 按来源文件名过滤
    - chunk_type: 按切块类型(text/image/chart)过滤
    - parent_id: 按父切块 ID 过滤
    - query_text: 按切块文本内容模糊搜索

    Args:
        request: FastAPI 请求对象。
        page: 页码,从 1 开始。
        page_size: 每页条数,默认 20,最大 200。
        partition: 可选,分区名过滤。
        source: 可选,来源文件名过滤。
        chunk_type: 可选,切块类型过滤。
        parent_id: 可选,父切块 ID 过滤。
        query_text: 可选,文本模糊搜索。

    Returns:
        JSONResponse: ``{"total": int, "page": int, "page_size": int, "items": [...]}``。
        每项含 id / text(前200字符) / source / partition / chunk_type / page 等字段。

    Raises:
        HTTPException 500: 查询失败。
    """
    try:
        vs = system.vector_store
        if not vs or not vs.metadata:
            return JSONResponse(content={"total": 0, "items": [], "page": page, "page_size": page_size})

        metadata = vs.metadata

        filtered = metadata
        if partition:
            filtered = [m for m in filtered if m.get("partition") == partition]
        if source:
            filtered = [m for m in filtered if m.get("source") == source]
        if chunk_type:
            filtered = [m for m in filtered if m.get("chunk_type") == chunk_type]
        if parent_id:
            filtered = [m for m in filtered if m.get("parent_id") == parent_id]
        if query_text:
            q = query_text.lower()
            filtered = [m for m in filtered if q in (m.get("text") or "").lower()]

        total = len(filtered)
        start = (page - 1) * page_size
        end = start + page_size
        items = filtered[start:end]


        simplified = []
        for m in items:
            text = (m.get("text") or "")[:200]
            simplified.append({
                "id": m.get("id", ""),
                "parent_id": m.get("parent_id", ""),
                "text": text,
                "source": m.get("source", ""),
                "partition": m.get("partition", ""),
                "chunk_type": m.get("chunk_type", ""),
                "page": m.get("page"),
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


@router.get("/database/partitions")
@auth_required
@admin_required
async def get_partitions(request: Request):
    """列出所有分区及每个分区的文档/切块数。

    Args:
        request: FastAPI 请求对象。

    Returns:
        JSONResponse: ``{"partitions": [{"partition": str, "chunks": int, "sources": [str]}, ...]}``,
        按切块数降序排列。

    Raises:
        HTTPException 500: 查询失败。
    """
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
        result.sort(key=lambda x: -x["chunks"])

        return JSONResponse(content={"partitions": result})
    except Exception as e:
        logger.error(f"获取分区列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/database/check_integrity")
@auth_required
@admin_required
async def check_integrity(request: Request):
    """检查文档完整性:验证元数据中的文件/图片是否真实存在于磁盘。

    # ── 检查项

    - 原文件是否存在
    - chunk_out 目录是否存在(支持模糊匹配)
    - 图片文件是否存在(支持 hash 不精确匹配)

    Returns:
        JSONResponse: 包含 total_documents / healthy / problematic / total_chunks /
        total_images / healthy_images / missing_images 及 issues 详情。

    Raises:
        HTTPException 500: 检查失败。
    """
    try:
        vs = system.vector_store
        if not vs or not vs.metadata:
            return JSONResponse(content={
                "available": False,
                "message": "向量存储未初始化或无数据",
            })

        metadata = vs.metadata
        uploads_base = Path(conf.data_dir) / "uploads"

        docs: dict[tuple[str, str], dict] = {}
        for m in metadata:
            key = (m.get("partition", "") or "", m.get("source", "") or "")
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

        total_images = 0
        healthy_images = 0
        missing_images = 0
        issues = []
        healthy_docs = 0


        for (partition, source), info in docs.items():
            stem = Path(source).stem
            doc_issues = []


            source_file = uploads_base / partition / source
            source_exists = source_file.exists()
            if not source_exists:
                doc_issues.append(f"原文件缺失")


            chunk_dir = uploads_base / partition / "chunk_out" / stem
            chunk_exists = chunk_dir.is_dir()
            if not chunk_exists:
                fuzzy_dirs = sorted(glob.glob(str(uploads_base / partition / "chunk_out" / f"{stem}*")))
                if fuzzy_dirs:
                    chunk_dir = Path(fuzzy_dirs[0])
                    chunk_exists = True
                    doc_issues.append(f"chunk_out 目录名不精确 (实际: {chunk_dir.name})")
                else:
                    doc_issues.append(f"chunk_out 目录缺失")


            img_missing_count = 0
            img_hash_mismatch = 0
            for img_path in info["image_records"]:
                total_images += 1
                if not chunk_exists:
                    missing_images += 1
                    continue

                expected = chunk_dir / img_path
                candidates = glob.glob(str(expected))

                if not candidates:
                    candidates = sorted(glob.glob(str(expected) + "*"))
                if candidates:
                    healthy_images += 1

                    if Path(candidates[0]).name != Path(img_path).name:
                        img_hash_mismatch += 1
                else:
                    missing_images += 1
                    img_missing_count += 1

            severity = "healthy"
            if doc_issues:
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
                    "chunk_exists": chunk_exists,
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



@router.get("/database/system_docs")
@auth_required
@admin_required
async def list_system_docs(request: Request):
    """列出所有系统级文档(不属于任何用户分区)。

    Args:
        request: FastAPI 请求对象。

    Returns:
        JSONResponse: ``{"documents": [{"name": str, "chunks": int}, ...]}``,
        按文件名排序。

    Raises:
        HTTPException 500: 查询失败。
    """
    try:
        docs = system.vector_store.get_documents_by_partition(partition=SYSTEM_PARTITION) or []

        doc_chunks = {}
        if system.vector_store.metadata:
            for m in system.vector_store.metadata:
                src = m.get("source", "")
                if m.get("partition") == SYSTEM_PARTITION and src:
                    doc_chunks[src] = doc_chunks.get(src, 0) + 1
        items = []
        for d in sorted(docs):
            items.append({"name": d, "chunks": doc_chunks.get(d, 0)})
        return JSONResponse(content={"documents": items})
    except Exception as e:
        logger.error(f"获取系统文档列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/database/upload")
@auth_required
@admin_required
async def upload_system_data(request: Request, files: list[UploadFile] = File(...)):
    """上传系统级数据文档(后台处理,不阻塞)。

    # ── 处理流程

    1. 接收文件并保存到 ``uploads/__system__/`` 目录
    2. 后台线程逐文件处理:清除旧数据 → 向量化入库(MinerU 并发受 ``mineru_max_concurrency`` 限制)
    3. 可通过 ``GET /database/upload/status`` 查询任务状态

    Args:
        request: FastAPI 请求对象。
        files: 上传的文件列表。

    Returns:
        JSONResponse: ``{"task_id": str, "message": str, "files": [...]}``,立即返回不等待处理完成。

    Raises:
        HTTPException 400: 未提供文件。
        HTTPException 500: 接收失败。
    """
    if not files:
        raise HTTPException(status_code=400, detail="未提供文件")

    task_id = "upload_" + _uuid.uuid4().hex[:8]
    total = len(files)
    tasks = []

    for file in files:
        content = await file.read()
        if not content:
            continue

        filename = os.path.basename(file.filename)
        save_dir = f"{conf.data_dir}/uploads/{SYSTEM_PARTITION}"
        save_path = os.path.normpath(os.path.join(save_dir, filename))
        if not save_path.startswith(os.path.normpath(save_dir)):
            logger.warning(f"非法文件路径: {filename}")
            continue

        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(content)

        tasks.append((filename, save_path))

    _upload_tasks[task_id] = {
        "filenames": [t[0] for t in tasks],
        "status": "processing",
        "total": len(tasks),
        "success": 0,
        "fail": 0,
        "failures": [],
    }

    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    _mineru_sem = threading.Semaphore(
        getattr(conf, 'mineru_max_concurrency', 3)
    )

    def _process_one(fname, fpath):
        """处理单个文件: 删除旧数据 → 解析入库(受 MinerU 并发限制)。"""
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


@router.get("/database/upload/status")
@auth_required
@admin_required
async def get_upload_status(request: Request):
    """查询最近的上传任务状态。

    Args:
        request: FastAPI 请求对象。

    Returns:
        JSONResponse: 有活跃任务时返回 ``{"status": "processing", "task_id": str, "task": dict}``;
        有已完成任务时返回 ``{"status": "finished", ...}``;
        空闲时返回 ``{"status": "idle"}``。
    """


    active = {k: v for k, v in _upload_tasks.items() if v["status"] == "processing"}
    if active:
        tid, task = list(active.items())[-1]
        return JSONResponse(content={"task_id": tid, "status": "processing", "task": task})

    finished = {k: v for k, v in _upload_tasks.items() if v["status"] == "finished"}
    if finished:
        tid, task = list(finished.items())[-1]
        return JSONResponse(content={"task_id": tid, "status": "finished", "task": task})

    return JSONResponse(content={"status": "idle"})


@router.delete("/database/delete")
@auth_required
@admin_required
async def delete_document(request: Request, source: str = Query(...), partition: str = Query(...)):
    """删除指定分区中的指定文档(系统数据或用户数据)。

    # ── 清理范围

    - 向量库中的文档 (delete_documents_by_sources)
    - 暂存目录下的原文件
    - chunk_out 目录

    Args:
        request: FastAPI 请求对象。
        source: 文档来源文件名。
        partition: 分区名。

    Returns:
        JSONResponse: ``{"message": "文档 'xxx' 已从 yyy 删除"}``。

    Raises:
        HTTPException 400: 缺少参数。
        HTTPException 500: 删除失败。
    """
    try:
        if not source or not partition:
            raise HTTPException(status_code=400, detail="缺少参数 source 或 partition")


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

        logger.info(f"管理员删除文档: source={source}, partition={partition}")
        return JSONResponse(content={"message": f"文档 '{source}' 已从 {partition} 删除"})
    except Exception as e:
        logger.error(f"删除文档失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/database/batch_delete")
@auth_required
@admin_required
async def batch_delete_documents(request: Request):
    """批量删除指定分区中的多个文档。

    Args:
        request: FastAPI 请求对象,包含 JSON 体 ``{"sources": [str, ...], "partition": str}``。

    Returns:
        JSONResponse: ``{"message": str, "deleted": [str], "errors": [...]}``。

    Raises:
        HTTPException 400: 缺少参数。
        HTTPException 500: 批量删除失败。
    """
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
