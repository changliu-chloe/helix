"""config path-anchoring unit tests: relative paths anchored to the config dir, absolute paths preserved, upward lookup."""

import os
import tempfile
import unittest
from pathlib import Path

from helix import config as config_mod
from helix.config import Config, load_config


class TestBaseDirAnchor(unittest.TestCase):
    def test_relative_anchored_under_workspace(self):
        # relative data dirs now resolve under workspace/ (single root), not directly under base_dir
        cfg = Config(notes_dir="notes", experiments_dir="experiments", _path=Path("/proj/config.yaml"))
        self.assertEqual(cfg.base_dir, Path("/proj"))
        self.assertEqual(cfg.workspace_path, Path("/proj/workspace"))
        self.assertEqual(cfg.notes_path, Path("/proj/workspace/notes"))
        self.assertEqual(cfg.experiments_path, Path("/proj/workspace/experiments"))
        # .helix (runtime index/cache) stays at base_dir, NOT under workspace/
        self.assertEqual(cfg.index_path, Path("/proj/.helix/index.db"))

    def test_custom_workspace_dir(self):
        cfg = Config(workspace_dir="ws", notes_dir="notes", _path=Path("/proj/config.yaml"))
        self.assertEqual(cfg.notes_path, Path("/proj/ws/notes"))

    def test_absolute_notes_dir_stays_external(self):
        # an absolute notes_dir (Obsidian vault) is NOT pulled under workspace/
        cfg = Config(notes_dir="/data/vault", _path=Path("/proj/config.yaml"))
        self.assertEqual(cfg.notes_path, Path("/data/vault"))

    def test_expanduser(self):
        cfg = Config(notes_dir="~/vault", _path=Path("/proj/config.yaml"))
        self.assertEqual(cfg.notes_path, Path.home() / "vault")


class TestFindConfigUpward(unittest.TestCase):
    def test_finds_config_in_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "config.yaml").write_text("language: zh\n", encoding="utf-8")
            sub = root / "a" / "b"
            sub.mkdir(parents=True)
            old = Path.cwd()
            try:
                os.chdir(sub)
                found = config_mod.find_config()
                self.assertEqual(found.resolve(), root / "config.yaml")
            finally:
                os.chdir(old)

    def test_explicit_path_wins(self):
        self.assertEqual(config_mod.find_config("/x/config.yaml"), Path("/x/config.yaml"))


class TestLoadConfigSetsPath(unittest.TestCase):
    def test_loaded_config_anchors_to_its_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "config.yaml").write_text("notes_dir: notes\n", encoding="utf-8")
            cfg = load_config(str(root / "config.yaml"))
            self.assertEqual(cfg.notes_path, root / "workspace" / "notes")


class TestGitConfig(unittest.TestCase):
    def test_git_defaults_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "config.yaml").write_text("language: zh\n", encoding="utf-8")
            cfg = load_config(str(root / "config.yaml"))
            self.assertFalse(cfg.git.enabled)
            self.assertEqual(cfg.git.name, "")
            self.assertEqual(cfg.git.email, "")

    def test_git_config_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "config.yaml").write_text(
                "git:\n"
                "  enabled: true\n"
                "  name: exp bot\n"
                "  email: exp@example.com\n",
                encoding="utf-8",
            )
            cfg = load_config(str(root / "config.yaml"))
            self.assertTrue(cfg.git.enabled)
            self.assertEqual(cfg.git.name, "exp bot")
            self.assertEqual(cfg.git.email, "exp@example.com")

    def test_quoted_false_stays_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "config.yaml").write_text('git:\n  enabled: "false"\n', encoding="utf-8")
            cfg = load_config(str(root / "config.yaml"))
            self.assertFalse(cfg.git.enabled)


if __name__ == "__main__":
    unittest.main()
