"""config 路径锚定单元测试：相对路径锚定 config 目录、绝对路径原样、向上查找。"""

import os
import tempfile
import unittest
from pathlib import Path

from arxo import config as config_mod
from arxo.config import Config, load_config


class TestBaseDirAnchor(unittest.TestCase):
    def test_relative_anchored_to_config_dir(self):
        cfg = Config(notes_dir="notes", _path=Path("/proj/config.yaml"))
        self.assertEqual(cfg.base_dir, Path("/proj"))
        self.assertEqual(cfg.notes_path, Path("/proj/notes"))
        self.assertEqual(cfg.index_path, Path("/proj/.arxo/index.db"))

    def test_absolute_notes_dir_preserved(self):
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
            self.assertEqual(cfg.notes_path, root / "notes")


if __name__ == "__main__":
    unittest.main()
