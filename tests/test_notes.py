"""笔记生成与 wikilink 单元测试。"""

import unittest

from arxo import notes
from arxo.config import Config, Domain
from arxo.models import Paper


class TestFilename(unittest.TestCase):
    def test_title_sanitized(self):
        self.assertEqual(notes.title_to_filename("CoT-VLA: Reasoning"), "CoT-VLA_Reasoning")

    def test_empty_title(self):
        self.assertEqual(notes.title_to_filename(""), "untitled")


class TestTitleKeywords(unittest.TestCase):
    def test_acronym(self):
        kws = notes.extract_title_keywords("BLIP: Bootstrapping Language-Image Pre-training")
        self.assertIn("BLIP", kws)

    def test_hyphenated_term(self):
        kws = notes.extract_title_keywords("A Study of Vision-Language Models")
        self.assertIn("Vision-Language", kws)


class TestNotePath(unittest.TestCase):
    def test_domain_subdir(self):
        cfg = Config(notes_dir="notes", papers_subdir="papers")
        p = Paper(paper_id="1", title="CoT-VLA: x", matched_domains=["VLA模型"])
        path = notes.note_path_for(p, cfg)
        # 路径锚定 base_dir（绝对），只验证相对结构
        self.assertTrue(str(path).endswith("notes/papers/VLA模型/CoT-VLA_x.md"))
        self.assertTrue(path.is_absolute())

    def test_uncategorized(self):
        cfg = Config(notes_dir="notes", papers_subdir="papers")
        p = Paper(paper_id="1", title="x")
        self.assertIn("未分类", str(notes.note_path_for(p, cfg)))


class TestWriteNote(unittest.TestCase):
    def test_write_verifies_landed_and_no_overwrite(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(notes_dir=str(Path(tmp) / "notes"), papers_subdir="papers")
            p = Paper(paper_id="1", title="Paper One", abstract="abc", matched_domains=["新方向X"])
            path, created = notes.write_note(p, cfg)
            self.assertTrue(created)
            self.assertTrue(path.exists() and path.stat().st_size > 0)
            self.assertIn("新方向X", str(path))  # 用指定方向归档
            # 再写不覆盖
            path2, created2 = notes.write_note(p, cfg)
            self.assertFalse(created2)
            self.assertEqual(path, path2)

    def test_absolute_notes_dir_preserved(self):
        # 用户配绝对路径（如外部 Obsidian vault）应原样保留
        cfg = Config(notes_dir="/tmp/my_vault", papers_subdir="papers")
        p = Paper(paper_id="1", title="x", matched_domains=["D"])
        self.assertTrue(str(notes.note_path_for(p, cfg)).startswith("/tmp/my_vault/papers/D/"))


class TestLinkKeywords(unittest.TestCase):
    def _index(self):
        return {"cot-vla": ["papers/VLA/CoT-VLA.md"]}

    def test_basic_link(self):
        out = notes.link_keywords_in_text("受 CoT-VLA 启发", self._index())
        self.assertEqual(out, "受 [[papers/VLA/CoT-VLA.md|CoT-VLA]] 启发")

    def test_shared_keyword_skipped(self):
        # 同一关键词指向多篇论文 -> 太泛，不链接
        idx = {"vla": ["a.md", "b.md"]}
        out = notes.link_keywords_in_text("about VLA models", idx)
        self.assertEqual(out, "about VLA models")

    def test_already_linked_not_doubled(self):
        text = "见 [[papers/VLA/CoT-VLA.md|CoT-VLA]] 一文"
        out = notes.link_keywords_in_text(text, self._index())
        self.assertEqual(out, text)

    def test_common_word_not_linked(self):
        idx = {"model": ["a.md"]}
        out = notes.link_keywords_in_text("a good model here", idx)
        self.assertEqual(out, "a good model here")


if __name__ == "__main__":
    unittest.main()
