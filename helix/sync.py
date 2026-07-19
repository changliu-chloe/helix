"""Local <-> remote transport for experiment workspaces (helix exp push/pull), over scp.

Design principle (consistent with the project): the CLI only does deterministic, guarded file
transport. It never runs experiments -- that's exp run (remote tmux). push/pull are the two halves of
a belt that moves declared files up and distilled results back down.

Why scp (not rsync): scp ships with OpenSSH on macOS/Windows/Linux alike and honors ~/.ssh/config
aliases (jump host + key). macOS's bundled rsync is openrsync (feature-incomplete -- no --mkpath, etc.),
and Windows usually has no rsync. scp is the portable common denominator.

The transport contract:
- What machine to use lives in config.remotes (a reusable machine registry).
- What THIS experiment pushes/pulls + WHERE it lives on the remote lives in the workspace's sync.yaml
  (remote / remote_path / push / pull), traveling with the workspace.
- Where the remote agent drops results lives in RESULTS_LAYOUT.md (pushed up; pull mirrors it).

Safety (aligned with "never lose user data"):
- scp never mirror-deletes -- transfers only add/overwrite named items.
- push sends only the items declared in sync.yaml `push` (a whitelist enforced by enumeration).
- pull only fetches remote results/{metrics,plots,tables}/ -- never overwrites hand-written
  setup.md / plan.md / results/index.md / RESULTS_LAYOUT.md.
- --dry-run prints the exact transfers without running scp (simulated -- scp has no native dry-run).
- The remote path is confirmed by the user on first use (see resolve_remote_path / RemotePathUnset).
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


class RemotePathUnset(Exception):
    """Raised when a workspace has no confirmed remote_path yet. Carries the suggested default so the
    CLI can print it and ask the user to confirm with --remote-path."""

    def __init__(self, default: str):
        super().__init__("remote_path 未确认")
        self.default = default


@dataclass
class SyncSpec:
    """Parsed sync.yaml of one workspace."""

    remote: str = ""                       # references a name in config.remotes
    remote_path: str = ""                  # confirmed remote workspace dir; empty = not confirmed yet
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
        remote_path=str(data.get("remote_path", "") or ""),
        push=list(data.get("push") or []),
        pull=list(data.get("pull") or []),
    )


def set_remote_path(workspace: Path, remote_path: str) -> None:
    """Write the user-confirmed remote_path back into the workspace's sync.yaml, preserving the header."""
    p = workspace / "sync.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        data = {}
    # Rebuild in a stable field order so the file stays readable.
    spec = {
        "remote": data.get("remote", "") or "",
        "remote_path": remote_path,
        "push": data.get("push") or [],
        "pull": data.get("pull") or [],
    }
    header = ("# 本实验的传送清单。remote 填 config.yaml remotes 里的机器名。\n"
              "# remote_path: 远程工作区路径（首次 push 时由你用 --remote-path 确认后写入）。\n"
              "# push: 推到远程的文件（RESULTS_LAYOUT.md 必带，是远程写盘约定）。\n"
              "# pull: 从远程回拉的结果（对齐 RESULTS_LAYOUT.md 的三个子目录）。\n")
    p.write_text(header + yaml.safe_dump(spec, allow_unicode=True, sort_keys=False,
                                         default_flow_style=False), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Remote path: single source of truth (push/pull AND run/probe resolve through here)
# --------------------------------------------------------------------------- #

def default_remote_path(remote: Remote, workspace: Path) -> str:
    """Suggested remote workspace dir: <remote_repro_root>/<domain>/<short_name> (no trailing slash)."""
    root = remote.remote_repro_root.rstrip("/")
    return f"{root}/{workspace.parent.name}/{workspace.name}"


def resolve_remote_path(spec: SyncSpec) -> str | None:
    """The confirmed remote path, or None when the workspace hasn't confirmed one yet."""
    return spec.remote_path or None


def require_remote_path(remote: Remote, workspace: Path, spec: SyncSpec) -> str:
    """Resolve the remote path or raise RemotePathUnset(default) for the CLI to prompt confirmation."""
    path = resolve_remote_path(spec)
    if path is None:
        raise RemotePathUnset(default_remote_path(remote, workspace))
    return path


def _has_plaintext_password(host: str) -> bool:
    """Heuristic: a user:password@host form embeds a plaintext secret; warn and prefer an ssh alias."""
    return "@" in host and ":" in host.split("@", 1)[0]


@dataclass
class SyncResult:
    """Outcome of one push/pull."""

    direction: str                         # push | pull
    remote_name: str
    remote_dir: str
    cmds: list[list[str]]                  # the scp argv(s) that ran (or would run, in dry-run)
    dry_run: bool
    returncode: int
    warnings: list[str] = field(default_factory=list)


def _scp_base(remote: Remote) -> list[str]:
    """scp argv prefix: recursive + optional identity file. Destination host is remote.ssh_target."""
    base = ["scp", "-r", "-o", "StrictHostKeyChecking=accept-new"]
    if remote.ssh_key:
        base += ["-i", remote.ssh_key]
    return base


def _expand_push_items(workspace: Path, patterns: list[str]) -> tuple[list[str], list[str]]:
    """Normalize the push list into existing top-level files/dirs to scp. Returns (items, warnings).

    A `dir/**` (or `dir/`) pattern maps to the directory itself (scp -r sends it whole); a bare file
    maps to the file. Missing items are skipped with a warning. Enumeration IS the whitelist.
    """
    items: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for pat in patterns:
        top = pat.split("/", 1)[0] if "/" in pat else pat
        top = top.strip()
        if not top or top in seen:
            continue
        seen.add(top)
        if (workspace / top).exists():
            items.append(top)
        else:
            warnings.append(f"push 清单项不存在，跳过：{top}")
    return items, warnings


def push(cfg: Config, workspace: Path, *, dry_run: bool = False) -> SyncResult:
    """Push declared files (sync.yaml `push`, RESULTS_LAYOUT.md forced) to the confirmed remote path via scp.

    Raises RemotePathUnset if the workspace hasn't confirmed a remote path yet (CLI prompts --remote-path).
    """
    workspace = workspace.resolve()
    spec = load_sync_spec(workspace)
    remote = _require_remote(cfg, spec)
    remote_dir = require_remote_path(remote, workspace, spec)

    patterns = list(spec.push)
    if REQUIRED_PUSH not in patterns:
        patterns.append(REQUIRED_PUSH)  # contract file always rides along
    items, warnings = _expand_push_items(workspace, patterns)

    if _has_plaintext_password(remote.host):
        warnings.append(f"remote '{remote.name}' 的 host 里疑似含明文密码，建议改用 ~/.ssh/config alias")
    if not (workspace / REQUIRED_PUSH).exists():
        warnings.append(f"工作区缺 {REQUIRED_PUSH}（远程 agent 写盘约定），远程将收不到存放规则")

    dest = f"{remote.host}:{remote_dir}/"
    cmds = [_scp_base(remote) + [str(workspace / it), dest] for it in items]

    if dry_run:
        return SyncResult("push", remote.name, remote_dir, cmds, True, 0, warnings)

    # scp won't create the (multi-level) remote target dir; ensure it exists first.
    mk_rc = _ensure_remote_dir(remote, remote_dir)
    if mk_rc != 0:
        warnings.append(f"远程目录创建可能失败（mkdir -p 退出码 {mk_rc}）")
    rc = 0
    for cmd in cmds:
        rc = _run(cmd) or rc
    return SyncResult("push", remote.name, remote_dir, cmds, False, rc, warnings)


def pull(cfg: Config, workspace: Path, *, dry_run: bool = False) -> SyncResult:
    """Pull results/{metrics,plots,tables}/ from the confirmed remote path back into the workspace via scp.

    Never overwrites hand-written docs: only the three result subdirs are ever fetched.
    """
    workspace = workspace.resolve()
    spec = load_sync_spec(workspace)
    remote = _require_remote(cfg, spec)
    remote_dir = require_remote_path(remote, workspace, spec)

    warnings: list[str] = []
    if _has_plaintext_password(remote.host):
        warnings.append(f"remote '{remote.name}' 的 host 里疑似含明文密码，建议改用 ~/.ssh/config alias")

    # local landing spots
    (workspace / "results").mkdir(parents=True, exist_ok=True)
    for sub in PULL_SUBDIRS:
        (workspace / sub).mkdir(parents=True, exist_ok=True)

    # one scp per result subdir; each lands under the local results/ dir.
    cmds: list[list[str]] = []
    for sub in PULL_SUBDIRS:
        src = f"{remote.host}:{remote_dir}/{sub}"
        cmds.append(_scp_base(remote) + [src, str(workspace / "results") + "/"])

    if dry_run:
        return SyncResult("pull", remote.name, remote_dir, cmds, True, 0, warnings)

    # A missing remote subdir makes scp fail for that item; that's fine (nothing to pull) -- don't hard-fail.
    rc = 0
    any_ok = False
    for cmd in cmds:
        r = _run(cmd)
        if r == 0:
            any_ok = True
        else:
            rc = r
    if not any_ok:
        warnings.append("远程 results/{metrics,plots,tables}/ 都不存在或为空，无结果可拉")
        rc = 0  # nothing to pull is not an error
    return SyncResult("pull", remote.name, remote_dir, cmds, False, rc, warnings)


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
    """Run one scp command, streaming output. Raises FileNotFoundError with a hint if scp is absent."""
    if shutil.which(cmd[0]) is None:
        raise FileNotFoundError(f"找不到 {cmd[0]}，请先安装（OpenSSH 自带 scp，Mac/Win/Linux 通用）")
    proc = subprocess.run(cmd, check=False)
    return proc.returncode


def _ensure_remote_dir(remote: Remote, remote_dir: str) -> int:
    """mkdir -p the remote target over ssh, since scp won't create multi-level remote paths.

    Uses the same ssh destination as scp (remote.host — an ~/.ssh/config alias carries user/key/jump).
    No credentials touched here; password-auth remotes rely on the ssh layer / key auth.
    """
    if shutil.which("ssh") is None:
        return 127
    args = ["ssh"]
    if remote.ssh_key:
        args += ["-i", remote.ssh_key]
    args += [remote.ssh_target, f"mkdir -p {remote_dir}"]
    return subprocess.run(args, check=False).returncode
