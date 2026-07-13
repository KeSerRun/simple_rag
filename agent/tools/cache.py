"""工具缓存模块：跨工具共享的内存缓存，支持 TTL 和 LRU 淘汰。"""
from __future__ import annotations

import time as _time

_cache: dict[str, tuple[str, float]] = {}
_max_size = 100
_ttl = 300  # 5 分钟


def get(key: str) -> str | None:
    """读取缓存，过期或不存在返回 None。"""
    entry = _cache.get(key)
    if entry is None:
        return None
    content, ts = entry
    if _time.time() - ts > _ttl:
        del _cache[key]
        return None
    return content


def set(key: str, content: str):
    """写入缓存，超限时淘汰最旧条目。"""
    if len(_cache) >= _max_size:
        oldest = min(_cache.items(), key=lambda x: x[1][1])
        del _cache[oldest[0]]
    _cache[key] = (content, _time.time())


def clear():
    """清空缓存。"""
    _cache.clear()
