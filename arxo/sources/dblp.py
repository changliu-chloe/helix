"""DBLP 来源适配器（会议/期刊论文）。

用 DBLP 公开的 publ search API（JSON）。DBLP 不提供摘要和引用数，
主要贡献是权威的会议/期刊 venue 信息，venue 存入 categories 便于打分/展示。
"""

from __future__ import annotations

import html
import json
import time
import urllib.parse
import urllib.request

from ..models import Paper

DBLP_SEARCH_API = "https://dblp.org/search/publ/api"


def _request(url: str, max_retries: int = 3, timeout: int = 20) -> dict:
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "arxo/0.1"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < max_retries - 1:
                time.sleep((2 ** attempt) * 2)
    raise RuntimeError(f"DBLP 请求失败（重试 {max_retries} 次）：{last_err}")


def _authors(info: dict) -> list[str]:
    a = info.get("authors")
    if not a:
        return []
    authors = a.get("author")
    if isinstance(authors, dict):
        authors = [authors]
    out = []
    for au in authors or []:
        if isinstance(au, dict):
            name = au.get("text", "")
        else:
            name = str(au)
        if name:
            out.append(name)
    return out


def _to_paper(hit: dict) -> Paper | None:
    info = hit.get("info") or {}
    title = info.get("title")
    if not title:
        return None
    venue = info.get("venue", "")
    venues = venue if isinstance(venue, list) else ([venue] if venue else [])
    year = str(info.get("year", ""))
    return Paper(
        paper_id=info.get("key", "") or hit.get("@id", ""),
        title=html.unescape(title.strip().rstrip(".")),
        authors=[html.unescape(a) for a in _authors(info)],
        abstract="",  # DBLP 不提供摘要
        published=year,
        categories=venues,  # venue 放进 categories
        source="dblp",
        url=info.get("ee", "") or info.get("url", ""),
        pdf_url="",
        citation_count=None,
    )


def search(query: str, limit: int = 50) -> list[Paper]:
    """按查询词检索 DBLP，返回会议/期刊论文 Paper 列表。"""
    params = {"q": query, "format": "json", "h": str(min(limit, 100))}
    url = f"{DBLP_SEARCH_API}?{urllib.parse.urlencode(params)}"
    data = _request(url)
    hits = (((data.get("result") or {}).get("hits") or {}).get("hit")) or []
    papers: list[Paper] = []
    for hit in hits:
        p = _to_paper(hit)
        if p is not None:
            papers.append(p)
    return papers
