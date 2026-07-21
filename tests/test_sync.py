"""Transport (helix exp push/pull) unit tests: scp command shape, safety guards, remote-path mapping.

scp is never invoked here -- we patch helix.sync._run and assert on the argv it would run, so the
guards (push whitelist by enumeration, pull scoped to results/, RESULTS_LAYOUT.md forced, no delete)
and the first-use remote_path confirmation are verified deterministically.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from helix import sync
from helix.config import Config, Remote


def _mk_workspace(root: Path, remote: str, push, pull, remote_path="", agent_view=None) -> Path:
    ws = root / "experiments" / "domX" / "paperY"
    ws.mkdir(parents=True)
    payload = {"remote": remote, "remote_path": remote_path, "push": push, "pull": pull}
    if agent_view is not None:
        payload["agent_view"] = agent_view
    (ws / "sync.yaml").write_text(
        yaml.safe_dump(payload, allow_unicode=True),
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

    def test_plaintext_password_detected(self):
        self.assertTrue(sync._has_plaintext_password("user:secret@host"))
        self.assertFalse(sync._has_plaintext_password("gpu-a100"))

    def test_scp_base_recursive_no_delete(self):
        base = sync._scp_base(Remote("m", host="h"))
        self.assertEqual(base[0], "scp")
        self.assertIn("-r", base)
        self.assertNotIn("--delete", base)  # scp never mirror-deletes

    def test_scp_base_adds_identity(self):
        base = sync._scp_base(Remote("m", host="h", ssh_key="/k.pem"))
        self.assertIn("-i", base)
        self.assertIn("/k.pem", base)

    def test_expand_push_items_maps_globs_to_toplevel(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            (ws / "plan.md").write_text("x", encoding="utf-8")
            (ws / "scripts").mkdir()
            items, warns = sync._expand_push_items(ws, ["plan.md", "scripts/**", "configs/**"])
            self.assertIn("plan.md", items)
            self.assertIn("scripts", items)         # dir/** -> dir
            self.assertNotIn("configs", items)      # missing -> skipped
            self.assertTrue(any("configs" in w for w in warns))


class TestRemotePathMapping(unittest.TestCase):
    def test_default_remote_path(self):
        r = Remote("m", host="h", remote_repro_root="/data/exp")
        p = sync.default_remote_path(r, Path("/local/experiments/domX/paperY"))
        self.assertEqual(p, "/data/exp/domX/paperY")

    def test_resolve_empty_is_none(self):
        self.assertIsNone(sync.resolve_remote_path(sync.SyncSpec(remote="m", remote_path="")))

    def test_resolve_nonempty_returns_it(self):
        self.assertEqual(sync.resolve_remote_path(sync.SyncSpec(remote_path="/data/x")), "/data/x")

    def test_set_remote_path_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            ws = _mk_workspace(Path(d), "gpu", ["plan.md"], ["results/metrics/**"])
            sync.set_remote_path(ws, "/data/confirmed/exp1")
            spec = sync.load_sync_spec(ws)
            self.assertEqual(spec.remote_path, "/data/confirmed/exp1")
            self.assertEqual(spec.remote, "gpu")           # other fields preserved
            self.assertEqual(spec.push, ["plan.md"])

    def test_agent_view_is_loaded_and_preserved(self):
        agent_view = {
            "models": {"base_model": "/models/qwen"},
            "datasets": {"raw": "/data/ds"},
            "runtime": {"env": "uv"},
        }
        with tempfile.TemporaryDirectory() as d:
            ws = _mk_workspace(
                Path(d), "gpu", ["plan.md"], ["results/metrics/**"],
                agent_view=agent_view,
            )
            spec = sync.load_sync_spec(ws)
            self.assertEqual(spec.agent_view["models"]["base_model"], "/models/qwen")
            sync.set_remote_path(ws, "/data/confirmed/exp1")
            updated = sync.load_sync_spec(ws)
            self.assertEqual(updated.agent_view, agent_view)

    def test_invalid_agent_view_falls_back_to_empty(self):
        with tempfile.TemporaryDirectory() as d:
            ws = _mk_workspace(
                Path(d), "gpu", ["plan.md"], ["results/metrics/**"],
                agent_view=["bad"],
            )
            spec = sync.load_sync_spec(ws)
            self.assertEqual(spec.agent_view, {})


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

    def test_push_unconfirmed_raises_remote_path_unset(self):
        ws = _mk_workspace(self.root, "gpu-a100", ["plan.md"], ["results/metrics/**"])  # remote_path=""
        with self.assertRaises(sync.RemotePathUnset) as ctx:
            sync.push(self.cfg, ws, dry_run=True)
        self.assertEqual(ctx.exception.default, "/data/exp/domX/paperY")  # carries suggestion

    def test_push_scp_per_item_to_confirmed_path(self):
        ws = _mk_workspace(self.root, "gpu-a100", ["plan.md"], ["results/metrics/**"],
                           remote_path="/data/exp/domX/paperY")
        with mock.patch.object(sync, "_ensure_remote_dir", return_value=0), \
             mock.patch.object(sync, "_run", return_value=0) as run:
            res = sync.push(self.cfg, ws, dry_run=False)
        all_cmds = [c[0][0] for c in run.call_args_list]
        # one scp per declared item; plan.md + RESULTS_LAYOUT.md both sent
        sent = " | ".join(" ".join(c) for c in all_cmds)
        self.assertIn("plan.md", sent)
        self.assertIn("RESULTS_LAYOUT.md", sent)               # contract file forced
        for c in all_cmds:
            self.assertEqual(c[0], "scp")
            self.assertNotIn("--delete", c)
            self.assertTrue(c[-1].endswith("gpu-a100:/data/exp/domX/paperY/"))
        self.assertEqual(res.direction, "push")

    def test_push_dry_run_does_not_run_scp_or_mkdir(self):
        ws = _mk_workspace(self.root, "gpu-a100", ["plan.md"], ["results/metrics/**"],
                           remote_path="/data/exp/domX/paperY")
        with mock.patch.object(sync, "_ensure_remote_dir") as mk, \
             mock.patch.object(sync, "_run") as run:
            res = sync.push(self.cfg, ws, dry_run=True)
        mk.assert_not_called()
        run.assert_not_called()                                 # simulated -- nothing executed
        self.assertTrue(res.cmds)                               # but the planned cmds are reported

    def test_pull_only_fetches_result_subdirs(self):
        ws = _mk_workspace(self.root, "gpu-a100", ["plan.md"], ["results/metrics/**"],
                           remote_path="/data/exp/domX/paperY")
        with mock.patch.object(sync, "_run", return_value=0) as run:
            sync.pull(self.cfg, ws, dry_run=False)
        srcs = [c[0][0][-2] for c in run.call_args_list]        # scp source arg of each call
        # every source is one of the three result subdirs on the remote; never a hand-written doc
        self.assertTrue(all("/results/" in s for s in srcs))
        joined = " ".join(srcs)
        self.assertIn("results/metrics", joined)
        self.assertIn("results/plots", joined)
        self.assertIn("results/tables", joined)
        self.assertNotIn("plan.md", joined)
        self.assertNotIn("index.md", joined)
        self.assertTrue((ws / "results" / "metrics").is_dir())  # local landing spot created

    def test_pull_unconfirmed_raises(self):
        ws = _mk_workspace(self.root, "gpu-a100", ["plan.md"], ["results/metrics/**"])
        with self.assertRaises(sync.RemotePathUnset):
            sync.pull(self.cfg, ws, dry_run=True)

    def test_push_and_run_resolve_same_path(self):
        # consistency: the path push uses == the path exp run would cd into (single source of truth)
        ws = _mk_workspace(self.root, "gpu-a100", ["plan.md"], ["results/metrics/**"],
                           remote_path="/data/exp/domX/paperY")
        spec = sync.load_sync_spec(ws)
        remote = self.cfg.find_remote("gpu-a100")
        push_path = sync.require_remote_path(remote, ws, spec)
        run_path = sync.resolve_remote_path(spec)               # what CLI passes to ssh.run_in_tmux
        self.assertEqual(push_path, run_path)

    def test_unknown_remote_raises(self):
        ws = _mk_workspace(self.root, "nonexistent", ["plan.md"], ["results/metrics/**"],
                           remote_path="/data/x")
        with self.assertRaises(ValueError):
            sync.push(self.cfg, ws, dry_run=True)

    def test_empty_remote_raises(self):
        ws = _mk_workspace(self.root, "", ["plan.md"], ["results/metrics/**"], remote_path="/data/x")
        with self.assertRaises(ValueError):
            sync.push(self.cfg, ws, dry_run=True)


if __name__ == "__main__":
    unittest.main()
