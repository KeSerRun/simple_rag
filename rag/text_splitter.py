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


class ChineseRecursiveTextSplitter:
    """中文友好的递归字符切分器。

    按优先级从高到低尝试分隔符列表，递归切分文本，
    使每个片段不超过 chunk_size，支持保留分隔符和正则分隔符。

    Attributes:
        chunk_size: 每个 chunk 的最大字符数。
        chunk_overlap: chunk 之间的重叠字符数。
        separators: 分隔符列表（支持正则表达式），按优先级从高到低排列。
        keep_separator: 切分时是否保留分隔符在左侧片段末尾。
        is_separator_regex: separators 中的元素是否为正则表达式。
    """

    DEFAULT_SEPARATORS = [
        "\n\n",
        "\n",
        r"。|！|？",
        r"\.|\!|\?",
        r"；|;",
        r"，|,",
        " ",
        "",
    ]
    """默认分隔符列表，优先级从高到低，包含中文标点。"""

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        separators: Optional[List[str]] = None,
        keep_separator: bool = True,
        is_separator_regex: bool = True,
    ):
        """初始化文本切分器。

        Args:
            chunk_size: 每个 chunk 的最大字符数。
            chunk_overlap: chunk 之间的重叠字符数。
            separators: 分隔符列表；默认使用 DEFAULT_SEPARATORS。
            keep_separator: 切分时是否保留分隔符在左侧片段末尾。
            is_separator_regex: separators 中的元素是否为正则表达式。

        Raises:
            ValueError: 当 chunk_overlap >= chunk_size 时抛出。
        """
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap 必须小于 chunk_size")

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or list(self.DEFAULT_SEPARATORS)
        self.keep_separator = keep_separator
        self.is_separator_regex = is_separator_regex

    # ── 文档级切分 ────────────────────────────────────────────────

    def split_text(self, text: str) -> List[str]:
        """接收一段文本，返回切分后的字符串列表。

        Args:
            text: 要切分的原始字符串。

        Returns:
            切分后的字符串列表，每个元素是一个 chunk。
        """
        if not text:
            return []
        chunks = self._split(text, self.separators)
        return [re.sub(r"\n{2,}", "\n", c.strip()) for c in chunks if c.strip()]

    def split_documents(self, documents: List[Document]) -> List[Document]:
        """接收 Document 对象列表，对每个 Document 的正文做切分。

        每个切分结果生成一个新的 Document（保留原元数据）。

        Args:
            documents: Document 对象的列表。

        Returns:
            切分后新的 Document 对象列表。
        """
        from .vector_store import Document
        result: List[Document] = []
        for doc in documents:
            for chunk in self.split_text(doc.page_content):
                result.append(Document(page_content=chunk, metadata=dict(doc.metadata)))
        return result

    # ── 递归切分核心 ──────────────────────────────────────────────

    def _split(self, text: str, separators: List[str]) -> List[str]:
        """递归切分文本。

        按照 separators 顺序尝试用分隔符切分，
        如果某段仍然太长，继续用更细的分隔符递归切分。

        Args:
            text: 当前要切分的文本。
            separators: 当前层可用的分隔符列表（优先级从高到低）。

        Returns:
            切分后的字符串列表。
        """
        final_chunks = []

        separator = separators[-1]
        new_separators = []

        for i, _s in enumerate(separators):
            _separator = _s
            if self.is_separator_regex:
                if self._is_regex_safe(_separator):
                    if re.search(_separator, text):
                        separator = _separator
                        new_separators = separators[i + 1:]
                        break
                else:
                    if _separator in text:
                        separator = _separator
                        new_separators = separators[i + 1:]
                        break
            else:
                if _separator in text:
                    separator = _separator
                    new_separators = separators[i + 1:]
                    break

        if separator:
            splits = self._split_text_with_regex(text, separator, self.keep_separator)
        else:
            splits = list(text)

        _good_splits = []
        _separator = ""
        for s in splits:
            if self._is_regex_safe(separator):
                _separator = separator if self.keep_separator else ""
            else:
                _separator = ""

            if len(s) < self.chunk_size:
                _good_splits.append(s)
            else:

                if _good_splits:
                    merged = self._merge_splits(_good_splits, _separator)
                    final_chunks.extend(merged)
                    _good_splits = []

                if not new_separators:
                    final_chunks.extend(
                        self._split_text_with_regex(s, "", False, self.chunk_size)
                    )
                else:
                    final_chunks.extend(self._split(s, new_separators))

        if _good_splits:
            merged = self._merge_splits(_good_splits, _separator)
            final_chunks.extend(merged)

        return final_chunks

    # ── 切分与合并工具 ────────────────────────────────────────────

    @staticmethod
    def _split_text_with_regex(
        text: str,
        separator: str,
        keep_separator: bool,
        max_chunk: int = None
    ) -> List[str]:
        """根据分隔符（支持正则）切分文本。

        可选择保留分隔符或按最大长度切分。

        Args:
            text: 要切分的原始文本。
            separator: 分隔符（支持正则表达式）。
            keep_separator: 为 True 时，分隔符保留在左侧片段末尾。
            max_chunk: 如果不为 None，强制每个片段不超过此长度。

        Returns:
            切分后的字符串列表。
        """
        if separator:
            if keep_separator:
                splits = re.split(f"({separator})", text)
                result = []
                for i in range(0, len(splits) - 1, 2):
                    result.append(splits[i] + splits[i + 1])
                if len(splits) % 2 == 1:
                    result.append(splits[-1])
                splits = result
            else:
                splits = re.split(separator, text)
        else:
            splits = list(text)

        return [s for s in splits if s]

    @staticmethod
    def _merge_splits(splits: List[str], separator: str) -> List[str]:
        """将多个小片段合并成大小合适的块（不超过 750 字符）。

        Args:
            splits: 小片段列表。
            separator: 拼接时使用的连接符。

        Returns:
            合并后的块列表。
        """
        merged = []
        current = []
        total = 0
        for s in splits:
            _len = len(s)
            if total + _len > 750:
                if current:
                    merged.append(separator.join(current))
                    current = []
                total = 0
            current.append(s)
            total += _len
        if current:
            merged.append(separator.join(current))
        return merged

    @staticmethod
    def _is_regex_safe(s: str) -> bool:
        """检查字符串能否作为合法正则表达式编译。

        Args:
            s: 待检查的字符串。

        Returns:
            该字符串能否作为合法正则表达式。
        """
        try:
            re.compile(s)
            return True
        except re.error:
            return False
