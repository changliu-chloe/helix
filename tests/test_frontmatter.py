"""Shared frontmatter parsing unit tests (previously duplicated in notes/index)."""

import unittest

from helix import frontmatter


class TestSplit(unittest.TestCase):
    def test_parse(self):
        fm, body = frontmatter.split("---\ntitle: X\n---\nbody here")
        self.assertEqual(fm["title"], "X")
        self.assertEqual(body.strip(), "body here")

    def test_no_frontmatter(self):
        fm, body = frontmatter.split("just text")
        self.assertEqual(fm, {})
        self.assertEqual(body, "just text")

    def test_malformed_yaml_falls_back_empty(self):
        # bad YAML in the frontmatter block (not a dict) should not raise; returns {}
        fm, body = frontmatter.split("---\n: : bad\n---\nx")
        self.assertEqual(fm, {})
        self.assertEqual(body.strip(), "x")

    def test_non_dict_frontmatter(self):
        fm, _ = frontmatter.split("---\n- just\n- a list\n---\nx")
        self.assertEqual(fm, {})


class TestMeta(unittest.TestCase):
    def test_meta_returns_dict_only(self):
        self.assertEqual(frontmatter.meta("---\ntitle: X\n---\nbody"), {"title": "X"})

    def test_meta_no_frontmatter(self):
        self.assertEqual(frontmatter.meta("plain"), {})


if __name__ == "__main__":
    unittest.main()
