"""helix init: wire project skills into Claude Code's discovery path.

Creates symlinks under .claude/skills/ pointing to each skill in skills/, so an
outer agent (Claude Code, etc.) can trigger these skills via natural language.
Idempotent and safe to run repeatedly.
"""

from __future__ import annotations

from pathlib import Path

# Project root = two levels up from this file (helix/init.py -> helix/ -> project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILLS_SRC = PROJECT_ROOT / "skills"


def _link_scope_dir(scope: str) -> Path:
    """Return the .claude/skills target dir: project=inside project, global=~/.claude/skills."""
    if scope == "global":
        return Path.home() / ".claude" / "skills"
    return PROJECT_ROOT / ".claude" / "skills"


def list_skill_names() -> list[str]:
    """List all skill names under skills/ that contain SKILL.md (the main entry 'helix' comes first)."""
    if not SKILLS_SRC.exists():
        return []
    names = [d.name for d in sorted(SKILLS_SRC.iterdir()) if d.is_dir() and (d / "SKILL.md").exists()]
    if "helix" in names:
        names.remove("helix")
        names.insert(0, "helix")
    return names


def link_skills(scope: str = "project") -> list[str]:
    """Create a symlink for each skill at .claude/skills/<name>. Returns an operation log."""
    logs: list[str] = []
    if not SKILLS_SRC.exists():
        return [f"未找到 skills 源目录：{SKILLS_SRC}"]

    dest_dir = _link_scope_dir(scope)
    dest_dir.mkdir(parents=True, exist_ok=True)

    for skill_dir in sorted(SKILLS_SRC.iterdir()):
        if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").exists():
            continue
        link = dest_dir / skill_dir.name
        target = skill_dir.resolve()

        if link.is_symlink():
            if link.resolve() == target:
                logs.append(f"已存在（跳过）：{link} -> {target}")
                continue
            link.unlink()  # stale symlink pointing elsewhere, rebuild it
        elif link.exists():
            # real dir/file, don't overwrite, leave it for the user to handle
            logs.append(f"⚠ 已存在同名非软链，跳过（请手动处理）：{link}")
            continue

        link.symlink_to(target, target_is_directory=True)
        logs.append(f"已链接：{link} -> {target}")

    return logs
