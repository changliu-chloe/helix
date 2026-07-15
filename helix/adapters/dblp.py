"""DBLP source adapter (conference/journal papers).

Uses DBLP's public publ search API (JSON). DBLP provides no abstracts or
citation counts; its main value is authoritative conference/journal venue
info. The venue is stored in categories for scoring/display.
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
            req = urllib.request.Request(url, headers={"User-Agent": "helix/0.1"})
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
        abstract="",  # DBLP provides no abstract
        published=year,
        categories=venues,  # put venue into categories
        source="dblp",
        url=info.get("ee", "") or info.get("url", ""),
        pdf_url="",
        citation_count=None,
    )


def search(query: str, limit: int = 50) -> list[Paper]:
    """Search DBLP by query, returning a list of conference/journal Paper."""
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
