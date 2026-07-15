"""Source adapters (S2/DBLP) unit tests. Uses mocked responses, no real network."""

import unittest
from unittest import mock

from helix.adapters import semantic_scholar as s2
from helix.adapters import dblp
from helix.models import Paper


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
        {"paperId": "no-title", "title": None},  # should be discarded
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
        self.assertEqual(len(papers), 1)  # None title discarded
        p = papers[0]
        self.assertEqual(p.paper_id, "2406.09246")  # arXiv id preferred
        self.assertEqual(p.citation_count, 320)
        self.assertEqual(p.source, "s2")
        self.assertEqual(p.authors, ["A B", "C D"])

    def test_no_key_pre_request_throttle(self):
        # without api_key, should proactively sleep to throttle before the request
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
        msleep.assert_not_called()  # with a key, no throttling


class TestDBLP(unittest.TestCase):
    def test_parse_unescape_and_venue(self):
        with mock.patch.object(dblp, "_request", return_value=DBLP_SAMPLE):
            papers = dblp.search("vlm")
        self.assertEqual(len(papers), 1)
        p = papers[0]
        self.assertEqual(p.title, "A Vision-Language Model & Beyond")  # &amp; decoded + trailing period stripped
        self.assertEqual(p.categories, ["CVPR"])
        self.assertEqual(p.source, "dblp")
        self.assertEqual(p.published, "2024")


if __name__ == "__main__":
    unittest.main()
