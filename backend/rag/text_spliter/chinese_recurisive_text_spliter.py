from __future__ import annotations
import re
from typing import List, Optional


class ChineseRecursiveTextSplitter:
    """中文友好的递归字符切分器,纯 Python 实现,不依赖 langchain。"""

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

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        separators: Optional[List[str]] = None,
        keep_separator: bool = True,
        is_separator_regex: bool = True,
    ):
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap 必须小于 chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or list(self.DEFAULT_SEPARATORS)
        self.keep_separator = keep_separator
        self.is_separator_regex = is_separator_regex

    def split_text(self, text: str) -> List[str]:
        if not text:
            return []
        chunks = self._split(text, self.separators)
        return [re.sub(r"\n{2,}", "\n", c.strip()) for c in chunks if c.strip()]

    def split_documents(self, documents: List[Document]) -> List[Document]:
        from ..core.document_process import Document
        result: List[Document] = []
        for doc in documents:
            for chunk in self.split_text(doc.page_content):
                result.append(Document(page_content=chunk, metadata=dict(doc.metadata)))
        return result

    def _split(self, text: str, separators: List[str]) -> List[str]:
        if len(text) <= self.chunk_size:
            return [text]
        separator = separators[-1]
        next_separators: List[str] = []
        for i, s in enumerate(separators):
            pattern = s if self.is_separator_regex else re.escape(s)
            if s == "":
                separator = s
                break
            if re.search(pattern, text):
                separator = s
                next_separators = separators[i + 1:]
                break
        splits = self._regex_split(text, separator)
        good: List[str] = []
        final: List[str] = []
        sep_for_merge = "" if self.keep_separator else separator
        for piece in splits:
            if len(piece) < self.chunk_size:
                good.append(piece)
            else:
                if good:
                    final.extend(self._merge(good, sep_for_merge))
                    good = []
                if next_separators:
                    final.extend(self._split(piece, next_separators))
                else:
                    final.append(piece)
        if good:
            final.extend(self._merge(good, sep_for_merge))
        return final

    def _regex_split(self, text: str, separator: str) -> List[str]:
        if separator == "":
            return list(text)
        pattern = separator if self.is_separator_regex else re.escape(separator)
        if self.keep_separator:
            parts = re.split(f"({pattern})", text)
            merged = ["".join(p) for p in zip(parts[0::2], parts[1::2])]
            if len(parts) % 2 == 1:
                merged.append(parts[-1])
            return [s for s in merged if s]
        return [s for s in re.split(pattern, text) if s]

    def _merge(self, splits: List[str], separator: str) -> List[str]:
        sep_len = len(separator)
        chunks: List[str] = []
        cur: List[str] = []
        total = 0
        for s in splits:
            slen = len(s)
            if cur and total + slen + (sep_len if cur else 0) > self.chunk_size:
                chunks.append(separator.join(cur))
                while cur and (total > self.chunk_overlap or
                               (total + slen + sep_len > self.chunk_size and total > 0)):
                    popped = cur.pop(0)
                    total -= len(popped) + (sep_len if cur else 0)
            cur.append(s)
            total += slen + (sep_len if len(cur) > 1 else 0)
        if cur:
            chunks.append(separator.join(cur))
        return chunks
