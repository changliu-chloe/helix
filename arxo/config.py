"""读取并解析 config.yaml。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_NAME = "config.yaml"


@dataclass
class Domain:
    name: str
    keywords: list[str] = field(default_factory=list)
    arxiv_categories: list[str] = field(default_factory=list)
    priority: int = 1


@dataclass
class Config:
    language: str = "zh"
    notes_dir: str = "notes"
    papers_subdir: str = "papers"
    daily_subdir: str = "daily"
    semantic_scholar_api_key: str = ""
    score_weights: dict[str, float] = field(default_factory=dict)
    excluded_keywords: list[str] = field(default_factory=list)
    domains: list[Domain] = field(default_factory=list)
    _path: Path | None = None

    @property
    def notes_path(self) -> Path:
        return Path(self.notes_dir)

    @property
    def papers_path(self) -> Path:
        return self.notes_path / self.papers_subdir

    @property
    def daily_path(self) -> Path:
        return self.notes_path / self.daily_subdir

    def all_categories(self) -> list[str]:
        """所有领域的 arXiv 分类去重。"""
        seen: list[str] = []
        for d in self.domains:
            for c in d.arxiv_categories:
                if c not in seen:
                    seen.append(c)
        return seen


def find_config(explicit: str | None = None) -> Path:
    """定位 config.yaml：显式路径 > 环境变量 ARXO_CONFIG > 当前目录。"""
    if explicit:
        return Path(explicit)
    env = os.environ.get("ARXO_CONFIG")
    if env:
        return Path(env)
    return Path.cwd() / DEFAULT_CONFIG_NAME


def load_config(path: str | None = None) -> Config:
    cfg_path = find_config(path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"找不到配置文件：{cfg_path}（可用 --config 指定或设 ARXO_CONFIG）")

    with cfg_path.open("r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    domains = []
    for name, spec in (raw.get("research_domains") or {}).items():
        spec = spec or {}
        domains.append(
            Domain(
                name=name,
                keywords=list(spec.get("keywords") or []),
                arxiv_categories=list(spec.get("arxiv_categories") or []),
                priority=int(spec.get("priority", 1)),
            )
        )

    return Config(
        language=raw.get("language", "zh"),
        notes_dir=raw.get("notes_dir", "notes"),
        papers_subdir=raw.get("papers_subdir", "papers"),
        daily_subdir=raw.get("daily_subdir", "daily"),
        semantic_scholar_api_key=raw.get("semantic_scholar_api_key", "") or "",
        score_weights=dict(raw.get("score_weights") or {}),
        excluded_keywords=list(raw.get("excluded_keywords") or []),
        domains=domains,
        _path=cfg_path,
    )
