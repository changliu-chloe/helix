"""arXiv source adapter.

Calls the arXiv Atom API, parses the XML, and returns a unified list of Paper.
Ported from ref/evil-read-arxiv/start-my-day/scripts/search_arxiv.py.
"""

from __future__ import annotations

import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from ..models import Paper

ARXIV_API = "https://export.arxiv.org/api/query"
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


def _build_url(search_query: str, max_results: int, sort_by: str) -> str:
    params = {
        "search_query": search_query,
        "max_results": str(max_results),
        "sortBy": sort_by,
        "sortOrder": "descending",
    }
    # In arXiv's search_query, +OR+ and : are semantic; preserve them via safe
    return f"{ARXIV_API}?{urllib.parse.urlencode(params, safe='+:')}"


def _fetch(url: str, max_retries: int = 3, timeout: int = 60) -> str:
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "helix/0.1"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")
        except Exception as e:  # noqa: BLE001 — retry uniformly on network errors
            last_err = e
            if attempt < max_retries - 1:
                time.sleep((2 ** attempt) * 2)
    raise RuntimeError(f"arXiv 请求失败（重试 {max_retries} 次）：{last_err}")


def parse_xml(xml_content: str) -> list[Paper]:
    """Parse arXiv Atom XML into a list of Paper."""
    papers: list[Paper] = []
    root = ET.fromstring(xml_content)
    for entry in root.findall("atom:entry", NS):
        id_elem = entry.find("atom:id", NS)
        raw_id = id_elem.text if id_elem is not None else ""
        arxiv_id = ""
        if raw_id:
            m = re.search(r"arxiv\.org/abs/([^v]+?)(v\d+)?$", raw_id) or re.search(r"/(\d+\.\d+)", raw_id)
            if m:
                arxiv_id = m.group(1)

        title_elem = entry.find("atom:title", NS)
        title = (title_elem.text or "").strip() if title_elem is not None else ""

        summary_elem = entry.find("atom:summary", NS)
        abstract = (summary_elem.text or "").strip() if summary_elem is not None else ""

        authors = []
        for a in entry.findall("atom:author", NS):
            name = a.find("atom:name", NS)
            if name is not None and name.text:
                authors.append(name.text.strip())

        published = ""
        pub_elem = entry.find("atom:published", NS)
        if pub_elem is not None and pub_elem.text:
            published = pub_elem.text.strip()

        categories = []
        for c in entry.findall("atom:category", NS):
            term = c.get("term")
            if term:
                categories.append(term)

        pdf_url = ""
        for link in entry.findall("atom:link", NS):
            if link.get("title") == "pdf":
                pdf_url = link.get("href") or ""
                break

        papers.append(
            Paper(
                paper_id=arxiv_id or raw_id,
                title=title,
                authors=authors,
                abstract=abstract,
                published=published,
                categories=categories,
                source="arxiv",
                url=raw_id,
                pdf_url=pdf_url,
            )
        )
    return papers


def search_by_categories(
    categories: list[str],
    days: int = 30,
    max_results: int = 200,
) -> list[Paper]:
    """Search by category plus a recent N-day date window."""
    cat_q = "+OR+".join(f"cat:{c}" for c in categories)
    end = datetime.now()
    start = end - timedelta(days=days)
    date_q = f"submittedDate:[{start.strftime('%Y%m%d')}0000+TO+{end.strftime('%Y%m%d')}2359]"
    query = f"({cat_q})+AND+{date_q}"
    url = _build_url(query, max_results, sort_by="submittedDate")
    return parse_xml(_fetch(url))


def get_by_id(arxiv_id: str) -> Paper | None:
    """Fetch metadata for a single paper by arXiv id."""
    arxiv_id = arxiv_id.strip()
    url = f"{ARXIV_API}?{urllib.parse.urlencode({'id_list': arxiv_id, 'max_results': '1'})}"
    papers = parse_xml(_fetch(url))
    return papers[0] if papers else None


def search_by_keywords(
    keywords: list[str],
    days: int | None = None,
    max_results: int = 100,
) -> list[Paper]:
    """Search title/abstract by keywords, with an optional date window."""
    parts = []
    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        if " " in kw:
            parts.append(f'(ti:"{kw}"+OR+abs:"{kw}")')
        else:
            parts.append(f"(ti:{kw}+OR+abs:{kw})")
    if not parts:
        return []
    query = "+OR+".join(parts)
    if days:
        end = datetime.now()
        start = end - timedelta(days=days)
        date_q = f"submittedDate:[{start.strftime('%Y%m%d')}0000+TO+{end.strftime('%Y%m%d')}2359]"
        query = f"({query})+AND+{date_q}"
    url = _build_url(query, max_results, sort_by="relevance")
    return parse_xml(_fetch(url))
