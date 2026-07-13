# ── 中文递归文本切分器 ───────────────────────────────────────────
"""中文友好的递归字符切分器。

把一段长文本递归地按照一组分隔符（段落、句号、逗号等）
切成多个小片段（chunks），每个片段不会超过 chunk_size 限制。
适合中文场景，分隔符包含中文标点。
"""

from __future__ import annotations

import re

from typing import TYPE_CHECKING, List, Optional


if TYPE_CHECKING:
    from .vector_store import Document
