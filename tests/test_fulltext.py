"""全文抓取：源码抽图 + MinerU 封装单元测试（不打真实网络）。"""

import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arxo.sources import fulltext
from arxo.config import Config


class TestCollectFigures(unittest.TestCase):
    def test_finds_figure_dir_case_insensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Figure").mkdir()
            (root / "Figure" / "teaser.pdf").write_bytes(b"x")
            (root / "Figure" / "method.png").write_bytes(b"y")
            found = fulltext._collect_figures(root)
            names = {p.name for p in found}
            self.assertEqual(names, {"teaser.pdf", "method.png"})

    def test_fallback_to_root_bitmaps_filters_logo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "diagram.png").write_bytes(b"x")
            (root / "logo.png").write_bytes(b"y")  # 应过滤
            found = fulltext._collect_figures(root)
            names = {p.name for p in found}
            self.assertIn("diagram.png", names)
            self.assertNotIn("logo.png", names)


class TestSafeExtract(unittest.TestCase):
    def _make_tar(self, names_and_data):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for name, data in names_and_data:
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        buf.seek(0)
        return buf

    def test_skips_path_traversal(self):
        tar_buf = self._make_tar([("figure/ok.png", b"x"), ("../evil.png", b"bad"), ("/abs.png", b"bad")])
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            with tarfile.open(fileobj=tar_buf, mode="r:gz") as tar:
                fulltext._safe_extract(tar, dest)
            extracted = {p.name for p in dest.rglob("*") if p.is_file()}
            self.assertIn("ok.png", extracted)
            self.assertNotIn("evil.png", extracted)
            self.assertNotIn("abs.png", extracted)


class TestMineruGating(unittest.TestCase):
    def test_no_key_raises(self):
        with self.assertRaises(RuntimeError) as ctx:
            fulltext.mineru_parse(Path("x.pdf"), api_key="", out_dir=Path("."))
        self.assertIn("api_key", str(ctx.exception))


class TestMineruCliLocate(unittest.TestCase):
    def test_prefers_sibling_of_python(self):
        # CLI 与当前解释器同目录时应优先返回该路径（不依赖 PATH）
        from arxo.sources import mineru_client

        with tempfile.TemporaryDirectory() as tmp:
            fake_bin = Path(tmp) / "bin"
            fake_bin.mkdir()
            cli = fake_bin / mineru_client.MINERU_CLI
            cli.write_text("#!/bin/sh\n")
            with mock.patch.object(mineru_client.sys, "executable", str(fake_bin / "python")):
                self.assertEqual(mineru_client._find_cli(), str(cli))

    def test_falls_back_to_path(self):
        from arxo.sources import mineru_client

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(mineru_client.sys, "executable", str(Path(tmp) / "python")), \
                 mock.patch.object(mineru_client.shutil, "which", return_value="/usr/bin/mineru-open-api"):
                self.assertEqual(mineru_client._find_cli(), "/usr/bin/mineru-open-api")


class TestAssetsPath(unittest.TestCase):
    def test_assets_path_structure(self):
        cfg = Config(notes_dir="notes", papers_subdir="papers", _path=Path("/proj/config.yaml"))
        p = cfg.assets_path("VLA模型", "2503.22020")
        self.assertEqual(str(p), "/proj/notes/papers/VLA模型/assets/2503.22020")

    def test_mineru_key_env_fallback(self):
        cfg = Config(mineru_api_key="")
        with mock.patch.dict("os.environ", {"MINERU_API_KEY": "envkey"}):
            self.assertEqual(cfg.mineru_key, "envkey")
        cfg2 = Config(mineru_api_key="cfgkey")
        with mock.patch.dict("os.environ", {"MINERU_API_KEY": "envkey"}):
            self.assertEqual(cfg2.mineru_key, "cfgkey")  # config 优先


if __name__ == "__main__":
    unittest.main()
