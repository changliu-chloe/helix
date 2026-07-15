"""Read and parse config.yaml."""

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
class HardwareProfile:
    """Hardware profile of one machine/class for reproduction. The repro plan uses this to judge whether a model fits."""

    name: str                       # profile name, e.g. a100-40g / h20-96g
    gpu_model: str = ""             # GPU model, e.g. A100-40GB / H20
    vram_gb: float = 0.0            # per-GPU VRAM (GB)
    num_gpus: int = 1               # number of GPUs
    interconnect: str = ""          # interconnect, e.g. NVLink / PCIe (affects TP feasibility)
    notes: str = ""                 # notes

    @property
    def total_vram_gb(self) -> float:
        return self.vram_gb * max(1, self.num_gpus)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "gpu_model": self.gpu_model,
            "vram_gb": self.vram_gb,
            "num_gpus": self.num_gpus,
            "interconnect": self.interconnect,
            "notes": self.notes,
            "total_vram_gb": self.total_vram_gb,
        }


@dataclass
class Config:
    language: str = "zh"
    notes_dir: str = "notes"
    papers_subdir: str = "papers"
    daily_subdir: str = "daily"
    review_subdir: str = "reviews"
    repro_dir: str = "repro"
    reviewer_model: str = "gpt-5.6-sol"
    review_funnel_top_n: int = 10
    semantic_scholar_api_key: str = ""
    mineru_api_key: str = ""
    score_weights: dict[str, float] = field(default_factory=dict)
    excluded_keywords: list[str] = field(default_factory=list)
    domains: list[Domain] = field(default_factory=list)
    hardware_profiles: list[HardwareProfile] = field(default_factory=list)
    _path: Path | None = None

    @property
    def mineru_key(self) -> str:
        """MinerU key: config takes precedence, then the MINERU_API_KEY env var."""
        return self.mineru_api_key or os.environ.get("MINERU_API_KEY", "")

    def assets_path(self, domain: str, arxiv_id: str) -> Path:
        """Asset directory for a single paper: notes/papers/<domain>/assets/<id>/."""
        import re as _re

        safe_domain = _re.sub(r'[ /\\:*?"<>|]+', "_", domain or "未分类").strip("_") or "未分类"
        safe_id = arxiv_id.replace("/", "_")
        return self.papers_path / safe_domain / "assets" / safe_id

    @property
    def base_dir(self) -> Path:
        """Anchor for all relative paths = the directory containing config.yaml (project root)."""
        return self._path.resolve().parent if self._path else Path.cwd()

    def _resolve(self, p: str) -> Path:
        """Resolve a config path to absolute: absolute paths as-is, relative paths anchored to base_dir."""
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
    def review_path(self) -> Path:
        """Literature-review notes directory, under notes_path."""
        return self.notes_path / self.review_subdir

    @property
    def repro_path(self) -> Path:
        """Reproduction workspace root, a sibling of notes_path, anchored to base_dir."""
        return self._resolve(self.repro_dir)

    def repro_workspace_path(self, domain: str, short_name: str, draft: bool = False) -> Path:
        """Reproduction workspace for a single paper: repro/<domain>/<short_name>/ (goes to draft_notes/ when --draft)."""
        import re as _re

        def _safe(s: str, fallback: str) -> str:
            return _re.sub(r'[ /\\:*?"<>|]+', "_", s or fallback).strip("_") or fallback

        root = self._resolve("draft_notes") if draft else self.repro_path
        return root / _safe(domain, "未分类") / _safe(short_name, "untitled")

    def find_profile(self, name: str) -> HardwareProfile | None:
        for p in self.hardware_profiles:
            if p.name == name:
                return p
        return None

    @property
    def index_path(self) -> Path:
        """FTS5 index location, at .helix/index.db under base_dir."""
        return self.base_dir / ".helix" / "index.db"

    def all_categories(self) -> list[str]:
        """Deduplicated arXiv categories across all domains."""
        seen: list[str] = []
        for d in self.domains:
            for c in d.arxiv_categories:
                if c not in seen:
                    seen.append(c)
        return seen


def find_config(explicit: str | None = None) -> Path:
    """Locate config.yaml: explicit path > HELIX_CONFIG env var > search upward from cwd."""
    if explicit:
        return Path(explicit)
    env = os.environ.get("HELIX_CONFIG")
    if env:
        return Path(env)
    # Search upward from cwd for config.yaml (like git finding .git), so it works from subdirs
    cur = Path.cwd()
    for d in [cur, *cur.parents]:
        candidate = d / DEFAULT_CONFIG_NAME
        if candidate.exists():
            return candidate
    return cur / DEFAULT_CONFIG_NAME  # not found anywhere; fall back to cwd (a friendly error follows)


def load_config(path: str | None = None) -> Config:
    cfg_path = find_config(path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"找不到配置文件：{cfg_path}（可用 --config 指定或设 HELIX_CONFIG）")

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

    profiles = []
    for name, spec in (raw.get("hardware_profiles") or {}).items():
        spec = spec or {}
        profiles.append(
            HardwareProfile(
                name=name,
                gpu_model=str(spec.get("gpu_model", "") or ""),
                vram_gb=float(spec.get("vram_gb", 0) or 0),
                num_gpus=int(spec.get("num_gpus", 1) or 1),
                interconnect=str(spec.get("interconnect", "") or ""),
                notes=str(spec.get("notes", "") or ""),
            )
        )

    return Config(
        language=raw.get("language", "zh"),
        notes_dir=raw.get("notes_dir", "notes"),
        papers_subdir=raw.get("papers_subdir", "papers"),
        daily_subdir=raw.get("daily_subdir", "daily"),
        review_subdir=raw.get("review_subdir", "reviews"),
        repro_dir=raw.get("repro_dir", "repro"),
        reviewer_model=raw.get("reviewer_model", "gpt-5.6-sol") or "gpt-5.6-sol",
        review_funnel_top_n=int(raw.get("review_funnel_top_n", 10) or 10),
        semantic_scholar_api_key=raw.get("semantic_scholar_api_key", "") or "",
        mineru_api_key=raw.get("mineru_api_key", "") or "",
        score_weights=dict(raw.get("score_weights") or {}),
        excluded_keywords=list(raw.get("excluded_keywords") or []),
        domains=domains,
        hardware_profiles=profiles,
        _path=cfg_path,
    )
