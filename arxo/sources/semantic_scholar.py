"""Semantic Scholar 来源适配器。

用 S2 Graph API 检索论文，带引用数（喂给打分的热度维度）。
返回统一的 Paper。匿名接口有限流，可在 config 配 api_key。
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

from ..models import Paper

S2_SEARCH_API = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_FIELDS = "title,abstract,publicationDate,year,citationCount,influentialCitationCount,url,authors,externalIds"

# 无 api_key 时的限流参数（匿名接口限流激进：约每几秒才允许一次）
NO_KEY_PRE_REQUEST_DELAY = 3.0   # 每次请求前先等待，主动节流
NO_KEY_RATE_LIMIT_WAIT = 30      # 命中 429 后的等待
KEYED_RATE_LIMIT_WAIT = 5        # 有 key 时 429 等待更短


def _request(url: str, api_key: str = "", max_retries: int = 4, timeout: int = 20) -> dict:
    headers = {"User-Agent": "arxo/0.1"}
    if api_key:
        headers["x-api-key"] = api_key
    rate_wait = KEYED_RATE_LIMIT_WAIT if api_key else NO_KEY_RATE_LIMIT_WAIT
    # 无 key 时请求前主动节流，降低触发 429 的概率
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
            # 429 限流：等更久（指数退避，封顶 rate_wait）
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
    """按查询词检索 S2，返回带引用数的 Paper 列表（按引用数降序）。"""
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
