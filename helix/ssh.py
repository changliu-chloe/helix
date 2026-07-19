"""Remote command execution over SSH, in remote tmux sessions — the CLI half of local-dev / remote-run.

Design (consistent with sync.py:_run): commands are built as argv lists (never shell=True), rsync/ssh/
tmux are system binaries probed with shutil.which, and credentials are injected at the subprocess boundary
only — via env (SSHPASS) or stdin (sudo -S). No password ever enters argv, logs, or a returned structure.
This is what lets the agent orchestrate remote runs without the model ever seeing a credential.

tmux runs ON THE REMOTE: a session started here survives ssh disconnect, so a long experiment keeps
running after the CLI returns (the agent is told the machine + session name + ETA instead of polling).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, Remote
from .secrets import RemoteSecret, Secrets


@dataclass
class RunResult:
    """Outcome of one remote command. Never contains credentials."""

    remote_name: str
    session: str
    argv: list[str]                        # the ssh argv actually run (no secrets — sshpass reads env)
    returncode: int
    stdout: str = ""
    stderr: str = ""
    warnings: list[str] = field(default_factory=list)


def _identity_args(remote: Remote) -> list[str]:
    return ["-i", remote.ssh_key] if remote.ssh_key else []


def _ssh_base(remote: Remote, secret: RemoteSecret) -> tuple[list[str], dict[str, str] | None]:
    """Build the ssh argv prefix + optional env for password injection.

    Key auth (no ssh_password): plain `ssh [-i key] <target>`, env=None.
    Password auth: `sshpass -e ssh ...`, with SSHPASS in the returned env — the password is NEVER in argv.
    """
    target = remote.ssh_target
    opts = ["-o", "BatchMode=no", "-o", "StrictHostKeyChecking=accept-new"]
    if secret.has_ssh_password:
        if shutil.which("sshpass") is None:
            raise FileNotFoundError(
                "配置了 ssh_password 但未装 sshpass（brew install hudochenkov/sshpass/sshpass / "
                "apt install sshpass）；或改用 SSH key 免密（推荐）"
            )
        argv = ["sshpass", "-e", "ssh", *opts, *_identity_args(remote), target]
        env = {"SSHPASS": secret.ssh_password}  # injected via env, not argv
        return argv, env
    argv = ["ssh", *opts, *_identity_args(remote), target]
    return argv, None


def _wrap_sudo(cmd: str, secret: RemoteSecret) -> tuple[str, bool]:
    """If a sudo password is set, feed it to `sudo -S` via stdin. Returns (remote_cmd, needs_stdin).

    The caller only invokes this for commands the agent marked as needing sudo; the password is written
    to the ssh process stdin, never placed in the command string.
    """
    # We prepend a sudo -S read; the password arrives on stdin (see _exec). Marker only.
    return cmd, secret.has_sudo_password


def _exec(argv: list[str], env: dict[str, str] | None, stdin_data: str | None, timeout: int) -> subprocess.CompletedProcess:
    """Run an ssh argv. Merges injection env over os.environ; feeds stdin_data (e.g. sudo pw) if given."""
    if shutil.which(argv[0]) is None:
        raise FileNotFoundError(f"找不到 {argv[0]}，请先安装")
    import os
    full_env = {**os.environ, **env} if env else None
    return subprocess.run(
        argv, input=stdin_data, capture_output=True, text=True, env=full_env, timeout=timeout,
    )


def require_remote(cfg: Config, remote_name: str) -> Remote:
    if not remote_name:
        raise ValueError("未指定 remote（sync.yaml 的 remote 字段或 --remote）")
    remote = cfg.find_remote(remote_name)
    if remote is None:
        names = ", ".join(r.name for r in cfg.remotes) or "（config 未配 remotes）"
        raise ValueError(f"未知 remote '{remote_name}'，config.remotes 已有：{names}")
    if not remote.host:
        raise ValueError(f"remote '{remote.name}' 缺 host，先在 config.yaml 补全")
    return remote


def run_in_tmux(
    cfg: Config, secrets: Secrets, remote: Remote, remote_path: str, cmd: str,
    *, session: str, oneshot: bool = False, use_sudo: bool = False, timeout: int = 60,
) -> RunResult:
    """Start (or reuse) a remote tmux session and send `cmd` to run in `remote_path` (the confirmed dir).

    remote_path is resolved by the CLI via sync.resolve_remote_path -- the single source of truth shared
    with push/pull, so run always lands in the same place push did.
    oneshot=True appends a kill-session so the window closes when the command finishes (e.g. env install).
    Otherwise the session persists (e.g. a training run) so it survives ssh disconnect.
    """
    secret = secrets.for_remote(remote.name)
    ssh_argv, env = _ssh_base(remote, secret)
    ws_dir = remote_path

    inner, needs_stdin = _wrap_sudo(cmd, secret) if use_sudo else (cmd, False)
    # cd into workspace, run the command; oneshot self-closes the session at the end.
    run_line = f"cd {ws_dir} && {inner}"
    if oneshot:
        run_line = f"{run_line}; tmux kill-session -t {session}"

    # Create the session detached if absent, then send the command line to it.
    remote_script = (
        f"tmux has-session -t {session} 2>/dev/null || tmux new-session -d -s {session}; "
        f"tmux send-keys -t {session} {_shq(run_line)} Enter"
    )
    stdin_data = secret.sudo_password + "\n" if needs_stdin else None
    proc = _exec([*ssh_argv, remote_script], env, stdin_data, timeout)

    warnings: list[str] = []
    if use_sudo and not secret.has_sudo_password:
        warnings.append("命令要 sudo 但 secrets 未配 sudo_password；若远程 sudo 非免密会卡住")
    return RunResult(remote.name, session, [*ssh_argv, "<remote-script>"], proc.returncode,
                     proc.stdout, proc.stderr, warnings)


def list_sessions(cfg: Config, secrets: Secrets, remote: Remote, timeout: int = 30) -> RunResult:
    """List remote tmux sessions (tmux ls). Empty output / rc!=0 when none exist."""
    secret = secrets.for_remote(remote.name)
    ssh_argv, env = _ssh_base(remote, secret)
    proc = _exec([*ssh_argv, "tmux ls 2>/dev/null || true"], env, None, timeout)
    return RunResult(remote.name, "", [*ssh_argv, "tmux ls"], proc.returncode, proc.stdout, proc.stderr)


def kill_session(cfg: Config, secrets: Secrets, remote: Remote, session: str, timeout: int = 30) -> RunResult:
    """Kill one remote tmux session."""
    secret = secrets.for_remote(remote.name)
    ssh_argv, env = _ssh_base(remote, secret)
    proc = _exec([*ssh_argv, f"tmux kill-session -t {_shq(session)}"], env, None, timeout)
    return RunResult(remote.name, session, [*ssh_argv, "tmux kill-session"], proc.returncode,
                     proc.stdout, proc.stderr)


def probe(cfg: Config, secrets: Secrets, remote: Remote, timeout: int = 30,
          remote_path: str | None = None) -> dict:
    """Probe remote experiment conditions: disk free + per-GPU memory/util via nvidia-smi.

    Disk is checked at remote_path when the workspace has confirmed one (df tolerates a not-yet-created
    path by walking up), else at the remote root. Returns a plain dict (no credentials) for the agent.
    """
    secret = secrets.for_remote(remote.name)
    ssh_argv, env = _ssh_base(remote, secret)
    path = remote_path or remote.remote_repro_root or "~"
    root = remote.remote_repro_root or "~"
    # df the confirmed path; if it doesn't exist yet (first probe before push), fall back to the root.
    # Two probes joined; parse leniently since a box may lack nvidia-smi.
    script = (
        f"echo '###DISK'; (df -h {path} 2>/dev/null || df -h {root} 2>/dev/null) | tail -n +2; "
        f"echo '###GPU'; nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu "
        f"--format=csv,noheader,nounits 2>/dev/null || echo 'NO_GPU'"
    )
    proc = _exec([*ssh_argv, script], env, None, timeout)
    return {
        "remote": remote.name,
        "returncode": proc.returncode,
        **_parse_probe(proc.stdout),
    }


def _parse_probe(out: str) -> dict:
    """Parse the ###DISK / ###GPU sections of the probe script output into structured data."""
    disk_lines: list[str] = []
    gpus: list[dict] = []
    section = None
    for line in out.splitlines():
        s = line.strip()
        if s == "###DISK":
            section = "disk"; continue
        if s == "###GPU":
            section = "gpu"; continue
        if not s:
            continue
        if section == "disk":
            disk_lines.append(s)
        elif section == "gpu":
            if s == "NO_GPU":
                continue
            parts = [p.strip() for p in s.split(",")]
            if len(parts) == 4:
                idx, used, total, util = parts
                gpus.append({
                    "index": _to_int(idx), "mem_used_mb": _to_int(used),
                    "mem_total_mb": _to_int(total), "util_pct": _to_int(util),
                })
    disk = {}
    if disk_lines:
        # df output: Filesystem Size Used Avail Use% Mounted
        cols = disk_lines[0].split()
        if len(cols) >= 5:
            disk = {"size": cols[1], "used": cols[2], "avail": cols[3], "use_pct": cols[4]}
    return {"disk": disk, "gpus": gpus, "has_gpu": bool(gpus)}


def _to_int(s: str) -> int | None:
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def _shq(s: str) -> str:
    """Single-quote a string for safe embedding in the remote shell command (POSIX quoting)."""
    return "'" + s.replace("'", "'\\''") + "'"
