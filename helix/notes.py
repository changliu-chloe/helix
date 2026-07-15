"""Markdown notes: generate skeletons, scan to build a keyword index, auto wikilink.

Consolidated from ref/evil-read-arxiv's generate_note / scan_existing_notes / link_keywords.
Design principle: the CLI only generates skeletons and manages wikilink relations; the
deep-reading body is filled in by an external agent.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from datetime import date

from . import frontmatter, naming
from .config import Config
from .models import Paper

# Common words: excluded during keyword extraction and linking (low distinctiveness)
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
# Filename / path
# --------------------------------------------------------------------------- #

def title_to_filename(title: str) -> str:
    """Convert a paper title to a short, safe filename (without extension).

    Keeps note filenames short: an author-coined name before the colon, else
    the first few words. Full title is preserved in the note frontmatter.
    """
    return naming.short_title(title)


def _note_rel(path: Path, cfg: Config) -> str:
    """Note path relative to notes_path, forward-slashed — the form embedded in wikilinks."""
    try:
        return str(Path(path).resolve().relative_to(cfg.notes_path.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def note_dir_for(paper: Paper, cfg: Config) -> Path:
    """Domain sub-directory a paper's note lives in: papers/<domain>/."""
    domain = paper.matched_domains[0] if paper.matched_domains else "未分类"
    domain_dir = naming.safe_filename(domain, "未分类")
    return cfg.papers_path / domain_dir


def note_path_for(paper: Paper, cfg: Config, name: str | None = None) -> Path:
    """Return a single note path split by domain: papers/<domain>/<short>.md.

    `name` overrides the auto-derived short name (agent-chosen after reading).
    If the short name collides with an existing note for a *different* paper
    (different arxiv_id in frontmatter), append the paper id to disambiguate —
    so short names stay the norm but two distinct papers never share a file.
    """
    stem = naming.safe_filename(name) if name else title_to_filename(paper.title)
    base = note_dir_for(paper, cfg) / f"{stem}.md"
    if base.exists() and paper.paper_id:
        try:
            existing_id = frontmatter.meta(base.read_text(encoding="utf-8", errors="replace")).get("arxiv_id")
        except OSError:
            existing_id = None
        if existing_id and str(existing_id) != str(paper.paper_id):
            safe_id = naming.safe_filename(str(paper.paper_id))
            return base.with_name(f"{base.stem}_{safe_id}.md")
    return base


# --------------------------------------------------------------------------- #
# Note skeleton generation
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
        "tags": ["helix", "paper"],
        "score": paper.score_final,
    }
    body = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f"---\n{body}---\n"


def build_note_skeleton(paper: Paper, lang: str = "zh") -> str:
    """Generate a single deep-reading note skeleton. Body sections are left empty for the agent to fill in."""
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


def write_note(paper: Paper, cfg: Config, overwrite: bool = False, name: str | None = None) -> tuple[Path, bool]:
    """Write a single note skeleton. Returns (path, whether newly created). Skips if it exists and overwrite is False.

    `name` overrides the title-derived short filename. After writing, verify the
    file was actually persisted and is non-empty, else raise OSError -- avoids
    "reporting success without writing".
    """
    path = note_path_for(paper, cfg, name=name)
    if path.exists() and not overwrite:
        return path, False
    path.parent.mkdir(parents=True, exist_ok=True)
    content = build_note_skeleton(paper, cfg.language)
    path.write_text(content, encoding="utf-8")
    # Persistence check: the file must exist and its size be consistent with what was written
    if not path.exists() or path.stat().st_size == 0:
        raise OSError(f"笔记写入失败，文件未落盘：{path}")
    return path, True


def set_review_scores(
    path: Path,
    *,
    relevance: float | None = None,
    novelty: float | None = None,
    reliability: float | None = None,
    reviewer_model: str | None = None,
    note: str | None = None,
    scored_at: str | None = None,
) -> dict:
    """Write/update a `review_scores` block in a paper note's frontmatter (idempotent).

    The three scores (0-10) come from an independent reviewer (codex MCP) after a
    deep read; see skills/deep-read. Only the deterministic write lives here -- the
    scoring judgment is the agent's. Preserves the body and all other frontmatter
    keys; re-scoring overwrites in place. Returns the review_scores dict written.
    """
    path = Path(path)
    if not path.exists():
        raise OSError(f"笔记不存在：{path}")
    content = path.read_text(encoding="utf-8", errors="replace")
    fm, body = frontmatter.split(content)
    if not fm:
        raise OSError(f"笔记缺少 frontmatter，无法写入打分：{path}")

    scores = dict(fm.get("review_scores") or {})
    if relevance is not None:
        scores["relevance"] = round(float(relevance), 1)
    if novelty is not None:
        scores["novelty"] = round(float(novelty), 1)
    if reliability is not None:
        scores["reliability"] = round(float(reliability), 1)
    if reviewer_model is not None:
        scores["model"] = reviewer_model
    if note is not None:
        scores["notes"] = note
    scores["scored_at"] = scored_at or date.today().isoformat()

    fm["review_scores"] = scores
    new_fm = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False)
    path.write_text(f"---\n{new_fm}---\n{body}", encoding="utf-8")
    return scores


def rename_note(old_path: Path, new_name: str, cfg: Config, *, overwrite: bool = False) -> tuple[Path, int]:
    """Rename a note in place and fix inbound [[wikilinks]] across the vault.

    Used after deep-reading: give a descriptive-titled paper a short name based
    on its method/innovation. `new_name` is sanitized to a short slug; the note
    stays in the same domain directory. Returns (new path, # notes whose links
    were updated). Refuses to clobber a different existing file unless overwrite.
    Assets live under assets/<id>/ keyed by arxiv id, so they are unaffected.
    """
    old_path = Path(old_path)
    if not old_path.exists():
        raise OSError(f"笔记不存在：{old_path}")
    new_stem = naming.safe_filename(new_name)
    new_path = old_path.with_name(f"{new_stem}.md")
    if new_path.resolve() == old_path.resolve():
        return new_path, 0
    if new_path.exists() and not overwrite:
        raise OSError(f"目标文件名已存在：{new_path}（换个名字或加 --overwrite）")

    old_rel = _note_rel(old_path, cfg)
    new_rel = _note_rel(new_path, cfg)
    old_path.rename(new_path)

    # Rewrite inbound wikilinks: [[papers/.../old.md|text]] embeds old_rel verbatim.
    updated = 0
    for md in iter_note_files(cfg.papers_path):
        try:
            content = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if old_rel and old_rel in content:
            new_content = content.replace(old_rel, new_rel)
            if new_content != content:
                md.write_text(new_content, encoding="utf-8")
                updated += 1
    return new_path, updated


# --------------------------------------------------------------------------- #
# Scan to build index
# --------------------------------------------------------------------------- #

def extract_title_keywords(title: str) -> list[str]:
    """Extract keywords from a title usable as wikilink anchors (acronyms, proper nouns, hyphenated terms)."""
    if not title:
        return []
    keywords: list[str] = []
    # Leading uppercase acronym: BLIP: ...
    m = re.match(r"^([A-Z]{2,})(?:\s*:|\s+)", title)
    if m:
        keywords.append(m.group(1))
    # Short title before the colon
    parts = title.split(":")
    if len(parts) >= 2 and 3 <= len(parts[0].strip()) <= 20:
        keywords.append(parts[0].strip())
    # Hyphenated technical terms: Vision-Language
    for term in re.findall(r"\b[A-Z][a-z]*(?:-[A-Z][a-z]*)+\b", title):
        t = term.strip()
        if 3 <= len(t) <= 20 and t.lower() not in COMMON_WORDS:
            keywords.append(t)
    return list(dict.fromkeys(keywords))


def iter_note_files(papers_dir: Path):
    """Iterate over real note .md files, skipping ancillary files under assets/ (fulltext.md, etc.)."""
    if not papers_dir.exists():
        return
    for md in papers_dir.rglob("*.md"):
        rel = md.relative_to(papers_dir)
        if "assets" in rel.parts:  # papers/<domain>/assets/<id>/*.md are ancillary, not notes
            continue
        yield md


def scan_notes(cfg: Config) -> dict:
    """Scan the papers directory, returning {notes:[...], keyword_to_notes:{kw:[path]}}."""
    papers_dir = cfg.papers_path
    notes: list[dict] = []
    keyword_sets: dict[str, set[str]] = {}

    def add_kw(kw: str, path: str):
        k = kw.lower()
        if 3 <= len(k) <= 30 and k not in COMMON_WORDS and not k.isdigit():
            keyword_sets.setdefault(k, set()).add(path)

    if not papers_dir.exists():
        return {"notes": [], "keyword_to_notes": {}}

    for md in iter_note_files(papers_dir):
        try:
            content = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm = frontmatter.meta(content)
        rel = str(md.relative_to(cfg.notes_path)).replace("\\", "/")
        title = fm.get("title") or md.stem
        title_kws = extract_title_keywords(title)
        notes.append({"path": rel, "filename": md.name, "title": title, "title_keywords": title_kws})
        for kw in title_kws:
            add_kw(kw, rel)

    keyword_index = {k: sorted(v) for k, v in keyword_sets.items()}
    return {"notes": notes, "keyword_to_notes": keyword_index}


# --------------------------------------------------------------------------- #
# wikilink auto-linking
# --------------------------------------------------------------------------- #

def _split_protected_lines(content: str) -> list[tuple[str, bool]]:
    """Split content into lines, marking which should be skipped (frontmatter/code block/heading/image/existing-link lines).

    Returns [(line, skip)]. Inline code is protected separately within processable lines.
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
    """Return the (start, end) spans of all [[...]] in the text."""
    return [(m.start(), m.end()) for m in re.finditer(r"\[\[.*?\]\]", text)]


def link_keywords_in_text(text: str, keyword_index: dict[str, list[str]], self_rel: str | None = None) -> str:
    """Replace keywords in a single line of text with [[path|original]].

    Skips words shared across multiple papers (too broad), matches already inside a
    wikilink, and — when self_rel is given — any keyword that only points back to the
    note being linked (a note linking to itself is meaningless; only links to *other*
    notes are useful).
    """
    candidates = {
        kw: paths
        for kw, paths in keyword_index.items()
        if kw.lower() not in COMMON_WORDS and 3 <= len(kw) <= 30 and not kw.isdigit()
        and len(paths) == 1 and paths[0] != self_rel
    }
    result = text
    matched: set[str] = set()
    # Longer keywords first, to avoid substring mismatches
    for kw in sorted(candidates, key=len, reverse=True):
        if kw in matched:
            continue
        pattern = r"(?<![a-zA-Z0-9_-])" + re.escape(kw) + r"(?![a-zA-Z0-9_-])"
        hits = list(re.finditer(pattern, result, re.IGNORECASE))
        if not hits:
            continue
        path = candidates[kw][0]
        # Precompute existing wikilink spans; replacing in reverse keeps lower offsets valid
        spans = _wikilink_spans(result)
        for m in reversed(hits):
            start, end = m.span()
            if any(s <= start and end <= e for s, e in spans):
                continue  # falls inside an existing wikilink
            result = result[:start] + f"[[{path}|{m.group(0)}]]" + result[end:]
        matched.add(kw)
    return result


# Spans that must never be touched by keyword linking: inline code, markdown
# links/images [text](url), autolinks <url>, and bare http(s) URLs. A keyword
# that happens to appear inside a URL (e.g. github.com/.../ThunderAgent) is part
# of the link, not prose — wrapping it in [[...]] corrupts the link.
_PROTECT_RE = re.compile(
    r"`[^`]+`"                       # inline code
    r"|!?\[[^\]]*\]\([^)]*\)"        # markdown link / image
    r"|<https?://[^>]+>"             # autolink
    r"|https?://\S+",                # bare URL
)


def link_file(path: Path, keyword_index: dict[str, list[str]], cfg: Config | None = None) -> int:
    """Apply wikilink linking to a file's body, writing back in place. Returns the number of links added.

    When cfg is given, the note's own path is computed and passed as self_rel so the
    note never links to itself. URLs and markdown links are protected from matching.
    """
    content = path.read_text(encoding="utf-8")
    self_rel = _note_rel(path, cfg) if cfg is not None else None
    before = len(re.findall(r"\[\[.*?\]\]", content))
    out_lines = []
    for line, skip in _split_protected_lines(content):
        if skip:
            out_lines.append(line)
            continue
        # Protect inline code, URLs and markdown links from keyword matching
        protected: list[str] = []
        def stash(m):
            protected.append(m.group(0))
            return f"\x00{len(protected)-1}\x00"
        stashed = _PROTECT_RE.sub(stash, line)
        linked = link_keywords_in_text(stashed, keyword_index, self_rel=self_rel)
        for i, c in enumerate(protected):
            linked = linked.replace(f"\x00{i}\x00", c)
        out_lines.append(linked)
    result = "\n".join(out_lines)
    path.write_text(result, encoding="utf-8")
    after = len(re.findall(r"\[\[.*?\]\]", result))
    return after - before
