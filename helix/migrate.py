"""helix migrate: bring an in-use checkout up to date after `git pull`.

`git pull` only updates working-tree files; it re-runs no wiring. So newly pulled
skills aren't symlinked into .claude, new dependencies aren't installed, and new
config fields go unnoticed. `migrate` is the idempotent, run-anytime step that
reconciles these. Design: cheap and safe by default — it re-links skills and
prunes stale links, but only *reports* config/dependency drift rather than
mutating your config.yaml or venv (those are your call).

Deliberately out of scope for now (add when a real schema change first occurs):
FTS index schema versioning with auto-rebuild, and storage-layout data migration.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import init
from .config import Config

# Top-level config keys are compared example-vs-user to surface newly added ones.
PROJECT_ROOT = init.PROJECT_ROOT
EXAMPLE_CONFIG = PROJECT_ROOT / "config.example.yaml"
LOCK_FILE = PROJECT_ROOT / "uv.lock"


def _state_path(cfg: Config) -> Path:
    """Migration state lives next to the index, under .helix/ (git-ignored, per-checkout)."""
    return cfg.base_dir / ".helix" / "state.json"


def _load_state(cfg: Config) -> dict:
    p = _state_path(cfg)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(cfg: Config, state: dict) -> None:
    p = _state_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _file_hash(path: Path) -> str | None:
    """SHA-256 of a file, or None if it doesn't exist."""
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _example_top_keys() -> list[str]:
    """Top-level keys present in config.example.yaml (the template of known fields)."""
    if not EXAMPLE_CONFIG.exists():
        return []
    try:
        data = yaml.safe_load(EXAMPLE_CONFIG.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    return list(data.keys()) if isinstance(data, dict) else []


def _user_top_keys(cfg: Config) -> list[str]:
    """Top-level keys present in the user's actual config.yaml."""
    if not cfg._path or not cfg._path.exists():
        return []
    try:
        data = yaml.safe_load(cfg._path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    return list(data.keys()) if isinstance(data, dict) else []


@dataclass
class MigrateReport:
    """What migrate did and what the user still needs to do by hand."""

    linked: list[str] = field(default_factory=list)          # newly created skill symlinks
    pruned: list[str] = field(default_factory=list)          # stale skill symlinks removed
    new_config_keys: list[str] = field(default_factory=list)  # example has, user config lacks
    deps_changed: bool = False                                # uv.lock changed since last migrate
    index_stale_hint: bool = False                            # notes newer than index

    def to_dict(self) -> dict:
        return {
            "linked": self.linked,
            "pruned": self.pruned,
            "new_config_keys": self.new_config_keys,
            "deps_changed": self.deps_changed,
            "index_stale_hint": self.index_stale_hint,
        }


def _index_looks_stale(cfg: Config) -> bool:
    """Heuristic: any note file is newer than the FTS index db (or the index is missing but notes exist)."""
    idx = cfg.index_path
    papers = cfg.papers_path
    if not papers.exists():
        return False
    try:
        from .notes import iter_note_files

        notes = list(iter_note_files(papers))
    except Exception:  # noqa: BLE001 — best-effort hint only
        return False
    if not notes:
        return False
    if not idx.exists():
        return True
    idx_mtime = idx.stat().st_mtime
    return any(n.stat().st_mtime > idx_mtime for n in notes)


def run_migrate(cfg: Config, scope: str = "project") -> tuple[MigrateReport, list[str]]:
    """Reconcile a pulled checkout. Idempotent and non-destructive by default.

    Returns (report, log lines). The caller (cli) prints the log and a summary.
    """
    logs: list[str] = []
    report = MigrateReport()

    # 1. Re-link skills + prune stale links (fixes "add-only" drift when skills are added/removed/renamed).
    for line in init.link_skills(scope=scope):
        logs.append(line)
        if line.startswith("已链接"):
            report.linked.append(line)
    for line in init.prune_stale_skill_links(scope=scope):
        logs.append(line)
        report.pruned.append(line)

    # 2. Config drift — report only, never mutate the user's config.yaml.
    example_keys = _example_top_keys()
    user_keys = set(_user_top_keys(cfg))
    report.new_config_keys = [k for k in example_keys if k not in user_keys]

    # 3. Dependency drift — compare uv.lock hash against last-recorded; hint, don't install.
    state = _load_state(cfg)
    lock_hash = _file_hash(LOCK_FILE)
    if lock_hash is not None and state.get("lock_hash") != lock_hash:
        # first run has no prior hash; only flag as "changed" if we had recorded one before
        report.deps_changed = "lock_hash" in state

    # 4. Index staleness — hint only.
    report.index_stale_hint = _index_looks_stale(cfg)

    # Persist state (record current lock hash so the next migrate can detect changes).
    state["lock_hash"] = lock_hash
    _save_state(cfg, state)

    return report, logs
