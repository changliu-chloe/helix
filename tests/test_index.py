"""FTS5 索引单元测试。"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helix import index
from helix.config import Config


class TestQueryEscape(unittest.TestCase):
    def test_multi_token_or(self):
        self.assertEqual(index._escape_fts_query("vision language"), '"vision" OR "language"')

    def test_empty(self):
        self.assertEqual(index._escape_fts_query("   "), '""')

    def test_strips_quotes(self):
        self.assertEqual(index._escape_fts_query('a"b'), '"ab"')


class TestFrontmatter(unittest.TestCase):
    def test_parse(self):
        content = "---\ntitle: X\n---\nbody here"
        fm, body = index._parse_frontmatter(content)
        self.assertEqual(fm["title"], "X")
        self.assertEqual(body.strip(), "body here")

    def test_no_frontmatter(self):
        fm, body = index._parse_frontmatter("just text")
        self.assertEqual(fm, {})
        self.assertEqual(body, "just text")


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
        # assets 下的附属文件（fulltext.md），不应被当成笔记索引
        att = papers / "assets" / "2503.22020"
        att.mkdir(parents=True)
        (att / "fulltext.md").write_text("# 全文附属\n\nchain of thought robot compression\n", encoding="utf-8")
        # 索引 db 放到临时目录，避免污染仓库
        self._patch = mock.patch.object(index, "index_path", lambda cfg: base / ".helix" / "index.db")
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.tmp.cleanup()

    def test_build_and_search(self):
        count, _ = index.build(self.cfg)
        self.assertEqual(count, 2)  # 2 篇真笔记，assets/fulltext.md 被跳过
        hits = index.search(self.cfg, "chain thought")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["title"], "CoT-VLA Reasoning")

    def test_assets_md_excluded(self):
        index.build(self.cfg)
        # 附属 fulltext.md 含 compression，但不应作为独立命中项出现
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
