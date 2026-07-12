"""arxo 命令行入口。子命令：search / fetch / note / index / status。

迭代 0 仅搭骨架：status 可用，其余子命令占位（后续迭代填充）。
"""

from __future__ import annotations

import argparse
import sys

from . import __version__


def _not_implemented(name: str) -> int:
    print(f"[arxo] 子命令 '{name}' 尚未实现（将在后续迭代中加入）", file=sys.stderr)
    return 2


def cmd_status(args: argparse.Namespace) -> int:
    from .config import load_config

    try:
        cfg = load_config(args.config)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 1

    print(f"arxo v{__version__}")
    print(f"配置文件   : {cfg._path}")
    print(f"语言       : {cfg.language}")
    print(f"笔记库     : {cfg.notes_path}")
    print(f"研究领域   : {len(cfg.domains)} 个")
    for d in cfg.domains:
        print(f"  - {d.name}（优先级 {d.priority}，{len(d.keywords)} 关键词，分类 {','.join(d.arxiv_categories)}）")
    print(f"arXiv 分类 : {','.join(cfg.all_categories())}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    import json

    from .config import load_config
    from .score import score_papers
    from .sources import arxiv

    try:
        cfg = load_config(args.config)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 1

    sources = [s.strip() for s in args.source.split(",") if s.strip()]
    unsupported = [s for s in sources if s != "arxiv"]
    if unsupported:
        print(f"[arxo] 来源 {unsupported} 暂未实现（迭代 4 加入 s2/dblp），本次仅用 arxiv", file=sys.stderr)

    try:
        if args.query:
            print(f"[arxo] 关键词检索 arXiv：{args.query}", file=sys.stderr)
            keywords = [k.strip() for k in args.query.split(",") if k.strip()]
            papers = arxiv.search_by_keywords(keywords, days=args.days, max_results=args.max_results)
        else:
            cats = cfg.all_categories()
            if not cats:
                print("[arxo] config 中没有任何 arXiv 分类，且未提供查询词", file=sys.stderr)
                return 1
            days = args.days if args.days is not None else 30
            print(f"[arxo] 按 config 领域分类检索 arXiv（近 {days} 天）：{','.join(cats)}", file=sys.stderr)
            papers = arxiv.search_by_categories(cats, days=days, max_results=args.max_results)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1

    print(f"[arxo] 抓取 {len(papers)} 篇，开始打分筛选", file=sys.stderr)
    scored = score_papers(papers, cfg)
    top = scored[: args.top_n]

    output = {
        "query": args.query or "",
        "total_fetched": len(papers),
        "total_scored": len(scored),
        "top_papers": [p.to_dict() for p in top],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))

    for i, p in enumerate(top, 1):
        print(f"  {i}. [{p.score_final}] {p.title[:70]}", file=sys.stderr)
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    return _not_implemented("fetch")


def cmd_note(args: argparse.Namespace) -> int:
    import json

    from . import notes as notes_mod
    from .config import load_config
    from .score import relevance_score

    try:
        cfg = load_config(args.config)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 1

    if args.action == "new":
        if not args.target:
            print("[arxo] note new 需要 arXiv id，例如：arxo note new 2503.22020", file=sys.stderr)
            return 1
        from .sources import arxiv

        try:
            paper = arxiv.get_by_id(args.target)
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            return 1
        if paper is None:
            print(f"[arxo] 未找到论文：{args.target}", file=sys.stderr)
            return 1
        # 用相关性判定归入哪个领域目录
        _, domain, matched = relevance_score(paper, cfg.domains, cfg.excluded_keywords)
        paper.matched_domains = [domain] if domain else []
        paper.matched_keywords = matched
        path, created = notes_mod.write_note(paper, cfg, overwrite=args.overwrite)
        action = "已创建" if created else "已存在（跳过，可加 --overwrite）"
        print(f"[arxo] {action}：{path}", file=sys.stderr)
        print(str(path))
        return 0

    if args.action == "scan":
        index = notes_mod.scan_notes(cfg)
        print(json.dumps(index, ensure_ascii=False, indent=2))
        print(f"[arxo] 扫描到 {len(index['notes'])} 篇笔记，{len(index['keyword_to_notes'])} 个关键词", file=sys.stderr)
        return 0

    if args.action == "link":
        if not args.target:
            print("[arxo] note link 需要文件路径，例如：arxo note link notes/papers/VLA/xxx.md", file=sys.stderr)
            return 1
        from pathlib import Path

        target = Path(args.target)
        if not target.exists():
            print(f"[arxo] 文件不存在：{target}", file=sys.stderr)
            return 1
        index = notes_mod.scan_notes(cfg)
        added = notes_mod.link_file(target, index["keyword_to_notes"])
        print(f"[arxo] {target}: 新增 {added} 个 wikilink", file=sys.stderr)
        return 0

    return 2


def cmd_index(args: argparse.Namespace) -> int:
    import json

    from . import index as index_mod
    from .config import load_config

    try:
        cfg = load_config(args.config)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 1

    if args.action == "build":
        count, msg = index_mod.build(cfg)
        print(f"[arxo] {msg}", file=sys.stderr)
        return 0 if count > 0 or "已索引" in msg else 1

    if args.action == "search":
        if not args.query:
            print("[arxo] index search 需要查询词，例如：arxo index search 'VLA'", file=sys.stderr)
            return 1
        try:
            if args.vector:
                results = index_mod.vector_search(cfg, args.query, limit=args.limit)
            else:
                results = index_mod.search(cfg, args.query, limit=args.limit)
        except NotImplementedError as e:
            print(f"[arxo] {e}", file=sys.stderr)
            return 2
        except RuntimeError as e:
            print(f"[arxo] {e}", file=sys.stderr)
            return 1
        print(json.dumps(results, ensure_ascii=False, indent=2))
        for i, r in enumerate(results, 1):
            print(f"  {i}. {r['title'][:60]}  ({r['path']})", file=sys.stderr)
        print(f"[arxo] 命中 {len(results)} 篇", file=sys.stderr)
        return 0

    return 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="arxo", description="论文检索追踪 + 深读理解 CLI")
    p.add_argument("--config", help="config.yaml 路径（默认当前目录或 $ARXO_CONFIG）")
    p.add_argument("--version", action="version", version=f"arxo {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("status", help="显示配置/库/索引状态")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("search", help="检索并打分论文（arxiv/s2/dblp）")
    sp.add_argument("query", nargs="?", help="检索词（逗号分隔多词；留空则按 config 领域检索）")
    sp.add_argument("--source", default="arxiv", help="来源，逗号分隔：arxiv,s2,dblp")
    sp.add_argument("--top-n", type=int, default=10, help="返回条数")
    sp.add_argument("--days", type=int, default=None, help="检索最近 N 天（关键词模式默认不限；分类模式默认 30）")
    sp.add_argument("--max-results", type=int, default=200, help="从 arXiv 拉取的最大条数")
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("fetch", help="抓取单篇论文全文/图片")
    sp.add_argument("paper_id")
    sp.set_defaults(func=cmd_fetch)

    sp = sub.add_parser("note", help="笔记：new <id> / scan / link <file>")
    sp.add_argument("action", choices=["new", "scan", "link"])
    sp.add_argument("target", nargs="?", help="new: arXiv id；link: 笔记文件路径")
    sp.add_argument("--overwrite", action="store_true", help="new: 覆盖已存在的笔记")
    sp.set_defaults(func=cmd_note)

    sp = sub.add_parser("index", help="FTS5 索引：build / search <query>")
    sp.add_argument("action", choices=["build", "search"])
    sp.add_argument("query", nargs="?", help="search: 查询词")
    sp.add_argument("--limit", type=int, default=10, help="search: 返回条数")
    sp.add_argument("--vector", action="store_true", help="search: 用向量检索（暂未实现）")
    sp.set_defaults(func=cmd_index)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
