"""Semantic Scholar source adapter.

Searches papers via the S2 Graph API, carrying citation counts (feeding the
popularity dimension of scoring). Returns a unified Paper. The anonymous
endpoint is rate-limited; an api_key can be set in config.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

from ..models import Paper

S2_SEARCH_API = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_FIELDS = "title,abstract,publicationDate,year,citationCount,influentialCitationCount,url,authors,externalIds"

# Rate-limit params when no api_key (the anonymous endpoint throttles aggressively: roughly one call every few seconds)
NO_KEY_PRE_REQUEST_DELAY = 3.0   # wait before each request to throttle proactively
NO_KEY_RATE_LIMIT_WAIT = 30      # wait after hitting a 429
KEYED_RATE_LIMIT_WAIT = 5        # shorter 429 wait when a key is present


def _request(url: str, api_key: str = "", max_retries: int = 4, timeout: int = 20) -> dict:
    headers = {"User-Agent": "helix/0.1"}
    if api_key:
        headers["x-api-key"] = api_key
    rate_wait = KEYED_RATE_LIMIT_WAIT if api_key else NO_KEY_RATE_LIMIT_WAIT
    # When no key, throttle before requesting to lower the chance of triggering a 429
    if not api_key and NO_KEY_PRE_REQUEST_DELAY > 0:
        time.sleep(NO_KEY_PRE_REQUEST_DELAY)
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:  # noqa: PERF203
            last_err = e
            # 429 rate limit: wait longer (exponential backoff, capped at rate_wait)
            wait = min(rate_wait, (2 ** attempt) * 5) if e.code == 429 else (2 ** attempt) * 2
            if attempt < max_retries - 1:
                time.sleep(wait)
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < max_retries - 1:
                time.sleep((2 ** attempt) * 2)
    raise RuntimeError(f"Semantic Scholar 请求失败（重试 {max_retries} 次）：{last_err}")


def _to_paper(item: dict) -> Paper | None:
    title = item.get("title")
    if not title:
        return None
    ext = item.get("externalIds") or {}
    arxiv_id = ext.get("ArXiv")
    authors = [a.get("name", "") for a in (item.get("authors") or []) if a.get("name")]
    pub = item.get("publicationDate") or (str(item["year"]) if item.get("year") else "")
    return Paper(
        paper_id=arxiv_id or item.get("paperId", ""),
        title=title.strip(),
        authors=authors,
        abstract=(item.get("abstract") or "").strip(),
        published=pub,
        categories=[],
        source="s2",
        url=item.get("url", ""),
        pdf_url="",
        citation_count=item.get("citationCount"),
    )


def search(query: str, limit: int = 50, api_key: str = "") -> list[Paper]:
    """Search S2 by query, returning a list of Paper with citation counts (descending by citation count)."""
    params = {"query": query, "limit": str(min(limit, 100)), "fields": S2_FIELDS}
    url = f"{S2_SEARCH_API}?{urllib.parse.urlencode(params)}"
    data = _request(url, api_key=api_key)
    papers: list[Paper] = []
    for item in data.get("data", []) or []:
        p = _to_paper(item)
        if p is not None:
            papers.append(p)
    papers.sort(key=lambda p: p.citation_count or 0, reverse=True)
    return papers
