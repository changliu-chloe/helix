"""Local <-> remote transport for experiment workspaces (helix exp push/pull).

Design principle (consistent with the project): the CLI only does deterministic, guarded file
transport (an rsync wrapper). It never runs commands on the remote and never schedules experiments
-- the user ssh's in and runs things by hand (human-in-the-loop). push/pull are the two halves of a
belt that moves declared files up and distilled results back down.

The transport contract:
- What machine to use lives in config.remotes (a reusable machine registry).
- What THIS experiment pushes/pulls lives in the workspace's own sync.yaml (travels with the workspace).
- Where the remote agent drops results lives in RESULTS_LAYOUT.md (pushed up; pull globs mirror it).

Safety (aligned with "never lose user data"):
- No `--delete` ever -- transfers only add/update, never mirror-delete.
- push and pull are both scoped to `<remote_repro_root>/<domain>/<short_name>/` on the remote.
- pull writes only into results/{metrics,plots,tables}/ -- it never overwrites hand-written
  setup.md / plan.md / results/index.md / RESULTS_LAYOUT.md.
- --dry-run maps to rsync --dry-run so the user can preview every transfer.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import Config, Remote

# pull only ever lands raw artifacts here (relative to the workspace). Hand-written docs stay untouched.
PULL_SUBDIRS = ("results/metrics", "results/plots", "results/tables")
# RESULTS_LAYOUT.md must always ride along on push -- it's the remote-agent write contract.
REQUIRED_PUSH = "RESULTS_LAYOUT.md"


@dataclass
class SyncSpec:
    """Parsed sync.yaml of one workspace."""

    remote: str = ""                       # references a name in config.remotes
    push: list[str] = field(default_factory=list)
    pull: list[str] = field(default_factory=list)


def load_sync_spec(workspace: Path) -> SyncSpec:
    """Read <workspace>/sync.yaml. Raises FileNotFoundError if missing (run `helix exp new` first)."""
    p = workspace / "sync.yaml"
    if not p.exists():
        raise FileNotFoundError(f"工作区缺少 sync.yaml：{p}（先跑 helix exp new 生成骨架）")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        data = {}
    return SyncSpec(
        remote=str(data.get("remote", "") or ""),
        push=list(data.get("push") or []),
        pull=list(data.get("pull") or []),
    )


def _remote_dir(remote: Remote, domain: str, short_name: str) -> str:
    """The remote workspace path: <remote_repro_root>/<domain>/<short_name>/ (trailing slash for rsync)."""
    root = remote.remote_repro_root.rstrip("/")
    return f"{root}/{domain}/{short_name}/"


def _has_plaintext_password(host: str) -> bool:
    """Heuristic: a user:password@host form embeds a plaintext secret; warn and prefer an ssh alias."""
    return "@" in host and ":" in host.split("@", 1)[0]


@dataclass
class SyncResult:
    """Outcome of one push/pull."""

    direction: str                         # push | pull
    remote_name: str
    remote_dir: str
    cmd: list[str]
    dry_run: bool
    returncode: int
    warnings: list[str] = field(default_factory=list)


def _rsync_base(dry_run: bool) -> list[str]:
    # -a archive, -z compress, -h human, -i itemize changes so the user sees exactly what moved.
    # No --delete, ever.
    base = ["rsync", "-azh", "-i"]
    if dry_run:
        base.append("--dry-run")
    return base


def _build_includes(patterns: list[str]) -> list[str]:
    """Translate a workspace-relative glob list into rsync include/exclude rules.

    We include parent dirs + each pattern, then exclude everything else, so only declared paths move.
    """
    args: list[str] = []
    for pat in patterns:
        # ensure every parent path segment is walkable
        parts = pat.split("/")
        acc = ""
        for seg in parts[:-1]:
            acc = f"{acc}{seg}/"
            args += ["--include", acc]
        args += ["--include", pat]
    args += ["--exclude", "*"]
    return args


def push(cfg: Config, workspace: Path, *, dry_run: bool = False) -> SyncResult:
    """Push declared files (sync.yaml `push`, RESULTS_LAYOUT.md forced) up to the remote workspace dir.

    Never deletes on the remote. Raises on config/spec problems before touching rsync.
    """
    workspace = workspace.resolve()
    domain, short_name = workspace.parent.name, workspace.name
    spec = load_sync_spec(workspace)
    remote = _require_remote(cfg, spec)

    patterns = list(spec.push)
    if REQUIRED_PUSH not in patterns:
        patterns.append(REQUIRED_PUSH)  # contract file always rides along

    warnings: list[str] = []
    if _has_plaintext_password(remote.host):
        warnings.append(f"remote '{remote.name}' 的 host 里疑似含明文密码，建议改用 ~/.ssh/config alias")
    if not (workspace / REQUIRED_PUSH).exists():
        warnings.append(f"工作区缺 {REQUIRED_PUSH}（远程 agent 写盘约定），远程将收不到存放规则")

    remote_dir = _remote_dir(remote, domain, short_name)
    cmd = _rsync_base(dry_run) + _build_includes(patterns)
    cmd += [f"{workspace}/", f"{remote.host}:{remote_dir}"]
    rc = _run(cmd)
    return SyncResult("push", remote.name, remote_dir, cmd, dry_run, rc, warnings)


def pull(cfg: Config, workspace: Path, *, dry_run: bool = False) -> SyncResult:
    """Pull results (sync.yaml `pull`, restricted to results/{metrics,plots,tables}/) back into the workspace.

    Never overwrites hand-written docs: pull patterns are intersected with PULL_SUBDIRS.
    """
    workspace = workspace.resolve()
    domain, short_name = workspace.parent.name, workspace.name
    spec = load_sync_spec(workspace)
    remote = _require_remote(cfg, spec)

    patterns = _guard_pull_patterns(spec.pull)
    warnings: list[str] = []
    if _has_plaintext_password(remote.host):
        warnings.append(f"remote '{remote.name}' 的 host 里疑似含明文密码，建议改用 ~/.ssh/config alias")
    if not patterns:
        warnings.append("sync.yaml 的 pull 清单为空或都不在 results/{metrics,plots,tables}/ 内，无可拉取项")

    # ensure local result dirs exist so rsync has a landing spot
    for sub in PULL_SUBDIRS:
        (workspace / sub).mkdir(parents=True, exist_ok=True)

    remote_dir = _remote_dir(remote, domain, short_name)
    cmd = _rsync_base(dry_run) + _build_includes(patterns)
    cmd += [f"{remote.host}:{remote_dir}", f"{workspace}/"]
    rc = _run(cmd) if patterns else 0
    return SyncResult("pull", remote.name, remote_dir, cmd, dry_run, rc, warnings)


def _guard_pull_patterns(patterns: list[str]) -> list[str]:
    """Keep only pull patterns under results/{metrics,plots,tables}/ -- never let pull touch hand-written docs."""
    out: list[str] = []
    for pat in patterns:
        norm = pat.lstrip("./")
        if any(norm.startswith(sub) for sub in PULL_SUBDIRS):
            out.append(norm)
    return out


def _require_remote(cfg: Config, spec: SyncSpec) -> Remote:
    if not spec.remote:
        raise ValueError("sync.yaml 未填 remote（应为 config.remotes 里的机器名）——传送带对本工作区未启用")
    remote = cfg.find_remote(spec.remote)
    if remote is None:
        names = ", ".join(r.name for r in cfg.remotes) or "（config 未配 remotes）"
        raise ValueError(f"未知 remote '{spec.remote}'，config.remotes 已有：{names}")
    if not remote.host or not remote.remote_repro_root:
        raise ValueError(f"remote '{remote.name}' 缺 host 或 remote_repro_root，先在 config.yaml 补全")
    return remote


def _run(cmd: list[str]) -> int:
    """Run rsync, streaming its output. Raises FileNotFoundError with a friendly hint if rsync is absent."""
    if shutil.which(cmd[0]) is None:
        raise FileNotFoundError(f"找不到 {cmd[0]}，请先安装（macOS/Linux 一般自带 rsync）")
    proc = subprocess.run(cmd, check=False)
    return proc.returncode
