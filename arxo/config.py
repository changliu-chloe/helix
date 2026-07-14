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
class HardwareProfile:
    """一台/一类可复现机器的硬件档。复现方案据此判断模型装不装得下。"""

    name: str                       # 档名，如 a100-40g / h20-96g
    gpu_model: str = ""             # GPU 型号，如 A100-40GB / H20
    vram_gb: float = 0.0            # 单卡显存（GB）
    num_gpus: int = 1               # 卡数
    interconnect: str = ""          # 互联，如 NVLink / PCIe（影响 TP 可行性）
    notes: str = ""                 # 备注

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
    repro_dir: str = "repro"
    semantic_scholar_api_key: str = ""
    mineru_api_key: str = ""
    score_weights: dict[str, float] = field(default_factory=dict)
    excluded_keywords: list[str] = field(default_factory=list)
    domains: list[Domain] = field(default_factory=list)
    hardware_profiles: list[HardwareProfile] = field(default_factory=list)
    _path: Path | None = None

    @property
    def mineru_key(self) -> str:
        """MinerU key：config 优先，其次环境变量 MINERU_API_KEY。"""
        return self.mineru_api_key or os.environ.get("MINERU_API_KEY", "")

    def assets_path(self, domain: str, arxiv_id: str) -> Path:
        """单篇论文的资产目录：notes/papers/<领域>/assets/<id>/。"""
        import re as _re

        safe_domain = _re.sub(r'[ /\\:*?"<>|]+', "_", domain or "未分类").strip("_") or "未分类"
        safe_id = arxiv_id.replace("/", "_")
        return self.papers_path / safe_domain / "assets" / safe_id

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
    def repro_path(self) -> Path:
        """复现工作区根目录，与 notes_path 平级，锚定 base_dir。"""
        return self._resolve(self.repro_dir)

    def repro_workspace_path(self, domain: str, short_name: str, draft: bool = False) -> Path:
        """单篇论文的复现工作区：repro/<方向>/<短名>/（--draft 时落 draft_notes/）。"""
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
        repro_dir=raw.get("repro_dir", "repro"),
        semantic_scholar_api_key=raw.get("semantic_scholar_api_key", "") or "",
        mineru_api_key=raw.get("mineru_api_key", "") or "",
        score_weights=dict(raw.get("score_weights") or {}),
        excluded_keywords=list(raw.get("excluded_keywords") or []),
        domains=domains,
        hardware_profiles=profiles,
        _path=cfg_path,
    )
