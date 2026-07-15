"""Search orchestration: multi-source fetch -> merge & dedup -> score & rank.

Pure business logic extracted from cli.cmd_search; no argparse dependency, no direct print.
Progress is reported via an optional log callback (cli passes a function that writes to
stderr), so this pipeline can be unit-tested independently of the command line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from .config import Config
from .models import Paper
from .score import score_papers

KNOWN_SOURCES = {"arxiv", "s2", "dblp"}

# Progress callback: receives one human-readable line (cli writes to stderr; tests can pass None to ignore)
LogFn = Callable[[str], None]


def _noop(_: str) -> None:
    pass


def dedup_papers(papers: list[Paper]) -> list[Paper]:
    """Dedup by paper_id first, then by normalized title. Keep the first seen (usually higher citation count / more relevant)."""
    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    out: list[Paper] = []
    for p in papers:
        pid = (p.paper_id or "").strip()
        if pid:
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            out.append(p)
        else:
            norm = re.sub(r"[^a-z0-9\s]", "", (p.title or "").lower()).strip()
            if norm and norm in seen_titles:
                continue
            if norm:
                seen_titles.add(norm)
            out.append(p)
    return out


def _fetch_one(src: str, query: str | None, cfg: Config, *,
               days: int | None, max_results: int, log: LogFn) -> list[Paper]:
    """Fetch papers from a single source. Errors inside a source raise RuntimeError, caught and skipped by the caller."""
    if src == "arxiv":
        from .adapters import arxiv

        if query:
            log(f"[arxiv] 关键词检索：{query}")
            kws = [k.strip() for k in query.split(",") if k.strip()]
            return arxiv.search_by_keywords(kws, days=days, max_results=max_results)
        cats = cfg.all_categories()
        if not cats:
            log("config 无 arXiv 分类且未提供查询词，跳过 arxiv")
            return []
        d = days if days is not None else 30
        log(f"[arxiv] 按 config 分类检索（近 {d} 天）：{','.join(cats)}")
        return arxiv.search_by_categories(cats, days=d, max_results=max_results)

    if src == "s2":
        from .adapters import semantic_scholar

        q = query or (" ".join(cfg.domains[0].keywords[:3]) if cfg.domains else None)
        if not q:
            log("s2 需要查询词或 config 领域，跳过 s2")
            return []
        log(f"[s2] 检索：{q}")
        return semantic_scholar.search(q, limit=max_results, api_key=cfg.semantic_scholar_api_key)

    # dblp
    from .adapters import dblp

    q = query or (" ".join(cfg.domains[0].keywords[:3]) if cfg.domains else "")
    if not q:
        log("dblp 需要查询词或 config 领域，跳过 dblp")
        return []
    log(f"[dblp] 检索：{q}")
    return dblp.search(q, limit=max_results)


@dataclass
class SearchResult:
    """Result of one search orchestration. to_dict() is for the cli to emit JSON directly."""

    query: str
    sources: list[str]
    total_fetched: int
    total_scored: int
    top_papers: list[Paper] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "sources": self.sources,
            "total_fetched": self.total_fetched,
            "total_scored": self.total_scored,
            "top_papers": [p.to_dict() for p in self.top_papers],
        }


def search_papers(cfg: Config, query: str | None, sources: list[str], *,
                  top_n: int = 10, days: int | None = None,
                  max_results: int = 200, log: LogFn | None = None) -> SearchResult:
    """Run the full search pipeline. A single source failing only skips that source, not the rest."""
    emit = log or _noop
    papers: list[Paper] = []
    for src in sources:
        try:
            got = _fetch_one(src, query, cfg, days=days, max_results=max_results, log=emit)
        except RuntimeError as e:
            emit(f"[{src}] 失败（跳过）：{e}")
            got = []
        emit(f"[{src}] 拉回 {len(got)} 篇")
        papers.extend(got)

    papers = dedup_papers(papers)
    emit(f"合并去重后 {len(papers)} 篇，开始打分筛选")
    scored = score_papers(papers, cfg)
    return SearchResult(
        query=query or "",
        sources=sources,
        total_fetched=len(papers),
        total_scored=len(scored),
        top_papers=scored[:top_n],
    )
