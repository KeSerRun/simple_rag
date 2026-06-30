from dataclasses import dataclass, field


@dataclass
class Document:
    """轻量文档容器,替代 langchain_core.documents.Document"""
    page_content: str
    metadata: dict = field(default_factory=dict)
