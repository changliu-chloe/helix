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
import shutil
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
    repro_rename_pending: bool = False                        # legacy repro/ dir exists, needs move to experiments/
    repro_renamed: bool = False                               # repro/ -> experiments/ was performed this run
    results_upgraded: list[str] = field(default_factory=list)  # workspaces whose results.md -> results/index.md

    def to_dict(self) -> dict:
        return {
            "linked": self.linked,
            "pruned": self.pruned,
            "new_config_keys": self.new_config_keys,
            "deps_changed": self.deps_changed,
            "index_stale_hint": self.index_stale_hint,
            "repro_rename_pending": self.repro_rename_pending,
            "repro_renamed": self.repro_renamed,
            "results_upgraded": self.results_upgraded,
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


def _count_files(root: Path) -> int:
    """Number of regular files under a directory (for move verification)."""
    return sum(1 for p in root.rglob("*") if p.is_file())


def _migrate_repro_dir(cfg: Config, report: MigrateReport, logs: list[str], do_move: bool) -> None:
    """Move a legacy repro/ workspace root to experiments/ — only-move-never-lose, idempotent, verifiable.

    Renaming the workspace root is a storage-layout change, so per CLAUDE.md it must not lose data:
    we count files before/after and refuse to remove the source unless every file arrived.
    """
    legacy = cfg._resolve("repro")
    target = cfg.experiments_path
    # Nothing to do if there's no legacy dir, or it already *is* the target (user kept repro_dir: repro).
    if not legacy.exists() or not legacy.is_dir() or legacy.resolve() == target.resolve():
        return

    if not do_move:
        report.repro_rename_pending = True
        logs.append(f"待迁移：发现旧复现目录 {legacy}，新版用 {target.name}/。"
                    f"跑 `helix migrate --yes` 搬迁（只搬不删，先校验后核对）")
        return

    if target.exists():
        # target already exists — don't risk merging/overwriting; ask the user to resolve manually.
        logs.append(f"跳过搬迁：目标 {target} 已存在，为避免覆盖不自动合并。"
                    f"请手动核对 {legacy} 与 {target} 后自行处理")
        report.repro_rename_pending = True
        return

    before = _count_files(legacy)
    shutil.copytree(legacy, target)  # copy first (not move) so the source stays intact until verified
    after = _count_files(target)
    if after < before:
        # verification failed — leave both dirs, do NOT delete the source.
        logs.append(f"搬迁校验未通过（源 {before} 文件，目标 {after}），已保留原 {legacy} 不删。请手动核对")
        report.repro_rename_pending = True
        return
    shutil.rmtree(legacy)  # verified: every file arrived, safe to remove the old dir
    report.repro_renamed = True
    logs.append(f"已搬迁：{legacy} → {target}（{after} 文件，已核对；旧目录已清理）")


def _upgrade_results_files(cfg: Config, report: MigrateReport, logs: list[str]) -> None:
    """In each experiment workspace, migrate a legacy single-file results.md to results/index.md (idempotent)."""
    root = cfg.experiments_path
    if not root.exists():
        return
    for legacy in root.rglob("results.md"):
        ws = legacy.parent
        index = ws / "results" / "index.md"
        if index.exists():
            continue  # already upgraded
        index.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy), str(index))
        rel = str(ws.relative_to(root))
        report.results_upgraded.append(rel)
        logs.append(f"结果升级：{rel}/results.md → results/index.md")


def run_migrate(cfg: Config, scope: str = "project", *, do_move: bool = False) -> tuple[MigrateReport, list[str]]:
    """Reconcile a pulled checkout. Idempotent and non-destructive by default.

    do_move=True (helix migrate --yes) performs the repro/ -> experiments/ storage move; otherwise it's
    only reported as pending. Returns (report, log lines). The caller (cli) prints the log and a summary.
    """
    logs: list[str] = []
    report = MigrateReport()

    # 1. Re-link skills (into both .claude/skills + .agents/skills) + AGENTS.md -> CLAUDE.md,
    #    then prune stale links. Fixes "add-only" drift when skills are added/removed/renamed,
    #    and brings pre-existing checkouts up to the Codex/Cursor/Trae compat layer.
    for line in init.link_skills(scope=scope):
        logs.append(line)
        if line.startswith("已链接"):
            report.linked.append(line)
    if scope != "global":
        for line in init.link_agents_md():
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

    # 5. Storage-layout migration: legacy repro/ -> experiments/ (only with --yes), then upgrade
    #    any single-file results.md -> results/index.md. Only-move-never-lose (see helpers).
    _migrate_repro_dir(cfg, report, logs, do_move)
    _upgrade_results_files(cfg, report, logs)

    # Persist state (record current lock hash so the next migrate can detect changes).
    state["lock_hash"] = lock_hash
    _save_state(cfg, state)

    return report, logs
