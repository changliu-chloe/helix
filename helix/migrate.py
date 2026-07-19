"""helix migrate: bring an in-use checkout up to date after `git pull`.

`git pull` only updates working-tree files; it re-runs no wiring. So newly pulled
skills aren't symlinked into .claude, new dependencies aren't installed, and new
config fields go unnoticed. `migrate` is the idempotent, run-anytime step that
reconciles these. Design: it re-links skills and prunes stale links; for config
drift it *appends* any missing fields into config.yaml by copying their template
blocks (comments + name + empty placeholder) verbatim from config.example.yaml,
after backing up config.yaml -> config.yaml.bak. Append-only: existing lines,
comments, and layout are never rewritten, and only fields the user actually lacks
are added (idempotent). Dependency drift is still only reported (that's your call).

Deliberately out of scope for now (add when a real schema change first occurs):
FTS index schema versioning with auto-rebuild.
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
    """Migration state lives next to the index, under workspace/.helix/ (git-ignored, per-checkout)."""
    return cfg.index_path.parent / "state.json"


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


def _extract_field_block(example_text: str, key: str) -> str:
    """Extract a top-level `key:` block from config.example.yaml text, preserving comments + placeholder.

    Text-based (not YAML) on purpose -- yaml.safe_load discards comments, and the whole point is to copy
    the template's field name + explanatory comments + empty placeholder verbatim. Grabs the contiguous
    comment lines directly above `key:` plus the key's own value (including indented nested lines), up to
    the next top-level key / comment-block / EOF. Returns "" if the key isn't found.
    """
    lines = example_text.splitlines()
    # locate the top-level `key:` line (column 0, not indented, not a comment)
    key_idx = None
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if line[:1] not in (" ", "\t", "#") and ":" in line and stripped.split(":", 1)[0].strip() == key:
            key_idx = i
            break
    if key_idx is None:
        return ""

    # walk up over the contiguous comment lines immediately above (stop at a blank line or non-comment)
    start = key_idx
    j = key_idx - 1
    while j >= 0 and lines[j].lstrip().startswith("#"):
        start = j
        j -= 1

    # walk down: the key line, then any indented / blank-within-block lines until the next top-level token
    end = key_idx + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() == "":
            # a blank line may separate nested content; peek: if next non-blank is indented, keep going
            k = end + 1
            while k < len(lines) and lines[k].strip() == "":
                k += 1
            if k < len(lines) and lines[k][:1] in (" ", "\t"):
                end = k + 1
                continue
            break
        if line[:1] in (" ", "\t"):   # indented -> part of this key's nested value
            end = end + 1
            continue
        break                          # hit the next top-level key / comment block
    return "\n".join(lines[start:end]).rstrip("\n")


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
    new_config_keys: list[str] = field(default_factory=list)  # example has, user config lacks (detected)
    config_fields_written: list[str] = field(default_factory=list)  # fields appended into config.yaml this run
    config_backed_up: bool = False                            # config.yaml.bak written before appending
    deps_changed: bool = False                                # uv.lock changed since last migrate
    index_stale_hint: bool = False                            # notes newer than index
    repro_rename_pending: bool = False                        # legacy repro/ dir exists, needs move to experiments/
    repro_renamed: bool = False                               # repro/ -> experiments/ was performed this run
    results_upgraded: list[str] = field(default_factory=list)  # workspaces whose results.md -> results/index.md
    workspace_migrate_pending: bool = False                   # data dirs sit outside workspace/, need move
    workspace_migrated: list[str] = field(default_factory=list)  # dirs moved under workspace/ this run

    def to_dict(self) -> dict:
        return {
            "linked": self.linked,
            "pruned": self.pruned,
            "new_config_keys": self.new_config_keys,
            "config_fields_written": self.config_fields_written,
            "config_backed_up": self.config_backed_up,
            "deps_changed": self.deps_changed,
            "index_stale_hint": self.index_stale_hint,
            "repro_rename_pending": self.repro_rename_pending,
            "repro_renamed": self.repro_renamed,
            "results_upgraded": self.results_upgraded,
            "workspace_migrate_pending": self.workspace_migrate_pending,
            "workspace_migrated": self.workspace_migrated,
        }


# Marker header for the block migrate appends to config.yaml (kept stable so users recognize it).
_APPEND_MARKER = "# ===== 以下字段由 helix migrate 按模板补充，请填值 ====="


def _append_missing_fields(cfg: Config, missing_keys: list[str], report: MigrateReport,
                           logs: list[str]) -> None:
    """Append template blocks for missing config keys to the user's config.yaml (backup first, never rewrite).

    Copies each key's block (comments + name + placeholder) verbatim from config.example.yaml, so field
    names/comments/placement are controlled by the template, not hand-written. Only appends keys the user
    actually lacks (idempotent). No missing keys -> file untouched, no backup.
    """
    if not missing_keys or not cfg._path or not cfg._path.exists() or not EXAMPLE_CONFIG.exists():
        return
    example_text = EXAMPLE_CONFIG.read_text(encoding="utf-8")
    blocks: list[str] = []
    written: list[str] = []
    for key in missing_keys:
        block = _extract_field_block(example_text, key)
        if block:
            blocks.append(block)
            written.append(key)
    if not written:
        return

    # backup before touching the file (revertible; aligns with "never lose user data")
    bak = cfg._path.with_suffix(cfg._path.suffix + ".bak")
    shutil.copy(cfg._path, bak)
    report.config_backed_up = True

    existing = cfg._path.read_text(encoding="utf-8")
    sep = "" if existing.endswith("\n") else "\n"
    appended = f"{existing}{sep}\n{_APPEND_MARKER}\n" + "\n\n".join(blocks) + "\n"
    cfg._path.write_text(appended, encoding="utf-8")
    report.config_fields_written = written
    logs.append(f"已按模板补充 config 字段（值留空，请填）：{'、'.join(written)}；已备份 {bak.name}")


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


def _move_into_workspace(src: Path, dst: Path, label: str, report: MigrateReport, logs: list[str]) -> None:
    """Copy src -> dst, verify file count, then delete src. Only-move-never-lose (same as repro migration)."""
    if dst.exists():
        logs.append(f"跳过搬迁：目标 {dst} 已存在，为避免覆盖不自动合并。请手动核对 {src} 与 {dst}")
        report.workspace_migrate_pending = True
        return
    before = _count_files(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
    after = _count_files(dst)
    if after < before:
        logs.append(f"搬迁校验未通过（{label}：源 {before} 文件，目标 {after}），已保留原 {src} 不删")
        report.workspace_migrate_pending = True
        return
    shutil.rmtree(src)
    report.workspace_migrated.append(label)
    logs.append(f"已搬迁 {label}：{src} → {dst}（{after} 文件，已核对；旧目录已清理）")


def _migrate_to_workspace(cfg: Config, report: MigrateReport, logs: list[str], do_move: bool) -> None:
    """Move legacy top-level data dirs (notes/experiments/.helix/draft_notes) under workspace/.

    Storage-layout change (CLAUDE.md): only-move-never-lose, idempotent, --yes gated. A notes_dir that is
    an absolute path (external Obsidian vault) is left in place. Targets already inside workspace/ are skipped.
    """
    ws = cfg.workspace_path
    base = cfg.base_dir
    # (legacy source under base_dir, target under workspace, label). notes only if notes_dir is relative.
    candidates: list[tuple[Path, Path, str]] = []
    if not Path(cfg.notes_dir).expanduser().is_absolute():
        candidates.append((base / cfg.notes_dir, ws / cfg.notes_dir, "notes"))
    if not Path(cfg.experiments_dir).expanduser().is_absolute():
        candidates.append((base / cfg.experiments_dir, ws / cfg.experiments_dir, "experiments"))
    candidates.append((base / ".helix", ws / ".helix", ".helix"))
    candidates.append((base / "draft_notes", ws / "draft_notes", "draft_notes"))

    pending: list[tuple[Path, Path, str]] = []
    for src, dst, label in candidates:
        # skip if source doesn't exist, or already resolves inside workspace (nothing to move)
        if not src.exists() or not src.is_dir():
            continue
        if src.resolve() == dst.resolve():
            continue
        pending.append((src, dst, label))

    if not pending:
        return
    if not do_move:
        names = "、".join(label for _, _, label in pending)
        report.workspace_migrate_pending = True
        logs.append(f"待迁移：{names} 还在 workspace/ 外。跑 `helix migrate --yes` 搬进 "
                    f"{ws.name}/（只搬不删，先校验后核对）")
        return
    for src, dst, label in pending:
        _move_into_workspace(src, dst, label, report, logs)


def run_migrate(cfg: Config, scope: str = "project", *, do_move: bool = False) -> tuple[MigrateReport, list[str]]:
    """Reconcile a pulled checkout. Idempotent and non-destructive by default.

    do_move=True (helix migrate --yes) performs storage moves (data dirs -> workspace/, repro/ -> experiments/);
    otherwise they're only reported as pending. Returns (report, log lines); the cli prints log + summary.
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

    # 2. Config drift — append missing fields (template blocks) into config.yaml, after backing it up.
    #    Only appends (never rewrites existing lines), so user comments/layout are preserved.
    example_keys = _example_top_keys()
    user_keys = set(_user_top_keys(cfg))
    report.new_config_keys = [k for k in example_keys if k not in user_keys]
    _append_missing_fields(cfg, report.new_config_keys, report, logs)

    # 3. Dependency drift — compare uv.lock hash against last-recorded; hint, don't install.
    state = _load_state(cfg)
    lock_hash = _file_hash(LOCK_FILE)
    if lock_hash is not None and state.get("lock_hash") != lock_hash:
        # first run has no prior hash; only flag as "changed" if we had recorded one before
        report.deps_changed = "lock_hash" in state

    # 4. Index staleness — hint only.
    report.index_stale_hint = _index_looks_stale(cfg)

    # 5. Storage-layout migration (only-move-never-lose, --yes gated). Order matters:
    #    (a) move top-level data dirs under workspace/ first, so (b)/(c) operate on the new location.
    _migrate_to_workspace(cfg, report, logs, do_move)
    _migrate_repro_dir(cfg, report, logs, do_move)      # legacy repro/ -> experiments/ (now under workspace)
    _upgrade_results_files(cfg, report, logs)           # results.md -> results/index.md

    # Persist state (record current lock hash so the next migrate can detect changes).
    state["lock_hash"] = lock_hash
    _save_state(cfg, state)

    return report, logs
