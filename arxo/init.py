"""arxo init：把项目 skills 接入 Claude Code 的发现路径。

创建 .claude/skills/ 下指向 skills/ 里各 skill 的软链，让外层 agent
（Claude Code 等）能自然语言触发这些 skill。幂等、可重复执行。
"""

from __future__ import annotations

from pathlib import Path

# 项目根 = 本文件的上两级（arxo/init.py -> arxo/ -> 项目根）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILLS_SRC = PROJECT_ROOT / "skills"


def _link_scope_dir(scope: str) -> Path:
    """返回 .claude/skills 目标目录：project=项目内，global=~/.claude/skills。"""
    if scope == "global":
        return Path.home() / ".claude" / "skills"
    return PROJECT_ROOT / ".claude" / "skills"


def list_skill_names() -> list[str]:
    """列出 skills/ 下所有含 SKILL.md 的 skill 名（总入口 arxo 排在最前）。"""
    if not SKILLS_SRC.exists():
        return []
    names = [d.name for d in sorted(SKILLS_SRC.iterdir()) if d.is_dir() and (d / "SKILL.md").exists()]
    if "arxo" in names:
        names.remove("arxo")
        names.insert(0, "arxo")
    return names


def link_skills(scope: str = "project") -> list[str]:
    """为每个 skill 建软链到 .claude/skills/<name>。返回操作日志。"""
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
            link.unlink()  # 指向别处的旧软链，重建
        elif link.exists():
            # 真实目录/文件，不覆盖，交给用户处理
            logs.append(f"⚠ 已存在同名非软链，跳过（请手动处理）：{link}")
            continue

        link.symlink_to(target, target_is_directory=True)
        logs.append(f"已链接：{link} -> {target}")

    return logs
