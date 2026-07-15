"""Note generation and wikilink unit tests."""

import unittest

from helix import notes
from helix.config import Config, Domain
from helix.models import Paper


class TestFilename(unittest.TestCase):
    def test_author_coined_name_before_colon(self):
        # Short name before the colon is kept as the filename
        self.assertEqual(notes.title_to_filename("CoT-VLA: Visual Chain-of-Thought Reasoning"), "CoT-VLA")

    def test_descriptive_title_first_words(self):
        # No author-coined short name -> first few words, kept short
        self.assertEqual(
            notes.title_to_filename("Efficient Memory Management for Large Language Model Serving"),
            "Efficient_Memory_Management_for",
        )

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
        p = Paper(paper_id="1", title="CoT-VLA: Visual Reasoning", matched_domains=["VLA模型"])
        path = notes.note_path_for(p, cfg)
        # path anchored to base_dir (absolute); only verify the relative structure
        self.assertTrue(str(path).endswith("notes/papers/VLA模型/CoT-VLA.md"))
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
            self.assertIn("新方向X", str(path))  # archived under the specified domain
            # writing again does not overwrite
            path2, created2 = notes.write_note(p, cfg)
            self.assertFalse(created2)
            self.assertEqual(path, path2)

    def test_absolute_notes_dir_preserved(self):
        # a user-configured absolute path (e.g. an external Obsidian vault) should be preserved as-is
        cfg = Config(notes_dir="/tmp/my_vault", papers_subdir="papers")
        p = Paper(paper_id="1", title="x", matched_domains=["D"])
        self.assertTrue(str(notes.note_path_for(p, cfg)).startswith("/tmp/my_vault/papers/D/"))

    def test_explicit_name_override(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(notes_dir=str(Path(tmp) / "notes"), papers_subdir="papers")
            p = Paper(paper_id="1", title="Some Very Long Descriptive Title", matched_domains=["D"])
            path, created = notes.write_note(p, cfg, name="MyMethod")
            self.assertTrue(created)
            self.assertTrue(str(path).endswith("papers/D/MyMethod.md"))

    def test_collision_different_paper_disambiguated(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(notes_dir=str(Path(tmp) / "notes"), papers_subdir="papers")
            # Two different papers whose short names both resolve to "Efficient_X_for_Y"
            p1 = Paper(paper_id="2401.00001", title="Efficient X for Y", matched_domains=["D"])
            p2 = Paper(paper_id="2402.00002", title="Efficient X for Y (v2 different work)", matched_domains=["D"])
            path1, _ = notes.write_note(p1, cfg)
            path2, _ = notes.write_note(p2, cfg)
            # second paper must not reuse the first's file; id appended to disambiguate
            self.assertNotEqual(path1, path2)
            self.assertIn("2402.00002", path2.name)


class TestRenameNote(unittest.TestCase):
    def _cfg_with_notes(self, tmp):
        from pathlib import Path

        cfg = Config(notes_dir=str(Path(tmp) / "notes"), papers_subdir="papers")
        return cfg

    def test_rename_updates_inbound_wikilinks(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._cfg_with_notes(tmp)
            d = cfg.papers_path / "VLA"
            d.mkdir(parents=True)
            old = d / "Efficient_Memory_Management_for.md"
            old.write_text("---\ntitle: T\narxiv_id: '1'\n---\n# T\n", encoding="utf-8")
            # another note links to it
            other = d / "Other.md"
            other.write_text("见 [[papers/VLA/Efficient_Memory_Management_for.md|该工作]] 一文\n", encoding="utf-8")

            new_path, updated = notes.rename_note(old, "PagedAttention", cfg)
            self.assertTrue(new_path.name == "PagedAttention.md")
            self.assertFalse(old.exists())
            self.assertEqual(updated, 1)
            self.assertIn("papers/VLA/PagedAttention.md", other.read_text(encoding="utf-8"))

    def test_rename_refuses_clobber(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._cfg_with_notes(tmp)
            d = cfg.papers_path / "VLA"
            d.mkdir(parents=True)
            (d / "A.md").write_text("---\ntitle: A\n---\n", encoding="utf-8")
            (d / "B.md").write_text("---\ntitle: B\n---\n", encoding="utf-8")
            with self.assertRaises(OSError):
                notes.rename_note(d / "A.md", "B", cfg)


class TestNameOverride(unittest.TestCase):
    def test_explicit_name_wins(self):
        cfg = Config(notes_dir="notes", papers_subdir="papers")
        p = Paper(paper_id="1", title="Some Long Descriptive Title Here", matched_domains=["D"])
        path = notes.note_path_for(p, cfg, name="MyMethod")
        self.assertTrue(str(path).endswith("papers/D/MyMethod.md"))


class TestCollision(unittest.TestCase):
    def test_different_paper_same_shortname_disambiguated(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(notes_dir=str(Path(tmp) / "notes"), papers_subdir="papers")
            # Two different papers whose titles collapse to the same short name
            p1 = Paper(paper_id="2503.00001", title="Mamba: A Sequence Model", matched_domains=["SSM"])
            p2 = Paper(paper_id="2503.00002", title="Mamba: Another Take", matched_domains=["SSM"])
            path1, _ = notes.write_note(p1, cfg)
            self.assertTrue(str(path1).endswith("papers/SSM/Mamba.md"))
            # Second paper collides -> id appended, distinct file, first note untouched
            path2 = notes.note_path_for(p2, cfg)
            self.assertNotEqual(path1, path2)
            self.assertIn("2503.00002", path2.name)

    def test_same_paper_no_disambiguation(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(notes_dir=str(Path(tmp) / "notes"), papers_subdir="papers")
            p = Paper(paper_id="2503.00001", title="Mamba: A Sequence Model", matched_domains=["SSM"])
            path1, _ = notes.write_note(p, cfg)
            # Same paper again -> same path, no id suffix
            self.assertEqual(notes.note_path_for(p, cfg), path1)


class TestRename(unittest.TestCase):
    def test_rename_updates_file_and_wikilinks(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(notes_dir=str(Path(tmp) / "notes"), papers_subdir="papers")
            papers = cfg.papers_path / "VLA"
            papers.mkdir(parents=True)
            old = papers / "Efficient_Memory_Management_for.md"
            old.write_text("---\ntitle: Efficient Memory Management\narxiv_id: '1'\n---\n# x\n", encoding="utf-8")
            # another note links to the old one
            other = papers / "Other.md"
            other.write_text("---\ntitle: Other\n---\n见 [[papers/VLA/Efficient_Memory_Management_for.md|PagedAttn]]\n", encoding="utf-8")

            new_path, updated = notes.rename_note(old, "PagedAttention", cfg)
            self.assertTrue(new_path.exists())
            self.assertFalse(old.exists())
            self.assertTrue(str(new_path).endswith("papers/VLA/PagedAttention.md"))
            self.assertEqual(updated, 1)
            self.assertIn("papers/VLA/PagedAttention.md", other.read_text(encoding="utf-8"))

    def test_rename_refuses_clobber(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(notes_dir=str(Path(tmp) / "notes"), papers_subdir="papers")
            papers = cfg.papers_path / "VLA"
            papers.mkdir(parents=True)
            a = papers / "A.md"
            a.write_text("---\ntitle: A\n---\n", encoding="utf-8")
            b = papers / "B.md"
            b.write_text("---\ntitle: B\n---\n", encoding="utf-8")
            with self.assertRaises(OSError):
                notes.rename_note(a, "B", cfg)  # B.md already exists
            self.assertTrue(a.exists())  # original preserved on refusal


class TestLinkKeywords(unittest.TestCase):
    def _index(self):
        return {"cot-vla": ["papers/VLA/CoT-VLA.md"]}

    def test_basic_link(self):
        out = notes.link_keywords_in_text("受 CoT-VLA 启发", self._index())
        self.assertEqual(out, "受 [[papers/VLA/CoT-VLA.md|CoT-VLA]] 启发")

    def test_shared_keyword_skipped(self):
        # a keyword pointing to multiple papers -> too broad, don't link
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
