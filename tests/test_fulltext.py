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
