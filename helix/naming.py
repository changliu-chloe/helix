"""Shared filename/slug helpers.

Consolidates the filesystem-safe sanitization regex and the "short title"
logic that were previously duplicated across notes.py, repro.py and config.py.
User-facing note filenames should stay short; see short_title().
"""

from __future__ import annotations

import re

# Characters unsafe in filenames across common filesystems.
_UNSAFE = re.compile(r'[ /\\:*?"<>|]+')


def safe_filename(s: str, fallback: str = "untitled") -> str:
    """Sanitize a string into a filesystem-safe name (no extension)."""
    return _UNSAFE.sub("_", s or "").strip("_") or fallback


def short_title(title: str, fallback: str = "untitled") -> str:
    """Derive a short, safe name from a paper title.

    Prefer an author-coined short name before the colon (e.g. "CoT-VLA:",
    "Mamba:", "Self-RAG:") when it is 2-30 chars; otherwise fall back to the
    first few words of the title. Result is filesystem-safe.
    """
    if not title:
        return fallback
    head = title.split(":")[0].strip()
    if not (2 <= len(head) <= 30):
        head = " ".join(title.split()[:4])
    return safe_filename(head, fallback)
