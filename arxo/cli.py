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


def cmd_init(args: argparse.Namespace) -> int:
    from .init import link_skills

    logs = link_skills(scope=args.scope)
    for line in logs:
        print(f"[arxo] {line}", file=sys.stderr)
    linked = sum(1 for x in logs if x.startswith("已链接"))
    print(f"[arxo] init 完成：新建 {linked} 个软链（scope={args.scope}）", file=sys.stderr)

    from .init import list_skill_names

    names = list_skill_names()
    if names:
        print(f"[arxo] 现在可在支持 skill 的 agent 里用自然语言触发：{' / '.join(names)}", file=sys.stderr)
    return 0


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


def _dedup_papers(papers: list) -> list:
    """按 paper_id 优先、标题归一化其次去重。保留先出现的（通常引用数更高/更相关）。"""
    import re

    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    out = []
    for p in papers:
        pid = (p.paper_id or "").strip()
        if pid:
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            out.append(p)
        else:
            norm = re.sub(r"[^a-z0-9\s]", "", (p.title or "").lower()).strip()
            if norm and norm in seen_titles:
                continue
            if norm:
                seen_titles.add(norm)
            out.append(p)
    return out


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
    known = {"arxiv", "s2", "dblp"}
    unknown = [s for s in sources if s not in known]
    if unknown:
        print(f"[arxo] 未知来源 {unknown}，支持：arxiv,s2,dblp", file=sys.stderr)
        return 1

    papers: list = []
    for src in sources:
        try:
            if src == "arxiv":
                if args.query:
                    print(f"[arxo] [arxiv] 关键词检索：{args.query}", file=sys.stderr)
                    kws = [k.strip() for k in args.query.split(",") if k.strip()]
                    got = arxiv.search_by_keywords(kws, days=args.days, max_results=args.max_results)
                else:
                    cats = cfg.all_categories()
                    if not cats:
                        print("[arxo] config 无 arXiv 分类且未提供查询词，跳过 arxiv", file=sys.stderr)
                        got = []
                    else:
                        days = args.days if args.days is not None else 30
                        print(f"[arxo] [arxiv] 按 config 分类检索（近 {days} 天）：{','.join(cats)}", file=sys.stderr)
                        got = arxiv.search_by_categories(cats, days=days, max_results=args.max_results)
            elif src == "s2":
                from .sources import semantic_scholar

                q = args.query or " ".join(cfg.domains[0].keywords[:3]) if cfg.domains else args.query
                if not q:
                    print("[arxo] s2 需要查询词或 config 领域，跳过 s2", file=sys.stderr)
                    got = []
                else:
                    print(f"[arxo] [s2] 检索：{q}", file=sys.stderr)
                    got = semantic_scholar.search(q, limit=args.max_results, api_key=cfg.semantic_scholar_api_key)
            else:  # dblp
                from .sources import dblp

                q = args.query or (" ".join(cfg.domains[0].keywords[:3]) if cfg.domains else "")
                if not q:
                    print("[arxo] dblp 需要查询词或 config 领域，跳过 dblp", file=sys.stderr)
                    got = []
                else:
                    print(f"[arxo] [dblp] 检索：{q}", file=sys.stderr)
                    got = dblp.search(q, limit=args.max_results)
        except RuntimeError as e:
            print(f"[arxo] [{src}] 失败（跳过）：{e}", file=sys.stderr)
            got = []
        print(f"[arxo] [{src}] 拉回 {len(got)} 篇", file=sys.stderr)
        papers.extend(got)

    papers = _dedup_papers(papers)
    print(f"[arxo] 合并去重后 {len(papers)} 篇，开始打分筛选", file=sys.stderr)
    scored = score_papers(papers, cfg)
    top = scored[: args.top_n]

    output = {
        "query": args.query or "",
        "sources": sources,
        "total_fetched": len(papers),
        "total_scored": len(scored),
        "top_papers": [p.to_dict() for p in top],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))

    for i, p in enumerate(top, 1):
        print(f"  {i}. [{p.score_final}] ({p.source}) {p.title[:60]}", file=sys.stderr)
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    import json

    from .config import load_config
    from .score import relevance_score
    from .sources import arxiv, fulltext

    try:
        cfg = load_config(args.config)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 1

    arxiv_id = args.paper_id.strip()

    # 抓元数据，定领域 -> assets 目录
    try:
        paper = arxiv.get_by_id(arxiv_id)
    except RuntimeError as e:
        print(f"[arxo] {e}", file=sys.stderr)
        return 1
    if paper is None:
        print(f"[arxo] 未找到论文：{arxiv_id}", file=sys.stderr)
        return 1
    if args.domain:
        domain = args.domain
    else:
        _, domain, _ = relevance_score(paper, cfg.domains, cfg.excluded_keywords)
    assets = cfg.assets_path(domain or "未分类", arxiv_id)
    assets.mkdir(parents=True, exist_ok=True)

    # 1. 源码包高清图
    figures: list = []
    try:
        print(f"[arxo] 下载 arXiv 源码包提取高清图：{arxiv_id}", file=sys.stderr)
        figures = fulltext.download_source_figures(arxiv_id, assets)
        print(f"[arxo] 提取到 {len(figures)} 张源码图", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[arxo] 源码图提取失败（跳过）：{e}", file=sys.stderr)

    # 2. MinerU 全文（可选，无 key 或 --no-mineru 则跳过）
    md_path = None
    if not args.figures_only and not args.no_mineru:
        key = cfg.mineru_key
        if not key:
            print("[arxo] 未配置 mineru_api_key，跳过全文解析（仅抽图 + 摘要）。"
                  "配 config.yaml mineru_api_key 或环境变量 MINERU_API_KEY 可启用", file=sys.stderr)
        else:
            try:
                cache = cfg.base_dir / ".arxo" / "cache"
                print("[arxo] 下载 PDF 并调 MinerU 云端解析全文…", file=sys.stderr)
                pdf = fulltext.download_pdf(arxiv_id, cache)
                md_text, mineru_imgs = fulltext.mineru_parse(pdf, key, assets)
                md_path = assets / "fulltext.md"
                md_path.write_text(md_text, encoding="utf-8")
                if not figures:  # 源码没图时用 MinerU 的图兜底
                    figures = mineru_imgs
                print(f"[arxo] 全文已存：{md_path}（{len(md_text)} 字符）", file=sys.stderr)
            except RuntimeError as e:
                print(f"[arxo] MinerU 全文解析失败（回退到摘要）：{e}", file=sys.stderr)

    result = {
        "arxiv_id": arxiv_id,
        "domain": domain or "未分类",
        "assets_dir": str(assets),
        "fulltext": str(md_path) if md_path else None,
        "figures": [str(f) for f in figures],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"[arxo] fetch 完成：assets -> {assets}", file=sys.stderr)
    return 0


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
        # 领域归属：显式 --domain 优先（agent 可指定 config 里没有的新方向）；否则按相关性自动判定
        if args.domain:
            domain, matched = args.domain, []
        else:
            _, domain, matched = relevance_score(paper, cfg.domains, cfg.excluded_keywords)
        paper.matched_domains = [domain] if domain else []
        paper.matched_keywords = matched
        try:
            path, created = notes_mod.write_note(paper, cfg, overwrite=args.overwrite)
        except OSError as e:
            print(f"[arxo] {e}", file=sys.stderr)
            return 1
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

    sp = sub.add_parser("init", help="把 skills 软链到 .claude/skills，启用自然语言触发")
    sp.add_argument("--scope", choices=["project", "global"], default="project",
                    help="project: 本项目 .claude/skills（默认）；global: ~/.claude/skills")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("search", help="检索并打分论文（arxiv/s2/dblp）")
    sp.add_argument("query", nargs="?", help="检索词（逗号分隔多词；留空则按 config 领域检索）")
    sp.add_argument("--source", default="arxiv", help="来源，逗号分隔：arxiv,s2,dblp")
    sp.add_argument("--top-n", type=int, default=10, help="返回条数")
    sp.add_argument("--days", type=int, default=None, help="检索最近 N 天（关键词模式默认不限；分类模式默认 30）")
    sp.add_argument("--max-results", type=int, default=200, help="从 arXiv 拉取的最大条数")
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("fetch", help="抓取单篇论文全文（MinerU）+ 高清图（源码包）")
    sp.add_argument("paper_id", help="arXiv id，如 2503.22020")
    sp.add_argument("--figures-only", action="store_true", help="只抽高清图，不解析全文")
    sp.add_argument("--no-mineru", action="store_true", help="不调 MinerU 云端（离线，仅抽图）")
    sp.add_argument("--domain", help="指定研究方向（assets 归档目录），与 note new --domain 保持一致")
    sp.set_defaults(func=cmd_fetch)

    sp = sub.add_parser("note", help="笔记：new <id> / scan / link <file>")
    sp.add_argument("action", choices=["new", "scan", "link"])
    sp.add_argument("target", nargs="?", help="new: arXiv id；link: 笔记文件路径")
    sp.add_argument("--overwrite", action="store_true", help="new: 覆盖已存在的笔记")
    sp.add_argument("--domain", help="new: 指定研究方向（归档目录），可用 config 里没有的新方向；留空则自动判定")
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
