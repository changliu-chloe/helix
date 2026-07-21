"""CLI exp start: optional per-workspace git commit before push."""

import argparse
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helix import cli, vcs
from helix.config import Config, GitConfig, Remote
from helix.sync import SyncResult


def _args(message=None, dry_run=True):
    return argparse.Namespace(message=message, dry_run=dry_run)


def _push_result():
    return SyncResult("push", "gpu-a100", "/data/exp/dom/paper", [], True, 0, [])


class TestExpStart(unittest.TestCase):
    def test_git_disabled_only_pushes(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            cfg = Config(git=GitConfig(enabled=False))
            with mock.patch("helix.vcs.ensure_repo") as ensure, \
                 mock.patch("helix.sync.push", return_value=_push_result()) as push:
                rc = cli._cmd_exp_start(_args(), cfg, ws, Remote("gpu-a100"))
        self.assertEqual(rc, 0)
        ensure.assert_not_called()
        push.assert_called_once()

    def test_git_enabled_requires_identity(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            cfg = Config(git=GitConfig(enabled=True, name="", email=""))
            with mock.patch("helix.sync.push") as push:
                rc = cli._cmd_exp_start(_args("feat: run"), cfg, ws, Remote("gpu-a100"))
        self.assertEqual(rc, 1)
        push.assert_not_called()

    def test_git_enabled_commits_workspace_repo(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            (ws / "plan.md").write_text("plan", encoding="utf-8")
            cfg = Config(git=GitConfig(enabled=True, name="exp bot", email="exp@example.com"))
            with mock.patch("helix.sync.push", return_value=_push_result()) as push:
                rc = cli._cmd_exp_start(_args("feat: first round"), cfg, ws, Remote("gpu-a100"))
            self.assertEqual(rc, 0)
            self.assertTrue(vcs.is_git_repo(ws))
            self.assertTrue(vcs.current_commit(ws))
            self.assertTrue(vcs.is_clean(ws))
            push.assert_called_once()


if __name__ == "__main__":
    unittest.main()
