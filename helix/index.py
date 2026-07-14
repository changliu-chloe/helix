"""笔记库的 SQLite FTS5 全文索引。

用标准库 sqlite3 的 FTS5 虚拟表，对笔记的标题/摘要/正文建全文索引。
向量检索预留接口（vector_search），迭代后续再接 sentence-transformers。
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import yaml

from .config import Config


def index_path(cfg: Config) -> Path:
    """FTS5 索引位置，锚定项目根（config 所在目录）下的 .helix/index.db。"""
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


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """返回 (frontmatter dict, 正文)。"""
    m = re.match(r"^---\s*\n(.*?)^---\s*\n(.*)$", content, re.MULTILINE | re.DOTALL)
    if not m:
        return {}, content
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, m.group(2)


def build(cfg: Config) -> tuple[int, str]:
    """(重新)构建 FTS5 索引。返回 (索引条数, 提示信息)。"""
    papers_dir = cfg.papers_path
    conn = _connect(cfg)
    try:
        if not _fts5_available(conn):
            return 0, "当前 SQLite 不支持 FTS5，无法建索引"
        conn.execute("DROP TABLE IF EXISTS notes_fts")
        # path 为非索引列（UNINDEXED），仅存储
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
                fm, body = _parse_frontmatter(content)
                rel = str(md.relative_to(cfg.notes_path)).replace("\\", "/")
                title = str(fm.get("title") or md.stem)
                # 摘要：取正文里 ## 摘要/Abstract 段，退化为空
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
    """把用户查询包成 FTS5 安全的形式：按空白拆词，各词加引号，OR 连接。"""
    tokens = [t for t in re.split(r"\s+", query.strip()) if t]
    if not tokens:
        return '""'
    return " OR ".join(f'"{t.replace(chr(34), "")}"' for t in tokens)


def search(cfg: Config, query: str, limit: int = 10) -> list[dict]:
    """FTS5 全文检索，按 bm25 相关度排序。返回命中笔记列表。"""
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
    """向量检索占位。后续迭代接 sentence-transformers + 本地向量索引。"""
    raise NotImplementedError("向量检索尚未实现（计划后续迭代加入 sentence-transformers）")
