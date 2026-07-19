"""Sensitive remote credentials, loaded from a separate git-ignored file — never into an LLM request.

Why a separate file (not config.yaml): the whole point of the local-dev / remote-execute split is that
SSH and sudo passwords must stay inside the CLI. They live in config.secrets.yaml (sibling of config.yaml,
git-ignored), are read ONLY at the subprocess injection points in ssh.py, and are injected via env
(SSHPASS) / stdin (sudo -S) — never into argv, logs, or any structure returned to the CLI/agent/model.

SSH key auth is preferred (then no password is stored at all). Passwords are the fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_SECRETS_NAME = "config.secrets.yaml"


@dataclass
class RemoteSecret:
    """Credentials for one remote. Empty fields mean "use SSH key / no sudo password"."""

    ssh_password: str = ""
    sudo_password: str = ""

    @property
    def has_ssh_password(self) -> bool:
        return bool(self.ssh_password)

    @property
    def has_sudo_password(self) -> bool:
        return bool(self.sudo_password)


class Secrets:
    """All remote credentials. Deliberately has no to_dict / __repr__ that exposes values."""

    def __init__(self, by_remote: dict[str, RemoteSecret]):
        self._by_remote = by_remote

    def for_remote(self, name: str) -> RemoteSecret:
        """Credentials for a remote by name; empty RemoteSecret if none recorded (key-auth path)."""
        return self._by_remote.get(name, RemoteSecret())

    def __repr__(self) -> str:  # never leak values, even in tracebacks/logs
        return f"<Secrets remotes={sorted(self._by_remote)}>"


def secrets_path(base_dir: Path) -> Path:
    """Location of the secrets file: sibling of config.yaml."""
    return base_dir / DEFAULT_SECRETS_NAME


def load_secrets(base_dir: Path) -> Secrets:
    """Load config.secrets.yaml. Missing file -> empty Secrets (key-auth / no-sudo path works fine)."""
    p = secrets_path(base_dir)
    if not p.exists():
        return Secrets({})
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return Secrets({})
    if not isinstance(raw, dict):
        return Secrets({})

    by_remote: dict[str, RemoteSecret] = {}
    for name, spec in (raw.get("remotes") or {}).items():
        spec = spec or {}
        by_remote[name] = RemoteSecret(
            ssh_password=str(spec.get("ssh_password", "") or ""),
            sudo_password=str(spec.get("sudo_password", "") or ""),
        )
    return Secrets(by_remote)
