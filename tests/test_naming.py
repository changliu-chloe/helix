"""Shared naming/slug helper unit tests."""

import unittest

from helix import naming


class TestSafeFilename(unittest.TestCase):
    def test_sanitizes_unsafe_chars(self):
        self.assertEqual(naming.safe_filename("a/b: c*d"), "a_b_c_d")

    def test_empty_falls_back(self):
        self.assertEqual(naming.safe_filename(""), "untitled")
        self.assertEqual(naming.safe_filename("///"), "untitled")


class TestShortTitle(unittest.TestCase):
    def test_author_coined_name(self):
        self.assertEqual(naming.short_title("Mamba: Linear-Time Sequence Modeling"), "Mamba")
        self.assertEqual(naming.short_title("Self-RAG: Learning to Retrieve"), "Self-RAG")

    def test_descriptive_first_words(self):
        # colon-prefix too long -> fall back to first few words
        self.assertEqual(
            naming.short_title("Attention Is All You Need For Everything"),
            "Attention_Is_All_You",
        )

    def test_too_long_colon_head_falls_back(self):
        # head before colon exceeds 30 chars -> first words instead
        title = "A Very Long Preamble That Exceeds Thirty Chars: Short"
        self.assertEqual(naming.short_title(title), "A_Very_Long_Preamble")

    def test_empty(self):
        self.assertEqual(naming.short_title(""), "untitled")


if __name__ == "__main__":
    unittest.main()
