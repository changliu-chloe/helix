"""Review skeleton + review-score frontmatter unit tests."""

import tempfile
import unittest
from pathlib import Path

from helix import notes, review
from helix.config import Config


class TestReviewPath(unittest.TestCase):
    def test_flat_under_review_subdir(self):
        cfg = Config(notes_dir="notes", review_subdir="reviews", _path=Path("/proj/config.yaml"))
        path = review.review_path_for("视觉语言动作模型综述", cfg)
        self.assertTrue(str(path).endswith("notes/reviews/视觉语言动作模型综述.md"))
        self.assertTrue(path.is_absolute())

    def test_name_override(self):
        cfg = Config(notes_dir="notes", _path=Path("/proj/config.yaml"))
        path = review.review_path_for("A Very Long Topic Description", cfg, name="VLA-survey")
        self.assertTrue(str(path).endswith("reviews/VLA-survey.md"))


class TestBuildSkeleton(unittest.TestCase):
    def test_zh_skeleton_has_sections(self):
        s = review.build_review_skeleton("扩散策略", "zh")
        self.assertIn("type: review", s)
        self.assertIn("# 文献综述：扩散策略", s)
        self.assertIn("## 逐篇要点", s)
        self.assertIn("| 论文 | 相关性 | 创新性 | 可靠性 |", s)

    def test_en_skeleton(self):
        s = review.build_review_skeleton("Diffusion Policy", "en")
        self.assertIn("# Literature Review: Diffusion Policy", s)
        self.assertIn("| Paper | Relevance | Novelty | Reliability |", s)


class TestWriteReview(unittest.TestCase):
    def test_write_verifies_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(notes_dir=str(Path(tmp) / "notes"), review_subdir="reviews")
            path, created = review.write_review("VLA 综述", cfg)
            self.assertTrue(created and path.exists() and path.stat().st_size > 0)
            # second write does not overwrite
            _, created2 = review.write_review("VLA 综述", cfg)
            self.assertFalse(created2)
            # overwrite=True re-creates
            _, created3 = review.write_review("VLA 综述", cfg, overwrite=True)
            self.assertTrue(created3)


class TestSetReviewScores(unittest.TestCase):
    def _note(self, tmp: str) -> Path:
        p = Path(tmp) / "note.md"
        p.write_text(
            "---\ntitle: T\narxiv_id: '1'\ntags:\n- helix\nscore: 7.5\n---\n\n# T\n\n## 一句话总结\n\nbody.\n",
            encoding="utf-8",
        )
        return p

    def test_insert_preserves_body_and_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._note(tmp)
            scores = notes.set_review_scores(
                p, relevance=8, novelty=7, reliability=6, reviewer_model="gpt-5.6-sol", note="ok"
            )
            self.assertEqual(scores["relevance"], 8.0)
            content = p.read_text(encoding="utf-8")
            self.assertIn("review_scores:", content)
            self.assertIn("body.", content)          # body preserved
            self.assertIn("score: 7.5", content)     # other frontmatter keys preserved
            self.assertIn("title: T", content)

    def test_rescore_idempotent_update_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._note(tmp)
            notes.set_review_scores(p, relevance=8, novelty=7, reliability=6)
            notes.set_review_scores(p, novelty=9)  # update only novelty
            fm = __import__("helix.frontmatter", fromlist=["meta"]).meta(p.read_text(encoding="utf-8"))
            rs = fm["review_scores"]
            self.assertEqual(rs["novelty"], 9.0)
            self.assertEqual(rs["relevance"], 8.0)  # unchanged
            # only one review_scores block
            self.assertEqual(p.read_text(encoding="utf-8").count("review_scores:"), 1)

    def test_missing_frontmatter_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "plain.md"
            p.write_text("# no frontmatter\n", encoding="utf-8")
            with self.assertRaises(OSError):
                notes.set_review_scores(p, relevance=5)


class TestConfigReviewDefaults(unittest.TestCase):
    def test_defaults(self):
        cfg = Config()
        self.assertEqual(cfg.review_subdir, "reviews")
        self.assertEqual(cfg.reviewer_model, "gpt-5.6-sol")
        self.assertEqual(cfg.review_funnel_top_n, 10)

    def test_old_config_gets_defaults(self):
        from helix.config import load_config

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "config.yaml").write_text("language: zh\n", encoding="utf-8")  # no review fields
            cfg = load_config(str(root / "config.yaml"))
            self.assertEqual(cfg.review_subdir, "reviews")
            self.assertEqual(cfg.reviewer_model, "gpt-5.6-sol")
            self.assertEqual(cfg.review_funnel_top_n, 10)
            self.assertEqual(cfg.review_path, root / "workspace" / "notes" / "reviews")


if __name__ == "__main__":
    unittest.main()
