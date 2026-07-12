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
    def base_dir(self) -> Path:
        """所有相对路径的锚点 = config.yaml 所在目录（项目根）。"""
        return self._path.resolve().parent if self._path else Path.cwd()

    def _resolve(self, p: str) -> Path:
        """把配置里的路径解析为绝对路径：绝对路径原样，相对路径锚定 base_dir。"""
        path = Path(p).expanduser()
        return path if path.is_absolute() else self.base_dir / path

    @property
    def notes_path(self) -> Path:
        return self._resolve(self.notes_dir)

    @property
    def papers_path(self) -> Path:
        return self.notes_path / self.papers_subdir

    @property
    def daily_path(self) -> Path:
        return self.notes_path / self.daily_subdir

    @property
    def index_path(self) -> Path:
        """FTS5 索引位置，锚定 base_dir 下的 .arxo/index.db。"""
        return self.base_dir / ".arxo" / "index.db"

    def all_categories(self) -> list[str]:
        """所有领域的 arXiv 分类去重。"""
        seen: list[str] = []
        for d in self.domains:
            for c in d.arxiv_categories:
                if c not in seen:
                    seen.append(c)
        return seen


def find_config(explicit: str | None = None) -> Path:
    """定位 config.yaml：显式路径 > 环境变量 ARXO_CONFIG > 从 cwd 向上逐级查找。"""
    if explicit:
        return Path(explicit)
    env = os.environ.get("ARXO_CONFIG")
    if env:
        return Path(env)
    # 从当前目录向上找 config.yaml（像 git 找 .git），支持在子目录运行
    cur = Path.cwd()
    for d in [cur, *cur.parents]:
        candidate = d / DEFAULT_CONFIG_NAME
        if candidate.exists():
            return candidate
    return cur / DEFAULT_CONFIG_NAME  # 都没找到，回退当前目录（后续报错友好提示）


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
