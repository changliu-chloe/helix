"""helix init: wire project skills + dev conventions into agents' discovery paths.

Two families of agents look in different places:
- Claude Code reads CLAUDE.md and discovers skills under .claude/skills/.
- Codex / Cursor / Trae read AGENTS.md and discover skills under .agents/skills/
  (Codex scans .agents/skills from CWD up to the repo root; global is ~/.agents/skills).

So init does two things, both idempotent and safe to re-run:
1. Symlink each skill into BOTH .claude/skills/ and .agents/skills/ — one skill source,
   reachable by whichever agent the user runs.
2. Symlink AGENTS.md -> CLAUDE.md at the project root, so the single set of dev
   conventions in CLAUDE.md also reaches Codex/Cursor/Trae. No second file to maintain.
"""

from __future__ import annotations

import os
from pathlib import Path

# Project root = two levels up from this file (helix/init.py -> helix/ -> project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILLS_SRC = PROJECT_ROOT / "skills"

# Skill discovery dirs, keyed by the agent family that scans them. Both get linked.
_SKILL_DIRS = (".claude", ".agents")

# Conventions live in CLAUDE.md; AGENTS.md is a symlink to it for the other agents.
CONVENTIONS_SRC = PROJECT_ROOT / "CLAUDE.md"
AGENTS_MD = PROJECT_ROOT / "AGENTS.md"


def _link_scope_dirs(scope: str) -> list[Path]:
    """Return the skills target dirs (.claude/skills + .agents/skills).

    project=inside the project; global=under the user's home. Both families are
    always linked so helix works regardless of which agent the user runs.
    """
    base = Path.home() if scope == "global" else PROJECT_ROOT
    return [base / d / "skills" for d in _SKILL_DIRS]


def list_skill_names() -> list[str]:
    """List all skill names under skills/ that contain SKILL.md (the main entry 'helix' comes first)."""
    if not SKILLS_SRC.exists():
        return []
    names = [d.name for d in sorted(SKILLS_SRC.iterdir()) if d.is_dir() and (d / "SKILL.md").exists()]
    if "helix" in names:
        names.remove("helix")
        names.insert(0, "helix")
    return names


def _link_one(link: Path, target: Path, logs: list[str]) -> None:
    """Create/refresh a single symlink at `link` -> `target`, appending to logs. Idempotent."""
    if link.is_symlink():
        if link.resolve() == target:
            logs.append(f"已存在（跳过）：{link} -> {target}")
            return
        link.unlink()  # stale symlink pointing elsewhere, rebuild it
    elif link.exists():
        # real dir/file, don't overwrite, leave it for the user to handle
        logs.append(f"⚠ 已存在同名非软链，跳过（请手动处理）：{link}")
        return
    link.symlink_to(target, target_is_directory=target.is_dir())
    logs.append(f"已链接：{link} -> {target}")


def link_skills(scope: str = "project") -> list[str]:
    """Symlink each skill into both .claude/skills/ and .agents/skills/. Returns an operation log."""
    logs: list[str] = []
    if not SKILLS_SRC.exists():
        return [f"未找到 skills 源目录：{SKILLS_SRC}"]

    for dest_dir in _link_scope_dirs(scope):
        dest_dir.mkdir(parents=True, exist_ok=True)
        for skill_dir in sorted(SKILLS_SRC.iterdir()):
            if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").exists():
                continue
            _link_one(dest_dir / skill_dir.name, skill_dir.resolve(), logs)
    return logs


def link_agents_md() -> list[str]:
    """Symlink AGENTS.md -> CLAUDE.md at the project root so Codex/Cursor/Trae read the same conventions.

    Idempotent; project-scoped only (conventions are per-repo). Skips if CLAUDE.md is
    missing, or if a real (non-symlink) AGENTS.md already exists (left for the user).
    """
    logs: list[str] = []
    if not CONVENTIONS_SRC.exists():
        return [f"未找到规约源：{CONVENTIONS_SRC}（跳过 AGENTS.md 软链）"]
    _link_one(AGENTS_MD, CONVENTIONS_SRC.resolve(), logs)
    return logs


def prune_stale_skill_links(scope: str = "project") -> list[str]:
    """Remove symlinks under the skills dirs that point into skills/ but whose target no longer exists.

    Handles skills deleted or renamed upstream: after a pull the old symlink would
    dangle. Only touches symlinks resolving inside SKILLS_SRC — real dirs and links
    the user added pointing elsewhere are left untouched. Covers both .claude/skills
    and .agents/skills. Returns an operation log.
    """
    logs: list[str] = []
    skills_root = SKILLS_SRC.resolve()
    for dest_dir in _link_scope_dirs(scope):
        if not dest_dir.exists():
            continue
        for entry in sorted(dest_dir.iterdir()):
            if not entry.is_symlink():
                continue
            # os.readlink + manual resolve: the target may not exist, so entry.resolve() alone is ambiguous
            raw = Path(os.readlink(entry))
            target = raw if raw.is_absolute() else (entry.parent / raw)
            try:
                target_resolved = target.resolve()
            except OSError:
                target_resolved = target
            # only consider links that belong to us (point into skills/)
            try:
                target_resolved.relative_to(skills_root)
            except ValueError:
                continue  # points elsewhere — not ours, leave it
            if not target_resolved.exists():
                entry.unlink()
                logs.append(f"已清理失效软链（源已删除/改名）：{entry}")
    return logs
