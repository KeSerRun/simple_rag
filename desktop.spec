# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置 —— 将 RAG Simple 桌面应用打包为 rag-simple.exe。

用法:
    pyinstaller desktop.spec
"""

import os
import sys

# 项目根目录（spec 文件所在目录，即当前工作目录）
ROOT = os.getcwd()

block_cipher = None

a = Analysis(
    ["desktop.py"],
    pathex=[ROOT],
    binaries=[],
    datas=[
        # 前端构建产物（Vite 构建后的 dist/）
        (os.path.join(ROOT, "dist"), "dist"),
        # 提示词模板
        (os.path.join(ROOT, "prompts"), "prompts"),
    ],
    hiddenimports=[
        # ── FastAPI / uvicorn（动态加载较多） ──
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.middleware",
        "uvicorn.middleware.wsgi",
        "fastapi",
        "fastapi.routing",
        "fastapi.openapi",
        "starlette",
        "starlette.routing",
        "starlette.middleware",
        "starlette.middleware.cors",
        "starlette.staticfiles",
        "starlette.responses",
        "starlette.requests",
        "starlette.datastructures",
        "pydantic",
        "pydantic_settings",
        "anyio",
        "sniffio",
        "multipart",
        # ── 应用模块 ──
        "app",
        "api",
        "api.admin",
        "api.auth",
        "api.documents",
        "api.history",
        "api.query",
        "api.sessions",
        "api.deps",
        "base",
        "base.config",
        "base.logger",
        "base.llm_client",
        "agent",
        "agent.loop",
        "agent.integrate",
        "agent.state",
        "agent.context",
        "agent.governor",
        "agent.tools",
        "agent.tools.registry",
        "agent.tools._kb_handlers",
        "agent.tools._web_handlers",
        "agent.tools._infra_handlers",
        "agent.tools._format",
        "agent.tools.cache",
        "rag",
        "rag.vector_store",
        "rag.pdf_parser",
        "rag.eval_rag",
        "storage",
        "storage.json_store",
        "storage.base",
        # ── LLM 客户端 ──
        "openai",
        "openai.resources",
        "tiktoken",
        "tiktoken_ext",
        "tiktoken_ext.openai_public",
        # ── HTTP 客户端 ──
        "httpx",
        "httpcore",
        "h2",
        "hpack",
        "hyperframe",
        "brotli",
        # ── 向量库 ──
        "faiss",
        "numpy",
        # ── PDF / OCR ──
        "fitz",
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
        "PIL.ImageFont",
        "cv2",
        "rapidocr_onnxruntime",
        "rapidocr_onnxruntime.text_recognize",
        # ── 搜索 ──
        "duckduckgo_search",
        "ddgs",
        "requests",
        "beautifulsoup4",
        "bs4",
        "lxml",
        "lxml.html",
        "lxml.html.clean",
        "lxml.etree",
        "readability",
        "readability.readability",
        # ── 工具 & 日志 ──
        "rich",
        "rich.markdown",
        "rich.console",
        "rich.table",
        "tqdm",
        "yaml",
        "jwt",
        "PyJWT",
        # ── PyWebView ──
        "webview",
        "webview.platforms",
        "webview.platforms.win32_edge",
        "webview.util",
        "bottle",
        "proxy_tools",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "tkinterdnd2",
        "matplotlib",
        "scipy",
        "scipy.spatial",
        "scipy.special",
        "test",
        "unittest",
        "unittest.mock",
        "distutils",
        "setuptools._distutils",
        "pdb",
        "pyprof2calltree",
        "cProfile",
        "profile",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="rag-simple",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 不显示黑窗；日志写入 logs/ 目录
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, "dist", "favicon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="rag-simple",
)
