"""Transport (helix exp push/pull) unit tests: sync.yaml parsing, safety guards, rsync command shape.

rsync itself is never invoked here -- we patch helix.sync._run and assert on the command it would run,
so the guards (no --delete, pull scoped to results/, RESULTS_LAYOUT.md forced on push) are verified deterministically.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helix import sync
from helix.config import Config, Remote


def _mk_workspace(root: Path, remote: str, push, pull) -> Path:
    ws = root / "experiments" / "domX" / "paperY"
    ws.mkdir(parents=True)
    import yaml
    (ws / "sync.yaml").write_text(
        yaml.safe_dump({"remote": remote, "push": push, "pull": pull}, allow_unicode=True),
        encoding="utf-8",
    )
    (ws / "RESULTS_LAYOUT.md").write_text("rules", encoding="utf-8")
    (ws / "plan.md").write_text("plan", encoding="utf-8")
    return ws


class TestSyncSpec(unittest.TestCase):
    def test_missing_sync_yaml_raises(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d) / "ws"
            ws.mkdir()
            with self.assertRaises(FileNotFoundError):
                sync.load_sync_spec(ws)

    def test_guard_pull_drops_non_results_paths(self):
        # only results/{metrics,plots,tables}/ patterns survive -- never pull hand-written docs
        kept = sync._guard_pull_patterns(
            ["results/metrics/**", "plan.md", "results/index.md", "results/plots/a.png", "../etc/passwd"]
        )
        self.assertIn("results/metrics/**", kept)
        self.assertIn("results/plots/a.png", kept)
        self.assertNotIn("plan.md", kept)
        self.assertNotIn("results/index.md", kept)   # hand-written, protected
        self.assertNotIn("../etc/passwd", kept)

    def test_no_delete_flag_ever(self):
        base = sync._rsync_base(dry_run=False)
        self.assertNotIn("--delete", base)
        self.assertIn("-azh", base)

    def test_dry_run_maps_to_rsync_flag(self):
        self.assertIn("--dry-run", sync._rsync_base(dry_run=True))

    def test_plaintext_password_detected(self):
        self.assertTrue(sync._has_plaintext_password("user:secret@host"))
        self.assertFalse(sync._has_plaintext_password("gpu-a100"))


class TestPushPull(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = Config(
            _path=self.root / "config.yaml",
            remotes=[Remote("gpu-a100", host="gpu-a100", remote_repro_root="/data/exp")],
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_push_forces_results_layout_and_targets_remote_dir(self):
        ws = _mk_workspace(self.root, "gpu-a100", ["plan.md"], ["results/metrics/**"])
        with mock.patch.object(sync, "_run", return_value=0) as run:
            res = sync.push(self.cfg, ws, dry_run=True)
        cmd = run.call_args[0][0]
        self.assertIn("RESULTS_LAYOUT.md", cmd)                       # contract file forced
        self.assertNotIn("--delete", cmd)
        self.assertTrue(cmd[-1].endswith("gpu-a100:/data/exp/domX/paperY/"))
        self.assertEqual(res.direction, "push")

    def test_pull_creates_result_dirs_and_pulls_from_remote(self):
        ws = _mk_workspace(self.root, "gpu-a100", ["plan.md"], ["results/metrics/**", "plan.md"])
        with mock.patch.object(sync, "_run", return_value=0) as run:
            sync.pull(self.cfg, ws, dry_run=True)
        cmd = run.call_args[0][0]
        # source is the remote dir, dest is the local workspace
        self.assertTrue(cmd[-2].endswith("gpu-a100:/data/exp/domX/paperY/"))
        self.assertTrue(cmd[-1].endswith("paperY/") or cmd[-1].endswith("paperY"))
        # local result dirs were created as landing spots
        self.assertTrue((ws / "results" / "metrics").is_dir())

    def test_unknown_remote_raises(self):
        ws = _mk_workspace(self.root, "nonexistent", ["plan.md"], ["results/metrics/**"])
        with self.assertRaises(ValueError):
            sync.push(self.cfg, ws, dry_run=True)

    def test_empty_remote_raises(self):
        ws = _mk_workspace(self.root, "", ["plan.md"], ["results/metrics/**"])
        with self.assertRaises(ValueError):
            sync.push(self.cfg, ws, dry_run=True)


if __name__ == "__main__":
    unittest.main()
