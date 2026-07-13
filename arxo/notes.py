"""Markdown 笔记：生成骨架、扫描建关键词索引、wikilink 自动链接。

整合自 ref/evil-read-arxiv 的 generate_note / scan_existing_notes / link_keywords。
设计原则：CLI 只生成骨架和管理 wikilink 关系，深读正文由外部 agent 填充。
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .config import Config
from .models import Paper

# 通用词：自动提词与链接时排除（区分度低）
COMMON_WORDS = {
    "and", "the", "for", "of", "in", "on", "at", "by", "with", "from",
    "to", "as", "or", "but", "not", "a", "an", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "will", "would", "should", "could", "may", "might", "must",
    "can", "need", "use", "using", "via", "through", "over",
    "under", "between", "among", "during", "without", "within",
    "this", "that", "these", "those", "it", "its", "they", "their",
    "we", "you", "your", "our", "my", "his", "her",
    "model", "learning", "training", "data", "system", "method",
    "approach", "framework", "network", "algorithm", "task",
}


# --------------------------------------------------------------------------- #
# 文件名 / 路径
# --------------------------------------------------------------------------- #

def title_to_filename(title: str) -> str:
    """论文标题转安全文件名（不含扩展名）。"""
    name = re.sub(r'[ /\\:*?"<>|]+', "_", title).strip("_")
    return name or "untitled"


def note_path_for(paper: Paper, cfg: Config) -> Path:
    """按领域分目录返回单篇笔记路径：papers/<领域>/<标题>.md。"""
    domain = paper.matched_domains[0] if paper.matched_domains else "未分类"
    domain_dir = re.sub(r'[ /\\:*?"<>|]+', "_", domain).strip("_") or "未分类"
    return cfg.papers_path / domain_dir / f"{title_to_filename(paper.title)}.md"


# --------------------------------------------------------------------------- #
# 笔记骨架生成
# --------------------------------------------------------------------------- #

def _frontmatter(paper: Paper) -> str:
    fm = {
        "title": paper.title,
        "arxiv_id": paper.paper_id,
        "authors": paper.authors,
        "published": paper.published,
        "categories": paper.categories,
        "url": paper.url,
        "pdf_url": paper.pdf_url,
        "domains": paper.matched_domains,
        "tags": ["arxo", "paper"],
        "score": paper.score_final,
    }
    body = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f"---\n{body}---\n"


def build_note_skeleton(paper: Paper, lang: str = "zh") -> str:
    """生成单篇深读笔记骨架。正文小节留空，供 agent 填写。"""
    fm = _frontmatter(paper)
    authors = ", ".join(paper.authors) if paper.authors else "--"
    links = f"[arXiv]({paper.url}) | [PDF]({paper.pdf_url})"
    if lang == "en":
        return f"""{fm}
# {paper.title}

- **Authors**: {authors}
- **Links**: {links}
- **Source**: {paper.source}

## Abstract

{paper.abstract}

## One-line Summary

<!-- agent: fill in -->

## Core Contributions

<!-- agent: fill in -->

## Method

<!-- agent: fill in -->

## Key Results

<!-- agent: fill in -->

## Critical Analysis

<!-- agent: fill in -->

## Related Work

<!-- agent: link related notes with [[wikilink]] -->
"""
    return f"""{fm}
# {paper.title}

- **作者**：{authors}
- **链接**：{links}
- **来源**：{paper.source}

## 摘要

{paper.abstract}

## 一句话总结

<!-- agent: 待填写 -->

## 核心贡献

<!-- agent: 待填写 -->

## 方法

<!-- agent: 待填写 -->

## 关键结果

<!-- agent: 待填写 -->

## 批判性分析

<!-- agent: 待填写 -->

## 相关工作

<!-- agent: 用 [[wikilink]] 链接相关笔记 -->
"""


def write_note(paper: Paper, cfg: Config, overwrite: bool = False) -> tuple[Path, bool]:
    """写入单篇笔记骨架。返回 (路径, 是否新建)。已存在且未 overwrite 则跳过。

    写入后校验文件确实落盘且非空，否则抛 OSError——杜绝"报告成功却没写入"。
    """
    path = note_path_for(paper, cfg)
    if path.exists() and not overwrite:
        return path, False
    path.parent.mkdir(parents=True, exist_ok=True)
    content = build_note_skeleton(paper, cfg.language)
    path.write_text(content, encoding="utf-8")
    # 落盘校验：文件必须存在且大小与写入内容一致
    if not path.exists() or path.stat().st_size == 0:
        raise OSError(f"笔记写入失败，文件未落盘：{path}")
    return path, True


# --------------------------------------------------------------------------- #
# 扫描建索引
# --------------------------------------------------------------------------- #

def _parse_frontmatter(content: str) -> dict:
    m = re.match(r"^---\s*\n(.*?)^---\s*\n", content, re.MULTILINE | re.DOTALL)
    if not m:
        return {}
    try:
        return yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}


def extract_title_keywords(title: str) -> list[str]:
    """从标题提取可作为 wikilink 锚点的关键词（缩写、专有名词、连字符术语）。"""
    if not title:
        return []
    keywords: list[str] = []
    # 开头大写缩写：BLIP: ...
    m = re.match(r"^([A-Z]{2,})(?:\s*:|\s+)", title)
    if m:
        keywords.append(m.group(1))
    # 冒号前短标题
    parts = title.split(":")
    if len(parts) >= 2 and 3 <= len(parts[0].strip()) <= 20:
        keywords.append(parts[0].strip())
    # 连字符技术术语：Vision-Language
    for term in re.findall(r"\b[A-Z][a-z]*(?:-[A-Z][a-z]*)+\b", title):
        t = term.strip()
        if 3 <= len(t) <= 20 and t.lower() not in COMMON_WORDS:
            keywords.append(t)
    return list(dict.fromkeys(keywords))


def scan_notes(cfg: Config) -> dict:
    """扫描 papers 目录，返回 {notes:[...], keyword_to_notes:{kw:[path]}}。"""
    papers_dir = cfg.papers_path
    notes: list[dict] = []
    keyword_sets: dict[str, set[str]] = {}

    def add_kw(kw: str, path: str):
        k = kw.lower()
        if 3 <= len(k) <= 30 and k not in COMMON_WORDS and not k.isdigit():
            keyword_sets.setdefault(k, set()).add(path)

    if not papers_dir.exists():
        return {"notes": [], "keyword_to_notes": {}}

    for md in papers_dir.rglob("*.md"):
        try:
            content = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm = _parse_frontmatter(content)
        rel = str(md.relative_to(cfg.notes_path)).replace("\\", "/")
        title = fm.get("title") or md.stem
        title_kws = extract_title_keywords(title)
        notes.append({"path": rel, "filename": md.name, "title": title, "title_keywords": title_kws})
        for kw in title_kws:
            add_kw(kw, rel)

    keyword_index = {k: sorted(v) for k, v in keyword_sets.items()}
    return {"notes": notes, "keyword_to_notes": keyword_index}


# --------------------------------------------------------------------------- #
# wikilink 自动链接
# --------------------------------------------------------------------------- #

def _split_protected_lines(content: str) -> list[tuple[str, bool]]:
    """把内容按行拆分，标记哪些行应跳过（frontmatter/代码块/标题/图片/已有链接行）。

    返回 [(line, skip)]。行内代码在可处理行内单独保护。
    """
    out: list[tuple[str, bool]] = []
    in_code = False
    fm_count = 0
    in_fm = False
    for line in content.split("\n"):
        if line.strip() == "---":
            fm_count += 1
            in_fm = fm_count == 1
            out.append((line, True))
            continue
        if in_fm:
            out.append((line, True))
            continue
        if line.strip().startswith("```"):
            in_code = not in_code
            out.append((line, True))
            continue
        if in_code:
            out.append((line, True))
            continue
        if line.strip().startswith("#"):
            out.append((line, True))
            continue
        out.append((line, False))
    return out


def _wikilink_spans(text: str) -> list[tuple[int, int]]:
    """返回文本中所有 [[...]] 的 (start, end) 区间。"""
    return [(m.start(), m.end()) for m in re.finditer(r"\[\[.*?\]\]", text)]


def link_keywords_in_text(text: str, keyword_index: dict[str, list[str]]) -> str:
    """在单行文本中把关键词替换为 [[path|原文]]。跳过多论文共享词和已在 wikilink 内的匹配。"""
    candidates = {
        kw: paths
        for kw, paths in keyword_index.items()
        if kw.lower() not in COMMON_WORDS and 3 <= len(kw) <= 30 and not kw.isdigit() and len(paths) == 1
    }
    result = text
    matched: set[str] = set()
    # 长关键词优先，避免子串误匹配
    for kw in sorted(candidates, key=len, reverse=True):
        if kw in matched:
            continue
        pattern = r"(?<![a-zA-Z0-9_-])" + re.escape(kw) + r"(?![a-zA-Z0-9_-])"
        hits = list(re.finditer(pattern, result, re.IGNORECASE))
        if not hits:
            continue
        path = candidates[kw][0]
        # 预计算当前已有的 wikilink 区间；反向替换保证低位偏移不失效
        spans = _wikilink_spans(result)
        for m in reversed(hits):
            start, end = m.span()
            if any(s <= start and end <= e for s, e in spans):
                continue  # 落在已有 wikilink 内
            result = result[:start] + f"[[{path}|{m.group(0)}]]" + result[end:]
        matched.add(kw)
    return result


def link_file(path: Path, keyword_index: dict[str, list[str]]) -> int:
    """对文件正文做 wikilink 链接，原地写回。返回新增链接数。"""
    content = path.read_text(encoding="utf-8")
    before = len(re.findall(r"\[\[.*?\]\]", content))
    out_lines = []
    for line, skip in _split_protected_lines(content):
        if skip:
            out_lines.append(line)
            continue
        # 保护行内代码
        codes: list[str] = []
        def stash(m):
            codes.append(m.group(0))
            return f"\x00{len(codes)-1}\x00"
        stashed = re.sub(r"`[^`]+`", stash, line)
        linked = link_keywords_in_text(stashed, keyword_index)
        for i, c in enumerate(codes):
            linked = linked.replace(f"\x00{i}\x00", c)
        out_lines.append(linked)
    result = "\n".join(out_lines)
    path.write_text(result, encoding="utf-8")
    after = len(re.findall(r"\[\[.*?\]\]", result))
    return after - before
