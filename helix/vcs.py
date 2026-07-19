"""Git guardrails for the experiment belt: ensure remote code == a known local commit.

"Every round" = the changes between the end of the last experiment and the start of this one. When the
user says "start the experiment", helix commits the round and pushes, so each experiment maps to one
commit and results are traceable to an exact version.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _git(repo_dir: Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    if shutil.which("git") is None:
        raise FileNotFoundError("找不到 git")
    return subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        capture_output=True, text=True, timeout=timeout,
    )


def is_clean(repo_dir: Path) -> bool:
    """True if the working tree has no uncommitted changes (git status --porcelain empty)."""
    proc = _git(repo_dir, "status", "--porcelain")
    return proc.returncode == 0 and not proc.stdout.strip()


def current_commit(repo_dir: Path) -> str:
    """Short hash of HEAD (empty string if not resolvable)."""
    proc = _git(repo_dir, "rev-parse", "--short", "HEAD")
    return proc.stdout.strip() if proc.returncode == 0 else ""


def commit_round(repo_dir: Path, message: str) -> str:
    """Stage everything and commit this round. Returns the new short hash.

    Raises RuntimeError if nothing was committed (e.g. the tree was already clean — the caller should
    check is_clean first to decide whether a new round is even needed).
    """
    add = _git(repo_dir, "add", "-A")
    if add.returncode != 0:
        raise RuntimeError(f"git add 失败：{add.stderr.strip()}")
    commit = _git(repo_dir, "commit", "-m", message)
    if commit.returncode != 0:
        raise RuntimeError(f"git commit 失败：{commit.stderr.strip() or commit.stdout.strip()}")
    return current_commit(repo_dir)
