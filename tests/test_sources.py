"""来源适配器（S2/DBLP）与去重单元测试。用 mock 响应，不打真实网络。"""

import unittest
from unittest import mock

from arxo.sources import semantic_scholar as s2
from arxo.sources import dblp
from arxo.models import Paper
from arxo.cli import _dedup_papers


S2_SAMPLE = {
    "data": [
        {
            "paperId": "abc",
            "title": "OpenVLA: An Open VLA Model",
            "abstract": "we present a robot policy",
            "publicationDate": "2024-06-13",
            "year": 2024,
            "citationCount": 320,
            "influentialCitationCount": 40,
            "url": "https://s2.org/abc",
            "authors": [{"name": "A B"}, {"name": "C D"}],
            "externalIds": {"ArXiv": "2406.09246"},
        },
        {"paperId": "no-title", "title": None},  # 应被丢弃
    ]
}

DBLP_SAMPLE = {
    "result": {
        "hits": {
            "hit": [
                {
                    "@id": "1",
                    "info": {
                        "key": "conf/cvpr/Foo24",
                        "title": "A Vision-Language Model &amp; Beyond.",
                        "venue": "CVPR",
                        "year": "2024",
                        "ee": "https://doi.org/xxx",
                        "authors": {"author": [{"text": "Foo Bar"}, {"text": "Baz Qux"}]},
                    },
                }
            ]
        }
    }
}


class TestS2(unittest.TestCase):
    def test_parse_and_sort(self):
        with mock.patch.object(s2, "_request", return_value=S2_SAMPLE):
            papers = s2.search("vla")
        self.assertEqual(len(papers), 1)  # None 标题被丢弃
        p = papers[0]
        self.assertEqual(p.paper_id, "2406.09246")  # arXiv id 优先
        self.assertEqual(p.citation_count, 320)
        self.assertEqual(p.source, "s2")
        self.assertEqual(p.authors, ["A B", "C D"])

    def test_no_key_pre_request_throttle(self):
        # 无 api_key 时请求前应主动 sleep 节流
        import json as _json

        fake_resp = mock.MagicMock()
        fake_resp.read.return_value = _json.dumps(S2_SAMPLE).encode()
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = lambda *a: False
        with mock.patch.object(s2.time, "sleep") as msleep, mock.patch.object(
            s2.urllib.request, "urlopen", return_value=fake_resp
        ):
            s2._request("http://x", api_key="")
        msleep.assert_called_once_with(s2.NO_KEY_PRE_REQUEST_DELAY)

    def test_with_key_no_pre_throttle(self):
        import json as _json

        fake_resp = mock.MagicMock()
        fake_resp.read.return_value = _json.dumps(S2_SAMPLE).encode()
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = lambda *a: False
        with mock.patch.object(s2.time, "sleep") as msleep, mock.patch.object(
            s2.urllib.request, "urlopen", return_value=fake_resp
        ):
            s2._request("http://x", api_key="KEY")
        msleep.assert_not_called()  # 有 key 不节流


class TestDBLP(unittest.TestCase):
    def test_parse_unescape_and_venue(self):
        with mock.patch.object(dblp, "_request", return_value=DBLP_SAMPLE):
            papers = dblp.search("vlm")
        self.assertEqual(len(papers), 1)
        p = papers[0]
        self.assertEqual(p.title, "A Vision-Language Model & Beyond")  # &amp; 解码 + 去尾点
        self.assertEqual(p.categories, ["CVPR"])
        self.assertEqual(p.source, "dblp")
        self.assertEqual(p.published, "2024")


class TestDedup(unittest.TestCase):
    def test_dedup_by_id(self):
        papers = [
            Paper(paper_id="2406.09246", title="X", source="arxiv"),
            Paper(paper_id="2406.09246", title="X", source="s2"),  # 重复 id
            Paper(paper_id="other", title="Y", source="dblp"),
        ]
        out = _dedup_papers(papers)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].source, "arxiv")  # 保留先出现的

    def test_dedup_by_title_when_no_id(self):
        papers = [
            Paper(paper_id="", title="Same Title!", source="s2"),
            Paper(paper_id="", title="same title", source="dblp"),  # 归一化后相同
        ]
        out = _dedup_papers(papers)
        self.assertEqual(len(out), 1)


if __name__ == "__main__":
    unittest.main()
