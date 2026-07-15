"""Literature review notes: generate survey skeletons for an agent to fill in.

A review note synthesizes several deep-read papers around a topic. Two paths feed
it (see skills/review): (1) papers already in the vault, (2) a fresh direction
search funneled down to a few papers that then get deep-read. Either way the CLI
only lays down a deterministic skeleton; the agent fills the synthesis and pulls
per-paper scores (relevance / novelty / reliability) that deep-read wrote into
each paper note's frontmatter.

Design mirrors notes.py / repro.py: skeleton-only, path anchored to base_dir,
persistence self-check on write.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from . import naming
from .config import Config


def review_path_for(topic: str, cfg: Config, name: str | None = None) -> Path:
    """Return a review note path: reviews/<short>.md (flat — a review is itself a topic).

    `name` overrides the topic-derived short name (agent-chosen). The short name
    is filesystem-safe; the full topic is preserved in the note frontmatter.
    """
    stem = naming.safe_filename(name) if name else naming.short_title(topic)
    return cfg.review_path / f"{stem}.md"


def _frontmatter(topic: str) -> str:
    fm = {
        "title": topic,
        "type": "review",
        "tags": ["helix", "review"],
        "papers": [],  # agent fills note-relative paths of surveyed papers
    }
    body = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f"---\n{body}---\n"


def build_review_skeleton(topic: str, lang: str = "zh") -> str:
    """Generate a literature-review skeleton. Body sections are left for the agent to fill.

    The per-paper table columns match the three codex scores deep-read writes into
    each paper note's frontmatter (review_scores), so the agent copies them in.
    """
    fm = _frontmatter(topic)
    if lang == "en":
        return f"""{fm}
# Literature Review: {topic}

## Scope & Questions

<!-- agent: what this review covers, the guiding questions, inclusion criteria -->

## Landscape (by method / thread)

<!-- agent: group the surveyed papers into methodological threads; narrate the lineage -->

## Papers at a Glance

<!-- agent: one row per surveyed paper. Scores from each paper note's review_scores frontmatter (0-10). Link the paper title with [[wikilink]]. -->

| Paper | Relevance | Novelty | Reliability | One-line takeaway |
|---|---|---|---|---|
<!-- agent: fill rows; use — when a paper has no review_scores yet -->

## Synthesis

<!-- agent: cross-paper trends, agreements/contradictions, gaps, open opportunities -->

## Related Literature (further reading)

<!-- agent: papers found by a closing search but not deep-read; brief note each -->

## References

<!-- agent: link every surveyed note with [[wikilink]] -->
"""
    return f"""{fm}
# 文献综述：{topic}

## 综述范围与问题

<!-- agent: 本综述覆盖什么、核心问题、纳入标准 -->

## 方法脉络（按技术路线分类）

<!-- agent: 把入选论文按方法/路线归类，讲清演进脉络 -->

## 逐篇要点

<!-- agent: 每篇一行。分数取自各论文笔记 frontmatter 的 review_scores（0-10）。论文标题用 [[wikilink]]。 -->

| 论文 | 相关性 | 创新性 | 可靠性 | 一句话要点 |
|---|---|---|---|---|
<!-- agent: 逐行填写；某篇还没打分则填 — -->

## 综合分析

<!-- agent: 跨论文趋势、共识/分歧、研究空白、可切入的机会 -->

## 相关文献补充（延伸阅读）

<!-- agent: 收尾检索到、但未精读的相关文献，每篇一句话 -->

## 参考

<!-- agent: 用 [[wikilink]] 链接所有入选笔记 -->
"""


def write_review(topic: str, cfg: Config, overwrite: bool = False, name: str | None = None) -> tuple[Path, bool]:
    """Write a review skeleton. Returns (path, whether newly created). Skips if it exists and not overwrite.

    After writing, verify the file was persisted and non-empty, else raise OSError
    -- avoids "reporting success without writing" (mirrors notes.write_note).
    """
    path = review_path_for(topic, cfg, name=name)
    if path.exists() and not overwrite:
        return path, False
    path.parent.mkdir(parents=True, exist_ok=True)
    content = build_review_skeleton(topic, cfg.language)
    path.write_text(content, encoding="utf-8")
    if not path.exists() or path.stat().st_size == 0:
        raise OSError(f"综述笔记写入失败，文件未落盘：{path}")
    return path, True
