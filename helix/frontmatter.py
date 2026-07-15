"""YAML frontmatter parsing: a single shared implementation for the whole project.

Previously notes.py and index.py each had their own _parse_frontmatter (with
differing signatures); now consolidated here. Convention: a document is treated as
having frontmatter if it starts with `---\\n ... \\n---\\n`.
"""

from __future__ import annotations

import re

import yaml

# Match the leading --- ... --- block; group(1)=frontmatter text, group(2)=body after it
_FM_RE = re.compile(r"^---\s*\n(.*?)^---\s*\n(.*)$", re.MULTILINE | re.DOTALL)


def split(content: str) -> tuple[dict, str]:
    """Split into (frontmatter dict, body). Returns ({}, original) when no frontmatter."""
    m = _FM_RE.match(content)
    if not m:
        return {}, content
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    if not isinstance(fm, dict):
        fm = {}
    return fm, m.group(2)


def meta(content: str) -> dict:
    """Take only the frontmatter dict (use when the body doesn't matter)."""
    return split(content)[0]
