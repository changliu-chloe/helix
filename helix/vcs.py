"""Optional git management of experiment workspaces: ensure remote code == a known local commit.

Each experiment workspace (where sync.yaml lives) is its own git repo. When the git block is enabled and
the user says "start the experiment" (exp start), helix inits the workspace repo if needed, sets identity
(from config, into the repo's own .git/config — never ~/.gitconfig), commits the round, then pushes. So
each experiment maps to one commit, traceable to an exact version. "Every round" = the changes between the
end of the last experiment and the start of this one. Disabled by default -> exp start only pushes.
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


def is_git_repo(repo_dir: Path) -> bool:
    """True if repo_dir is the top of a git work tree (has its own .git)."""
    return (repo_dir / ".git").exists()


def ensure_repo(repo_dir: Path) -> bool:
    """git init repo_dir if it isn't already a repo (idempotent). Returns True if a new repo was created."""
    if is_git_repo(repo_dir):
        return False
    proc = _git(repo_dir, "init")
    if proc.returncode != 0:
        raise RuntimeError(f"git init 失败：{proc.stderr.strip()}")
    return True


def set_identity(repo_dir: Path, name: str, email: str) -> None:
    """Set commit identity local to this repo (writes repo/.git/config; never touches ~/.gitconfig)."""
    for key, val in (("user.name", name), ("user.email", email)):
        proc = _git(repo_dir, "config", key, val)
        if proc.returncode != 0:
            raise RuntimeError(f"git config {key} 失败：{proc.stderr.strip()}")


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
