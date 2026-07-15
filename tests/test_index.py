"""FTS5 index unit tests."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helix import frontmatter, index
from helix.config import Config


class TestQueryEscape(unittest.TestCase):
    def test_multi_token_or(self):
        self.assertEqual(index._escape_fts_query("vision language"), '"vision" OR "language"')

    def test_empty(self):
        self.assertEqual(index._escape_fts_query("   "), '""')

    def test_strips_quotes(self):
        self.assertEqual(index._escape_fts_query('a"b'), '"ab"')


class TestAbstractExtract(unittest.TestCase):
    def test_zh(self):
        body = "# T\n\n## 摘要\n\n这是摘要内容\n\n## 方法\n\nxxx"
        self.assertEqual(index._extract_abstract(body), "这是摘要内容")


class TestBuildAndSearch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.cfg = Config(notes_dir=str(base / "notes"), papers_subdir="papers")
        papers = self.cfg.papers_path / "VLA"
        papers.mkdir(parents=True)
        (papers / "a.md").write_text(
            "---\ntitle: CoT-VLA Reasoning\n---\n## 摘要\n\nchain of thought for robots\n", encoding="utf-8"
        )
        (papers / "b.md").write_text(
            "---\ntitle: Efficient VLA\n---\n## 摘要\n\nefficient model compression\n", encoding="utf-8"
        )
        # attachment file under assets (fulltext.md) should not be indexed as a note
        att = papers / "assets" / "2503.22020"
        att.mkdir(parents=True)
        (att / "fulltext.md").write_text("# 全文附属\n\nchain of thought robot compression\n", encoding="utf-8")
        # put the index db in a temp dir to avoid polluting the repo
        self._patch = mock.patch.object(index, "index_path", lambda cfg: base / ".helix" / "index.db")
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.tmp.cleanup()

    def test_build_and_search(self):
        count, _ = index.build(self.cfg)
        self.assertEqual(count, 2)  # 2 real notes; assets/fulltext.md skipped
        hits = index.search(self.cfg, "chain thought")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["title"], "CoT-VLA Reasoning")

    def test_assets_md_excluded(self):
        index.build(self.cfg)
        # attachment fulltext.md contains "compression" but should not appear as a standalone hit
        hits = index.search(self.cfg, "compression")
        paths = [h["path"] for h in hits]
        self.assertFalse(any("assets" in p for p in paths))

    def test_search_or_matches_both(self):
        index.build(self.cfg)
        hits = index.search(self.cfg, "VLA")
        self.assertEqual(len(hits), 2)

    def test_search_without_index_raises(self):
        with self.assertRaises(RuntimeError):
            index.search(self.cfg, "x")


if __name__ == "__main__":
    unittest.main()
