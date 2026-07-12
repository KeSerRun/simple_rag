
from __future__ import annotations

import re

from typing import TYPE_CHECKING, List, Optional


if TYPE_CHECKING:
    from .vector_store import Document



class ChineseRecursiveTextSplitter:
    """中文友好的递归字符切分器。

    这个类的作用是把一段长文本递归地按照一组分隔符（比如段落、句号、逗号等）
    切成多个小片段（chunks），每个片段不会超过 chunk_size 限制。
    适合中文场景，分隔符包含中文标点。
    """


    # 这是类的默认分隔符列表，切分时会按这个顺序尝试：
    # 先用段落分隔（双换行），再按单换行，再按中文句号/问号，以此类推
    DEFAULT_SEPARATORS = [
        "\n\n",                      # 两个换行符 —— 段落之间的分隔
        "\n",                        # 单个换行符
        r"。|！|？",                  # 中文句号、感叹号、问号（正则表达式形式）
        r"\.|\!|\?",                 # 英文句号、感叹号、问号（正则表达式形式）
        r"；|;",                     # 中文分号、英文分号
        r"，|,",                     # 中文逗号、英文逗号
        " ",                         # 空格
        "",                          # 空字符串 —— 兜底，每个字符单独成段
    ]


    def __init__(
        self,
        chunk_size: int = 500,        # 每个文本块的最大字符数，默认 500
        chunk_overlap: int = 50,      # 相邻块之间重叠的字符数，默认 50
        separators: Optional[List[str]] = None,  # 自定义分隔符列表，不传则用上面的默认值
        keep_separator: bool = True,  # 切分时是否保留分隔符本身在结果中
        is_separator_regex: bool = True,  # separators 里的字符串是否按正则表达式来解析
    ):

        # 如果重叠部分 >= 块大小，那切分没有意义，直接报错
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap 必须小于 chunk_size")


        self.chunk_size = chunk_size              # 保存每块字符数的上限
        self.chunk_overlap = chunk_overlap        # 保存重叠字符数
        # 如果没有传 separators，就用类属性 DEFAULT_SEPARATORS 的副本（list() 防篡改）
        self.separators = separators or list(self.DEFAULT_SEPARATORS)
        self.keep_separator = keep_separator      # 是否保留分隔符
        self.is_separator_regex = is_separator_regex  # 分隔符是否当作正则处理


    def split_text(self, text: str) -> List[str]:
        """
        接收一段文本，返回切分后的字符串列表。

        参数:
            text: 要切分的原始字符串

        返回:
            切分后的字符串列表，每个元素是一个 chunk
        """
        # 如果文本是空字符串或 None，直接返回空列表
        if not text:
            return []
        # 调用内部的 _split 方法进行递归切分，传入文本和当前使用的分隔符列表
        chunks = self._split(text, self.separators)
        # 对每个 chunk：去掉首尾空格，把连续 2 个以上的换行符替换成 1 个，
        return [re.sub(r"\n{2,}", "\n", c.strip()) for c in chunks if c.strip()]


    def split_documents(self, documents: List[Document]) -> List[Document]:
        """
        接收一个 Document 对象列表，对每个 Document 的正文做切分，
        每个切分结果生成一个新的 Document（保留原元数据）。

        参数:
            documents: Document 对象的列表

        返回:
            切分后新的 Document 对象列表
        """
        # 在函数内部导入 Document，避免模块顶层的循环导入问题
        from .vector_store import Document
        # 准备一个空列表，用来存放切分后生成的 Document
        result: List[Document] = []
        for doc in documents:
            # 对当前 doc 的 page_content（正文）做切分，逐个拿到切出的 chunk
            for chunk in self.split_text(doc.page_content):
                # 创建一个新的 Document，正文是 chunk，元数据拷贝自原文档（用 dict() 做浅拷贝）
                result.append(Document(page_content=chunk, metadata=dict(doc.metadata)))
        # 返回所有新生成的 Document 列表
        return result


    def _split(self, text: str, separators: List[str]) -> List[str]:
        """
        递归切分文本。按照 separators 顺序尝试用分隔符切分，
        如果某段仍然太长，继续用更细的分隔符递归切分。

        参数:
            text:        当前要切分的文本
            separators:  当前层可用的分隔符列表（优先级从高到低）

        返回:
            切分后的字符串列表
        """
        # 最终要返回的所有 chunk 将存放在这里
        final_chunks = []

        # separator 初始化为分隔符列表的最后一个元素（最细粒度的分隔符，即空字符串）
        separator = separators[-1]
        # new_separators 用于记录"当前分隔符之后的更细粒度分隔符"
        new_separators = []


        # 遍历 separators 列表，找到第一个能在 text 中匹配到的分隔符
        for i, _s in enumerate(separators):
            _separator = _s  # 取出当前这个分隔符
            # 如果分隔符按正则解析，则调用 _is_regex_safe 检查正则是否合法
            if self.is_separator_regex:
                if self._is_regex_safe(_separator):
                    # 用正则搜索 text 是否包含这个分隔符
                    if re.search(_separator, text):
                        separator = _separator          # 选中这个分隔符
                        new_separators = separators[i + 1:]  # 剩余更细的分隔符留给递归
                        break  # 找到了就跳出循环
                else:
                    # 如果分隔符不是合法正则，就当作普通字符串判断是否在 text 中
                    if _separator in text:
                        separator = _separator
                        new_separators = separators[i + 1:]
                        break
            else:
                # 不分隔符不当作正则，直接当作普通字符串判断
                if _separator in text:
                    separator = _separator
                    new_separators = separators[i + 1:]
                    break


        # 如果找到了一个有效的分隔符（非空字符串）
        if separator:
            # 调用 _split_text_with_regex 按正则/普通字符串切分
            splits = self._split_text_with_regex(text, separator, self.keep_separator)
        else:
            # 没有找到有效分隔符，就把文本拆成单个字符的列表
            splits = list(text)


        _good_splits = []   # 存放当前长度小于 chunk_size 的"好的"片段
        _separator = ""     # 记录当前使用的分隔符（用于后面合并）
        for s in splits:
            # 判断当前使用的 separator 是否是合法正则
            if self._is_regex_safe(separator):
                # 如果 keep_separator 为 True，保留分隔符；否则用空字符串拼接
                _separator = separator if self.keep_separator else ""
            else:
                _separator = ""

            # 如果当前片段的长度小于 chunk_size，说明它合格，先存起来
            if len(s) < self.chunk_size:
                _good_splits.append(s)
            else:

                # 先把之前攒的合格小片段合并成 chunk
                if _good_splits:
                    merged = self._merge_splits(_good_splits, _separator)
                    final_chunks.extend(merged)  # 把合并结果塞入最终列表
                    _good_splits = []            # 清空缓存

                if not new_separators:
                    # 直接强制按 chunk_size 切分（不管语义了）
                    final_chunks.extend(
                        self._split_text_with_regex(s, "", False, self.chunk_size)
                    )
                else:
                    # 还有更细的分隔符，递归调用 _split 继续切分
                    final_chunks.extend(self._split(s, new_separators))


        if _good_splits:
            merged = self._merge_splits(_good_splits, _separator)
            final_chunks.extend(merged)

        return final_chunks


    @staticmethod
    def _split_text_with_regex(
        text: str,
        separator: str,
        keep_separator: bool,
        max_chunk: int = None
    ) -> List[str]:
        """
        根据分隔符（支持正则）切分文本，可选择保留分隔符或按最大长度切分。

        参数:
            text:           要切分的原始文本
            separator:      分隔符（支持正则表达式）
            keep_separator: 为 True 时，分隔符保留在左侧片段末尾
            max_chunk:      如果不为 None，强制每个片段不超过此长度

        返回:
            切分后的字符串列表
        """
        if separator:
            if keep_separator:
                # 用正则捕获组 (separator) 切分，这样分隔符会出现在结果列表中
                splits = re.split(f"({separator})", text)
                result = []
                for i in range(0, len(splits) - 1, 2):
                    result.append(splits[i] + splits[i + 1])
                # 如果 splits 长度是奇数，最后会多一个无分隔符的尾巴，单独加进去
                if len(splits) % 2 == 1:
                    result.append(splits[-1])
                splits = result
            else:
                # 不保留分隔符，直接用 separator 做普通 split
                splits = re.split(separator, text)
        else:
            splits = list(text)

        # 如果传入了 max_chunk，需要额外按最大长度切分（这里仅返回非空片段）
        # 注意：这个方法的 max_chunk 参数目前未被实现强制切分，
        return [s for s in splits if s]


    @staticmethod
    def _merge_splits(splits: List[str], separator: str) -> List[str]:
        """
        将多个小片段合并成大小合适的块（不超过 750 字符）。
        注意：此处写死的 750 并非使用 self.chunk_size，可能是设计如此或疏漏。

        参数:
            splits:    小片段列表
            separator: 拼接时使用的连接符

        返回:
            合并后的块列表
        """
        merged = []   # 存放最终合并好的块
        current = []  # 当前正在累积的片段列表
        total = 0     # 当前累积的字符总数
        for s in splits:
            _len = len(s)               # 当前片段的长度
            # 如果加上当前片段会超过 750 字符（这里写死 750，非 self.chunk_size）
            if total + _len > 750:
                # 如果 current 不为空，把它合并成一个字符串并加入 merged
                if current:
                    merged.append(separator.join(current))
                    current = []  # 重置
                total = 0          # 重置计数器
            current.append(s)      # 把当前片段加入累积列表
            total += _len          # 更新总长度
        if current:
            merged.append(separator.join(current))
        return merged


    @staticmethod
    def _is_regex_safe(s: str) -> bool:
        """
        尝试把字符串编译成正则表达式，如果成功返回 True，否则返回 False。

        参数:
            s: 待检查的字符串

        返回:
            该字符串能否作为合法正则表达式
        """
        try:
            # 尝试用 re.compile 编译这个字符串
            re.compile(s)
            return True   # 编译成功，是合法正则
        except re.error:
            # 编译抛出了 re.error 异常，说明不是合法正则
            return False
