"""打分逻辑单元测试。"""

import unittest
from datetime import datetime, timedelta

from helix.config import Config, Domain
from helix.models import Paper
from helix import score


def _cfg():
    return Config(
        excluded_keywords=["workshop"],
        score_weights=score.DEFAULT_WEIGHTS,
        domains=[Domain(name="VLA", keywords=["VLA", "vision language action"], arxiv_categories=["cs.RO"], priority=5)],
    )


class TestRelevance(unittest.TestCase):
    def test_title_keyword_and_category(self):
        p = Paper(paper_id="1", title="A VLA model", abstract="robotics", categories=["cs.RO"])
        rel, domain, matched = score.relevance_score(p, _cfg().domains, [])
        # 标题命中 VLA(0.5) + 分类 cs.RO(1.0)
        self.assertAlmostEqual(rel, 1.5)
        self.assertEqual(domain, "VLA")
        self.assertIn("VLA", matched)
        self.assertIn("cs.RO", matched)

    def test_excluded_keyword_zeros_out(self):
        p = Paper(paper_id="1", title="VLA workshop paper", abstract="x", categories=["cs.RO"])
        rel, domain, matched = score.relevance_score(p, _cfg().domains, ["workshop"])
        self.assertEqual(rel, 0.0)
        self.assertIsNone(domain)


class TestRecency(unittest.TestCase):
    def test_recent_paper_scores_high(self):
        recent = (datetime.now() - timedelta(days=5)).isoformat()
        self.assertEqual(score.recency_score(recent), 3.0)

    def test_old_paper_scores_zero(self):
        old = (datetime.now() - timedelta(days=400)).isoformat()
        self.assertEqual(score.recency_score(old), 0.0)

    def test_empty_date(self):
        self.assertEqual(score.recency_score(""), 0.0)


class TestPopularity(unittest.TestCase):
    def test_citation_normalized(self):
        p = Paper(paper_id="1", title="x", citation_count=100)
        self.assertEqual(score.popularity_score(p), score.SCORE_MAX)

    def test_new_paper_potential_heat(self):
        p = Paper(paper_id="1", title="x", published=(datetime.now() - timedelta(days=3)).isoformat())
        self.assertEqual(score.popularity_score(p), 2.0)


class TestQuality(unittest.TestCase):
    def test_strong_innovation(self):
        self.assertGreater(score.quality_score("We achieve state-of-the-art, outperform baselines"), 1.0)

    def test_empty(self):
        self.assertEqual(score.quality_score(""), 0.0)


class TestFinalAndPipeline(unittest.TestCase):
    def test_final_score_range(self):
        s = score.final_score(3.0, 3.0, 3.0, 3.0, score.DEFAULT_WEIGHTS)
        self.assertEqual(s, 10.0)

    def test_score_papers_filters_and_sorts(self):
        cfg = _cfg()
        papers = [
            Paper(paper_id="a", title="Unrelated topic", abstract="nothing", categories=["cs.CV"]),
            Paper(paper_id="b", title="VLA model", abstract="novel framework achieves sota", categories=["cs.RO"],
                  published=(datetime.now() - timedelta(days=2)).isoformat()),
        ]
        scored = score.score_papers(papers, cfg)
        # 只有 b 相关，a 被过滤
        self.assertEqual(len(scored), 1)
        self.assertEqual(scored[0].paper_id, "b")
        self.assertGreater(scored[0].score_final, 0)


if __name__ == "__main__":
    unittest.main()
