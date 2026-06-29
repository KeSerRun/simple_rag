"""HTTP 接口模块,按业务域分文件:auth / sessions / history / query / documents

入口 app.py 通过 `include_router` 注册:

    from api import auth, sessions, history, query, documents
    app.include_router(auth.router)
    ...
"""
from . import auth, documents, history, query, sessions

__all__ = ["auth", "documents", "history", "query", "sessions"]
