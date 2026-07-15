"""SQLite FTS5 full-text index for the notes library.

Uses the stdlib sqlite3 FTS5 virtual table to full-text index note title/abstract/body.
Vector search is a reserved interface (vector_search); sentence-transformers to be wired in a later iteration.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from . import frontmatter
from .config import Config


def index_path(cfg: Config) -> Path:
    """FTS5 index location, at .helix/index.db under the project root (the config directory)."""
    return cfg.index_path


def _connect(cfg: Config) -> sqlite3.Connection:
    p = index_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    return conn


def _fts5_available(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE temp._fts_probe USING fts5(x)")
        conn.execute("DROP TABLE temp._fts_probe")
        return True
    except sqlite3.OperationalError:
        return False


def build(cfg: Config) -> tuple[int, str]:
    """(Re)build the FTS5 index. Returns (number of indexed entries, message)."""
    papers_dir = cfg.papers_path
    conn = _connect(cfg)
    try:
        if not _fts5_available(conn):
            return 0, "当前 SQLite 不支持 FTS5，无法建索引"
        conn.execute("DROP TABLE IF EXISTS notes_fts")
        # path is a non-indexed column (UNINDEXED), stored only
        conn.execute(
            "CREATE VIRTUAL TABLE notes_fts USING fts5("
            "path UNINDEXED, title, abstract, body, tokenize='unicode61')"
        )
        count = 0
        if papers_dir.exists():
            from .notes import iter_note_files

            for md in iter_note_files(papers_dir):
                try:
                    content = md.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                fm, body = frontmatter.split(content)
                rel = str(md.relative_to(cfg.notes_path)).replace("\\", "/")
                title = str(fm.get("title") or md.stem)
                # abstract: take the ## 摘要/Abstract section from the body, empty if absent
                abstract = _extract_abstract(body)
                conn.execute(
                    "INSERT INTO notes_fts(path, title, abstract, body) VALUES (?,?,?,?)",
                    (rel, title, abstract, body),
                )
                count += 1
        conn.commit()
        return count, f"已索引 {count} 篇笔记 -> {index_path(cfg)}"
    finally:
        conn.close()


def _extract_abstract(body: str) -> str:
    m = re.search(r"^##\s*(摘要|Abstract)\s*\n(.*?)(?=^##\s|\Z)", body, re.MULTILINE | re.DOTALL)
    return m.group(2).strip() if m else ""


def _escape_fts_query(query: str) -> str:
    """Wrap the user query into an FTS5-safe form: split on whitespace, quote each token, join with OR."""
    tokens = [t for t in re.split(r"\s+", query.strip()) if t]
    if not tokens:
        return '""'
    return " OR ".join(f'"{t.replace(chr(34), "")}"' for t in tokens)


def search(cfg: Config, query: str, limit: int = 10) -> list[dict]:
    """FTS5 full-text search, ranked by bm25 relevance. Returns the list of matching notes."""
    conn = _connect(cfg)
    try:
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='notes_fts'")
        if cur.fetchone() is None:
            raise RuntimeError("索引不存在，请先运行：helix index build")
        fts_q = _escape_fts_query(query)
        rows = conn.execute(
            "SELECT path, title, snippet(notes_fts, 3, '[', ']', '…', 12) AS snip, "
            "bm25(notes_fts) AS rank FROM notes_fts WHERE notes_fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            (fts_q, limit),
        ).fetchall()
        return [{"path": r[0], "title": r[1], "snippet": r[2], "rank": round(r[3], 3)} for r in rows]
    finally:
        conn.close()


def vector_search(cfg: Config, query: str, limit: int = 10) -> list[dict]:
    """Vector search placeholder. A later iteration will wire in sentence-transformers + a local vector index."""
    raise NotImplementedError("向量检索尚未实现（计划后续迭代加入 sentence-transformers）")
