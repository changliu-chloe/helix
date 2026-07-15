"""Search orchestration pipeline unit tests: dedup + multi-source fetch + failure isolation.

This logic used to be buried in cli.cmd_search, tied to argparse and impossible to unit test.
After extracting it into helix.pipeline it can be tested directly, independent of the command line.
"""

import unittest
from unittest import mock

from helix import pipeline
from helix.config import Config, Domain
from helix.models import Paper


class TestDedup(unittest.TestCase):
    def test_dedup_by_id(self):
        papers = [
            Paper(paper_id="2406.09246", title="X", source="arxiv"),
            Paper(paper_id="2406.09246", title="X", source="s2"),  # duplicate id
            Paper(paper_id="other", title="Y", source="dblp"),
        ]
        out = pipeline.dedup_papers(papers)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].source, "arxiv")  # keep the first-seen one

    def test_dedup_by_title_when_no_id(self):
        papers = [
            Paper(paper_id="", title="Same Title!", source="s2"),
            Paper(paper_id="", title="same title", source="dblp"),  # identical after normalization
        ]
        out = pipeline.dedup_papers(papers)
        self.assertEqual(len(out), 1)


class TestSearchPapers(unittest.TestCase):
    def _cfg(self) -> Config:
        cfg = Config()
        cfg.domains = [Domain(name="VLA", keywords=["vla", "robot", "policy"])]
        cfg.score_weights = {"relevance": 1.0, "recency": 0, "popularity": 0, "quality": 0}
        return cfg

    def test_source_failure_isolated(self):
        """An error from one source only skips that source; the rest return normally."""
        cfg = self._cfg()

        def fake_fetch(src, query, cfg, *, days, max_results, log):
            if src == "s2":
                raise RuntimeError("s2 挂了")
            return [Paper(paper_id="1", title="Good VLA policy", source=src)]

        with mock.patch.object(pipeline, "_fetch_one", side_effect=fake_fetch):
            res = pipeline.search_papers(cfg, "vla", ["arxiv", "s2", "dblp"], top_n=5)

        # arxiv + dblp return 1 each (same id gets deduped -> only 1 left); s2 is skipped without error
        self.assertEqual(res.sources, ["arxiv", "s2", "dblp"])
        self.assertEqual(res.total_fetched, 1)
        self.assertTrue(res.total_scored >= 0)

    def test_dedup_across_sources(self):
        cfg = self._cfg()

        def fake_fetch(src, query, cfg, *, days, max_results, log):
            return [Paper(paper_id="same", title="Dup", source=src)]

        with mock.patch.object(pipeline, "_fetch_one", side_effect=fake_fetch):
            res = pipeline.search_papers(cfg, "vla", ["arxiv", "s2"], top_n=5)
        self.assertEqual(res.total_fetched, 1)  # two sources with same id deduped

    def test_to_dict_shape(self):
        cfg = self._cfg()
        with mock.patch.object(pipeline, "_fetch_one", return_value=[]):
            res = pipeline.search_papers(cfg, "q", ["arxiv"], top_n=3)
        d = res.to_dict()
        self.assertEqual(set(d), {"query", "sources", "total_fetched", "total_scored", "top_papers"})
        self.assertEqual(d["query"], "q")
        self.assertIsInstance(d["top_papers"], list)


if __name__ == "__main__":
    unittest.main()
