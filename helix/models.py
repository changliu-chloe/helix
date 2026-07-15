"""Core data models. Source adapters uniformly return Paper."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Paper:
    """Normalized representation of a paper, unified across sources."""

    paper_id: str                       # ID within the source (e.g. arXiv id 2601.12345)
    title: str
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    published: str = ""                 # ISO date YYYY-MM-DD
    categories: list[str] = field(default_factory=list)
    source: str = ""                    # arxiv | s2 | dblp
    url: str = ""
    pdf_url: str = ""
    citation_count: Optional[int] = None

    # Scoring results (populated by score.py)
    score_relevance: float = 0.0
    score_recency: float = 0.0
    score_popularity: float = 0.0
    score_quality: float = 0.0
    score_final: float = 0.0
    matched_domains: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
