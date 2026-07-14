"""核心数据模型。各来源适配器统一返回 Paper。"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Paper:
    """一篇论文的规范化表示，跨来源统一。"""

    paper_id: str                       # 来源内的 ID（如 arXiv id 2601.12345）
    title: str
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    published: str = ""                 # ISO 日期 YYYY-MM-DD
    categories: list[str] = field(default_factory=list)
    source: str = ""                    # arxiv | s2 | dblp
    url: str = ""
    pdf_url: str = ""
    citation_count: Optional[int] = None

    # 打分结果（由 score.py 填充）
    score_relevance: float = 0.0
    score_recency: float = 0.0
    score_popularity: float = 0.0
    score_quality: float = 0.0
    score_final: float = 0.0
    matched_domains: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
