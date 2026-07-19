"""helix command-line entry point. Subcommands: search / fetch / note / index / status.

Iteration 0 is scaffolding only: status works, the other subcommands are placeholders (filled in later iterations).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__


def _err(msg: str) -> None:
    """Unified prefixed output to stderr."""
    print(f"[helix] {msg}", file=sys.stderr)


def _load_cfg(args: argparse.Namespace):
    """Load config, returning None on failure (error already printed). Removes the repeated try/except boilerplate in each command."""
    from .config import load_config

    try:
        return load_config(args.config)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return None


def cmd_init(args: argparse.Namespace) -> int:
    from .init import link_agents_md, link_skills, list_skill_names

    logs = link_skills(scope=args.scope)
    # AGENTS.md -> CLAUDE.md is per-repo; only wire it for project scope.
    if args.scope != "global":
        logs += link_agents_md()
    for line in logs:
        print(f"[helix] {line}", file=sys.stderr)
    linked = sum(1 for x in logs if x.startswith("已链接"))
    print(f"[helix] init 完成：新建 {linked} 个软链（scope={args.scope}）", file=sys.stderr)
    print(
        "[helix] Claude Code 读 CLAUDE.md + .claude/skills；"
        "Codex / Cursor / Trae 读 AGENTS.md + .agents/skills（同一套 skills 与规约）",
        file=sys.stderr,
    )

    names = list_skill_names()
    if names:
        print(f"[helix] 现在可在支持 skill 的 agent 里用自然语言触发：{' / '.join(names)}", file=sys.stderr)
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    from . import migrate as migrate_mod

    cfg = _load_cfg(args)
    if cfg is None:
        return 1

    report, logs = migrate_mod.run_migrate(cfg, scope=args.scope, do_move=args.yes)
    for line in logs:
        _err(line)

    # Summary: what was enabled + what you still need to do by hand.
    _err(f"migrate 完成：新链 {len(report.linked)} 个 skill，清理 {len(report.pruned)} 个失效软链")
    todo: list[str] = []
    if report.workspace_migrate_pending:
        todo.append("发现数据目录（notes/experiments/.helix 等）还在 workspace/ 外。跑 `helix migrate --yes` 搬进 workspace/（只搬不删、先校验）")
    if report.workspace_migrated:
        _err(f"已搬进 workspace/：{'、'.join(report.workspace_migrated)}")
    if report.repro_rename_pending:
        todo.append("发现旧 repro/ 复现目录，新版改用 experiments/。跑 `helix migrate --yes` 搬迁（只搬不删、先校验）")
    if report.config_fields_written:
        keys = "、".join(report.config_fields_written)
        bak = "（已备份 config.yaml.bak）" if report.config_backed_up else ""
        todo.append(f"已按模板补充 config.yaml 字段，请填值：{keys}{bak}")
    if report.deps_changed:
        todo.append("依赖有更新，请跑：uv sync --extra dev（或用 uv run helix 会自动同步）")
    if report.index_stale_hint:
        todo.append("笔记比索引新，建议重建：uv run helix index build")
    if todo:
        _err("以下需你手动处理：")
        for t in todo:
            _err(f"  · {t}")
    else:
        _err("无需手动处理，全部就绪。")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = _load_cfg(args)
    if cfg is None:
        return 1

    print(f"helix v{__version__}")
    print(f"配置文件   : {cfg._path}")
    print(f"语言       : {cfg.language}")
    print(f"笔记库     : {cfg.notes_path}")
    print(f"研究领域   : {len(cfg.domains)} 个")
    for d in cfg.domains:
        print(f"  - {d.name}（优先级 {d.priority}，{len(d.keywords)} 关键词，分类 {','.join(d.arxiv_categories)}）")
    print(f"arXiv 分类 : {','.join(cfg.all_categories())}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    from . import pipeline

    cfg = _load_cfg(args)
    if cfg is None:
        return 1

    sources = [s.strip() for s in args.source.split(",") if s.strip()]
    unknown = [s for s in sources if s not in pipeline.KNOWN_SOURCES]
    if unknown:
        _err(f"未知来源 {unknown}，支持：{','.join(sorted(pipeline.KNOWN_SOURCES))}")
        return 1

    result = pipeline.search_papers(
        cfg, args.query, sources,
        top_n=args.top_n, days=args.days, max_results=args.max_results,
        log=_err,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))

    for i, p in enumerate(result.top_papers, 1):
        _err(f"  {i}. [{p.score_final}] ({p.source}) {p.title[:60]}")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    from .score import relevance_score
    from .adapters import arxiv, fulltext

    cfg = _load_cfg(args)
    if cfg is None:
        return 1

    arxiv_id = args.paper_id.strip()

    # Fetch metadata, determine domain -> assets directory
    try:
        paper = arxiv.get_by_id(arxiv_id)
    except RuntimeError as e:
        print(f"[helix] {e}", file=sys.stderr)
        return 1
    if paper is None:
        print(f"[helix] 未找到论文：{arxiv_id}", file=sys.stderr)
        return 1
    if args.domain:
        domain = args.domain
    else:
        _, domain, _ = relevance_score(paper, cfg.domains, cfg.excluded_keywords)
    assets = cfg.assets_path(domain or "未分类", arxiv_id)
    assets.mkdir(parents=True, exist_ok=True)

    # 1. High-res figures from the source tarball (for archiving; mostly pdf vector graphics, not for markdown inlining)
    source_figures: list = []
    try:
        print(f"[helix] 下载 arXiv 源码包提取高清图：{arxiv_id}", file=sys.stderr)
        source_figures = fulltext.download_source_figures(arxiv_id, assets)
        print(f"[helix] 提取到 {len(source_figures)} 张源码高清图（存档）", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[helix] 源码图提取失败（跳过）：{e}", file=sys.stderr)

    # 2. MinerU full text + renderable figures (jpg, for note inlining)
    md_path = None
    rendered_images: list = []
    if not args.figures_only and not args.no_mineru:
        key = cfg.mineru_key
        if not key:
            print("[helix] 未配置 mineru_api_key，跳过全文解析（仅抽图 + 摘要）。"
                  "配 config.yaml mineru_api_key 或环境变量 MINERU_API_KEY 可启用", file=sys.stderr)
        else:
            try:
                cache = cfg.base_dir / ".helix" / "cache"
                print("[helix] 下载 PDF 并调 MinerU 云端解析全文…", file=sys.stderr)
                pdf = fulltext.download_pdf(arxiv_id, cache)
                md_text, rendered_images = fulltext.mineru_parse(pdf, key, assets)
                md_path = assets / "fulltext.md"
                md_path.write_text(md_text, encoding="utf-8")
                print(f"[helix] 全文已存：{md_path}（{len(md_text)} 字符），"
                      f"可渲染插图 {len(rendered_images)} 张", file=sys.stderr)
            except RuntimeError as e:
                print(f"[helix] MinerU 全文解析失败（回退到摘要）：{e}", file=sys.stderr)

    def _rel(p) -> str:
        """Path relative to the assets directory, for inline references in notes."""
        try:
            return str(Path(p).relative_to(assets))
        except ValueError:
            return str(p)

    result = {
        "arxiv_id": arxiv_id,
        "domain": domain or "未分类",
        "assets_dir": str(assets),
        "fulltext": str(md_path) if md_path else None,
        # Note inlining uses these (renderable jpg, path relative to assets like images/fig1.jpg)
        "rendered_images": [_rel(p) for p in rendered_images],
        # High-res archive (mostly pdf, not recommended for inline rendering)
        "source_figures": [_rel(p) for p in source_figures],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"[helix] fetch 完成：assets -> {assets}", file=sys.stderr)
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    from . import notes as notes_mod
    from .score import relevance_score

    cfg = _load_cfg(args)
    if cfg is None:
        return 1

    if args.action == "new":
        if not args.target:
            _err("note new 需要 arXiv id，例如：helix note new 2503.22020")
            return 1
        from .adapters import arxiv

        try:
            paper = arxiv.get_by_id(args.target)
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            return 1
        if paper is None:
            print(f"[helix] 未找到论文：{args.target}", file=sys.stderr)
            return 1
        # Domain assignment: explicit --domain takes precedence (an agent may specify a new domain not in config); otherwise auto-detect by relevance
        if args.domain:
            domain, matched = args.domain, []
        else:
            _, domain, matched = relevance_score(paper, cfg.domains, cfg.excluded_keywords)
        paper.matched_domains = [domain] if domain else []
        paper.matched_keywords = matched
        try:
            path, created = notes_mod.write_note(paper, cfg, overwrite=args.overwrite, name=args.name)
        except OSError as e:
            print(f"[helix] {e}", file=sys.stderr)
            return 1
        action = "已创建" if created else "已存在（跳过，可加 --overwrite）"
        print(f"[helix] {action}：{path}", file=sys.stderr)
        print(str(path))
        return 0

    if args.action == "rename":
        if not args.target or not args.name:
            _err("note rename 需要笔记路径和 --name，例如：helix note rename notes/papers/VLA/xxx.md --name CoT-VLA")
            return 1
        target = Path(args.target)
        try:
            new_path, updated = notes_mod.rename_note(target, args.name, cfg, overwrite=args.overwrite)
        except OSError as e:
            print(f"[helix] {e}", file=sys.stderr)
            return 1
        print(f"[helix] 已改名：{target.name} → {new_path.name}（同步更新 {updated} 篇笔记的 wikilink）", file=sys.stderr)
        print(str(new_path))
        return 0

    if args.action == "scan":
        index = notes_mod.scan_notes(cfg)
        print(json.dumps(index, ensure_ascii=False, indent=2))
        print(f"[helix] 扫描到 {len(index['notes'])} 篇笔记，{len(index['keyword_to_notes'])} 个关键词", file=sys.stderr)
        return 0

    if args.action == "link":
        if not args.target:
            _err("note link 需要文件路径，例如：helix note link notes/papers/VLA/xxx.md")
            return 1
        target = Path(args.target)
        if not target.exists():
            _err(f"文件不存在：{target}")
            return 1
        index = notes_mod.scan_notes(cfg)
        added = notes_mod.link_file(target, index["keyword_to_notes"], cfg)
        print(f"[helix] {target}: 新增 {added} 个 wikilink", file=sys.stderr)
        return 0

    if args.action == "score":
        if not args.target:
            _err("note score 需要笔记路径，例如：helix note score notes/papers/VLA/xxx.md --relevance 8 --novelty 7 --reliability 6")
            return 1
        if args.relevance is None and args.novelty is None and args.reliability is None:
            _err("note score 至少要给一个维度：--relevance / --novelty / --reliability（0-10）")
            return 1
        target = Path(args.target)
        try:
            scores = notes_mod.set_review_scores(
                target,
                relevance=args.relevance, novelty=args.novelty, reliability=args.reliability,
                reviewer_model=args.reviewer_model or cfg.reviewer_model,
                note=args.note,
            )
        except OSError as e:
            print(f"[helix] {e}", file=sys.stderr)
            return 1
        print(json.dumps(scores, ensure_ascii=False, indent=2))
        print(f"[helix] 已写入打分：{target} → {scores}", file=sys.stderr)
        return 0

    return 2


def cmd_review(args: argparse.Namespace) -> int:
    from . import review as review_mod

    cfg = _load_cfg(args)
    if cfg is None:
        return 1

    if args.action == "new":
        if not args.topic:
            _err('review new 需要综述主题，例如：helix review new "视觉语言动作模型综述"')
            return 1
        try:
            path, created = review_mod.write_review(
                args.topic, cfg, overwrite=args.overwrite, name=args.name,
            )
        except OSError as e:
            print(f"[helix] {e}", file=sys.stderr)
            return 1
        action = "已创建" if created else "已存在（跳过，可加 --overwrite）"
        print(f"[helix] {action}：{path}", file=sys.stderr)
        print(str(path))
        return 0

    return 2


def cmd_index(args: argparse.Namespace) -> int:
    from . import index as index_mod

    cfg = _load_cfg(args)
    if cfg is None:
        return 1

    if args.action == "build":
        count, msg = index_mod.build(cfg)
        print(f"[helix] {msg}", file=sys.stderr)
        return 0 if count > 0 or "已索引" in msg else 1

    if args.action == "search":
        if not args.query:
            print("[helix] index search 需要查询词，例如：helix index search 'VLA'", file=sys.stderr)
            return 1
        try:
            if args.vector:
                results = index_mod.vector_search(cfg, args.query, limit=args.limit)
            else:
                results = index_mod.search(cfg, args.query, limit=args.limit)
        except NotImplementedError as e:
            print(f"[helix] {e}", file=sys.stderr)
            return 2
        except RuntimeError as e:
            print(f"[helix] {e}", file=sys.stderr)
            return 1
        print(json.dumps(results, ensure_ascii=False, indent=2))
        for i, r in enumerate(results, 1):
            print(f"  {i}. {r['title'][:60]}  ({r['path']})", file=sys.stderr)
        print(f"[helix] 命中 {len(results)} 篇", file=sys.stderr)
        return 0

    return 2


def cmd_repro(args: argparse.Namespace) -> int:
    from . import repro as repro_mod

    cfg = _load_cfg(args)
    if cfg is None:
        return 1

    if args.action == "vram":
        if not args.params:
            _err("repro vram 需要 --params（十亿参数，如 --params 7 表示 7B）")
            return 1
        try:
            est = repro_mod.estimate_vram(
                args.params, dtype=args.dtype, ctx=args.ctx, batch=args.batch,
                num_layers=args.layers, hidden=args.hidden, kv_dtype=args.kv_dtype,
            )
        except ValueError as e:
            print(f"[helix] {e}", file=sys.stderr)
            return 1
        # With --profile, check only that machine; otherwise check all in config
        if args.profile:
            prof = cfg.find_profile(args.profile)
            if prof is None:
                names = ", ".join(p.name for p in cfg.hardware_profiles) or "（无）"
                print(f"[helix] 未知硬件档 '{args.profile}'，config 已有：{names}", file=sys.stderr)
                return 1
            fits = [repro_mod.fit_check(est, prof)]
        else:
            fits = repro_mod.fit_check_all(est, cfg)

        out = {"estimate": est.to_dict(), "fit": [f.to_dict() for f in fits]}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        approx = "（KV 按经验架构近似）" if est.approximate else ""
        print(f"[helix] {args.params}B/{est.dtype} ctx={est.ctx} batch={est.batch} "
              f"→ 约 {est.total_gb:.1f}GB {approx}", file=sys.stderr)
        for f in fits:
            print(f"  - {f.profile}: {f.summary}", file=sys.stderr)
            for s in f.suggestions:
                print(f"      · {s}", file=sys.stderr)
        return 0

    if args.action == "new":
        mine = bool(getattr(args, "mine", None))
        if mine:
            # my own experiment: target is optional (a reference paper note/id); --mine gives the name
            title = args.mine
            domain = args.domain or "未分类"
            note_rel = ""
            if args.target:
                title, domain, note_rel = _resolve_target(cfg, args.target, args.domain)
                title = args.mine  # experiment name wins as the title
            kind = "mine"
        else:
            if not args.target:
                print("[helix] exp new 需要笔记路径或 arXiv id（自己的实验用 --mine \"<名字>\"）", file=sys.stderr)
                return 1
            title, domain, note_rel = _resolve_target(cfg, args.target, args.domain)
            if title is None:
                return 1
            kind = "repro"

        short = args.name or repro_mod.short_name(title)
        try:
            ws, created = repro_mod.build_experiment_workspace(
                title, note_rel, domain, short, cfg,
                kind=kind, draft=args.draft, overwrite=args.overwrite,
            )
        except (OSError, ValueError) as e:
            print(f"[helix] {e}", file=sys.stderr)
            return 1
        result = {"workspace": str(ws), "created": created, "title": title, "domain": domain, "kind": kind}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        where = "draft_notes" if args.draft else "experiments"
        msg = f"新建 {created}" if created else "已存在（跳过，可加 --overwrite）"
        print(f"[helix] 实验工作区（{where}，{kind}）：{ws} — {msg}", file=sys.stderr)
        print(str(ws))
        return 0

    if args.action in ("push", "pull", "run", "probe", "sessions", "kill", "start"):
        return _cmd_exp_remote(args, cfg)

    return 2


def _resolve_workspace_remote(cfg, ws):
    """From a workspace dir, load sync.yaml and resolve its Remote. Returns (remote, err_msg)."""
    from . import ssh as ssh_mod
    from . import sync as sync_mod

    try:
        spec = sync_mod.load_sync_spec(ws)
        remote = ssh_mod.require_remote(cfg, spec.remote)
        return remote, None
    except (FileNotFoundError, ValueError) as e:
        return None, str(e)


EXP_REMOTE_PATH_UNSET = 3  # exit code: workspace has no confirmed remote_path yet


def _resolve_remote_path(cfg, ws, remote, args):
    """Resolve the confirmed remote_path, honoring --remote-path first-time confirmation.

    Returns (remote_path, exit_code). exit_code is None when resolved; an int to return otherwise.
    On first use with no --remote-path, prints the suggested default and returns exit code 3
    (nothing on the remote is touched). With --remote-path, writes it back to sync.yaml and proceeds.
    """
    from . import sync as sync_mod

    spec = sync_mod.load_sync_spec(ws)
    confirmed = sync_mod.resolve_remote_path(spec)
    given = getattr(args, "remote_path", None)

    if confirmed and given and given != confirmed:
        sync_mod.set_remote_path(ws, given)  # explicit user override wins
        print(f"[helix] ⚠ 已覆盖远程路径映射：{confirmed} → {given}", file=sys.stderr)
        return given, None
    if confirmed:
        return confirmed, None
    if given:
        sync_mod.set_remote_path(ws, given)
        print(f"[helix] 已确认远程路径并写入 sync.yaml：{given}", file=sys.stderr)
        return given, None

    # first use, not confirmed: suggest default, do NOT touch the remote
    default = sync_mod.default_remote_path(remote, ws)
    print(f"[helix] 本工作区尚未确认远程路径。建议：{default}", file=sys.stderr)
    print(f"[helix] 确认就重跑并加 --remote-path {default}（可改成别的路径）", file=sys.stderr)
    return None, EXP_REMOTE_PATH_UNSET


def _cmd_exp_remote(args, cfg) -> int:
    """Remote execution actions: run / probe / sessions / kill / start. Credentials stay in the CLI."""
    from . import secrets as secrets_mod
    from . import ssh as ssh_mod

    if not args.target:
        print(f"[helix] exp {args.action} 需要工作区路径", file=sys.stderr)
        return 1
    ws = Path(args.target)
    if not ws.is_dir():
        print(f"[helix] 工作区不存在或不是目录：{ws}", file=sys.stderr)
        return 1

    remote, err = _resolve_workspace_remote(cfg, ws)
    if remote is None:
        print(f"[helix] {err}", file=sys.stderr)
        return 1
    secrets = secrets_mod.load_secrets(cfg.base_dir)

    # sessions / kill don't need a workspace path on the remote — handle before path resolution.
    if args.action == "sessions":
        res = ssh_mod.list_sessions(cfg, secrets, remote)
        print(res.stdout.rstrip() or "（无远程 tmux 会话）")
        return 0

    if args.action == "kill":
        if not args.session:
            print("[helix] exp kill 需要 --session <会话名>", file=sys.stderr)
            return 1
        res = ssh_mod.kill_session(cfg, secrets, remote, args.session)
        ok = res.returncode == 0
        print(f"[helix] {'已杀会话' if ok else '杀会话失败'}：{remote.name}:{args.session}", file=sys.stderr)
        return 0 if ok else 1

    if args.action == "probe":
        # probe tolerates an unconfirmed path (falls back to remote root); pass confirmed path if any.
        from . import sync as sync_mod
        confirmed = sync_mod.resolve_remote_path(sync_mod.load_sync_spec(ws))
        info = ssh_mod.probe(cfg, secrets, remote, remote_path=confirmed)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        d = info.get("disk", {})
        if d:
            print(f"[helix] 磁盘可用 {d.get('avail')}（已用 {d.get('use_pct')}）", file=sys.stderr)
        for g in info.get("gpus", []):
            print(f"  - GPU{g['index']}: {g['mem_used_mb']}/{g['mem_total_mb']}MB, 利用率 {g['util_pct']}%", file=sys.stderr)
        if not info.get("has_gpu"):
            print("[helix] 远程未探测到 nvidia-smi（无 GPU 或未装驱动）", file=sys.stderr)
        return 0 if info.get("returncode") == 0 else 1

    if args.action == "run":
        if not args.cmd:
            print("[helix] exp run 需要 --cmd \"<命令>\"", file=sys.stderr)
            return 1
        remote_path, code = _resolve_remote_path(cfg, ws, remote, args)
        if remote_path is None:
            return code
        session = args.session or "helix-exp"
        try:
            res = ssh_mod.run_in_tmux(
                cfg, secrets, remote, remote_path, args.cmd,
                session=session, oneshot=args.oneshot, use_sudo=args.sudo,
            )
        except FileNotFoundError as e:
            print(f"[helix] {e}", file=sys.stderr)
            return 1
        for w in res.warnings:
            print(f"[helix] ⚠ {w}", file=sys.stderr)
        mode = "oneshot（跑完退会话）" if args.oneshot else "常驻（保留会话）"
        print(f"[helix] exp run → {remote.name}:{remote_path} tmux 会话 '{session}'（{mode}）", file=sys.stderr)
        if res.stdout.strip():
            print(res.stdout.rstrip(), file=sys.stderr)
        return 0 if res.returncode == 0 else 1

    if args.action in ("push", "pull"):
        remote_path, code = _resolve_remote_path(cfg, ws, remote, args)
        if remote_path is None:
            return code
        return _cmd_exp_transfer(args, cfg, ws)

    if args.action == "start":
        remote_path, code = _resolve_remote_path(cfg, ws, remote, args)
        if remote_path is None:
            return code
        return _cmd_exp_start(args, cfg, ws, remote)

    return 2


def _cmd_exp_transfer(args, cfg, ws) -> int:
    """exp push / pull over scp, after the remote path is confirmed."""
    from . import sync as sync_mod

    try:
        fn = sync_mod.push if args.action == "push" else sync_mod.pull
        res = fn(cfg, ws, dry_run=args.dry_run)
    except (FileNotFoundError, ValueError) as e:
        print(f"[helix] {e}", file=sys.stderr)
        return 1
    for w in res.warnings:
        print(f"[helix] ⚠ {w}", file=sys.stderr)
    tag = "（dry-run 预览，未实际传输）" if res.dry_run else ""
    print(f"[helix] exp {res.direction} → {res.remote_name}:{res.remote_dir} {tag}", file=sys.stderr)
    return 0 if res.returncode == 0 else 1


def _cmd_exp_start(args, cfg, ws, remote) -> int:
    """Start a round: enforce a clean tree (auto-commit if dirty), push to remote, report the commit."""
    from . import sync as sync_mod
    from . import vcs as vcs_mod

    repo = cfg.base_dir
    try:
        if not vcs_mod.is_clean(repo):
            msg = args.message or "实验轮次：本地改动"
            commit = vcs_mod.commit_round(repo, msg)
            print(f"[helix] 本轮改动已提交：{commit} — {msg}", file=sys.stderr)
        else:
            commit = vcs_mod.current_commit(repo)
            print(f"[helix] 工作区干净，当前提交：{commit}", file=sys.stderr)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"[helix] git 步骤失败：{e}", file=sys.stderr)
        return 1

    try:
        res = sync_mod.push(cfg, ws, dry_run=args.dry_run)
    except (FileNotFoundError, ValueError) as e:
        print(f"[helix] push 失败：{e}", file=sys.stderr)
        return 1
    for w in res.warnings:
        print(f"[helix] ⚠ {w}", file=sys.stderr)
    out = {"commit": commit, "remote": res.remote_name, "remote_dir": res.remote_dir, "dry_run": res.dry_run}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    tag = "（dry-run，未实际传输）" if res.dry_run else ""
    print(f"[helix] 开始实验：代码 {commit} 已推到 {res.remote_name}:{res.remote_dir} {tag}", file=sys.stderr)
    print("[helix] 下一步：uv run helix exp run <工作区> --cmd \"<跑实验命令>\" --session <名>", file=sys.stderr)
    return 0 if res.returncode == 0 else 1


def _resolve_target(cfg, target: str, domain_arg: str | None):
    """Resolve (title, domain, note_rel) from an existing note file or an arXiv id. Returns (None, None, None) on failure."""
    p = Path(target)
    if p.exists() and p.suffix == ".md":
        from . import frontmatter
        fm = frontmatter.meta(p.read_text(encoding="utf-8", errors="replace"))
        title = fm.get("title") or p.stem
        doms = fm.get("domains") or []
        domain = domain_arg or (doms[0] if doms else "未分类")
        try:
            note_rel = str(p.resolve().relative_to(cfg.notes_path)).replace("\\", "/")
        except ValueError:
            note_rel = str(p).replace("\\", "/")
        return title, domain, note_rel

    from .adapters import arxiv
    try:
        paper = arxiv.get_by_id(target)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return None, None, None
    if paper is None:
        print(f"[helix] 未找到论文，也不是已存在笔记：{target}", file=sys.stderr)
        return None, None, None
    domain = domain_arg or "未分类"
    return paper.title, domain, f"papers/{domain}/{paper.title}"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="helix", description="论文检索追踪 + 深读理解 CLI")
    p.add_argument("--config", help="config.yaml 路径（默认当前目录或 $HELIX_CONFIG）")
    p.add_argument("--version", action="version", version=f"helix {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("status", help="显示配置/库/索引状态")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("init", help="软链 skills 到 .claude/skills + .agents/skills、AGENTS.md→CLAUDE.md，启用自然语言触发")
    sp.add_argument("--scope", choices=["project", "global"], default="project",
                    help="project: 本项目 .claude/skills + .agents/skills（默认，含 AGENTS.md 软链）；global: ~/.claude/skills + ~/.agents/skills")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("migrate", help="git pull 后追平：重链 skill、清失效软链、提示 config/依赖/索引更新、搬迁 repro→experiments")
    sp.add_argument("--scope", choices=["project", "global"], default="project",
                    help="project: 本项目 .claude/skills（默认）；global: ~/.claude/skills")
    sp.add_argument("--yes", action="store_true",
                    help="执行存储搬迁（repro/ → experiments/，只搬不删、先校验后核对）；省略则只提示")
    sp.set_defaults(func=cmd_migrate)

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

    sp = sub.add_parser("note", help="笔记：new <id> / scan / link <file> / rename <file> / score <file>")
    sp.add_argument("action", choices=["new", "scan", "link", "rename", "score"])
    sp.add_argument("target", nargs="?", help="new: arXiv id；link/rename/score: 笔记文件路径")
    sp.add_argument("--overwrite", action="store_true", help="new: 覆盖已存在的笔记；rename: 允许覆盖同名目标")
    sp.add_argument("--domain", help="new: 指定研究方向（归档目录），可用 config 里没有的新方向；留空则自动判定")
    sp.add_argument("--name", help="new: 指定笔记短名（省略从标题自动生成短名）；rename: 新短名")
    sp.add_argument("--relevance", type=float, help="score: 相关性打分 0-10（独立评审给，见 skills/deep-read）")
    sp.add_argument("--novelty", type=float, help="score: 创新性打分 0-10")
    sp.add_argument("--reliability", type=float, help="score: 可靠性打分 0-10")
    sp.add_argument("--reviewer-model", help="score: 评审模型名（省略取 config reviewer_model）")
    sp.add_argument("--note", help="score: 打分理由一句话（写进 frontmatter）")
    sp.set_defaults(func=cmd_note)

    sp = sub.add_parser("review", help="文献综述：new <topic> 生成综述骨架")
    sp.add_argument("action", choices=["new"])
    sp.add_argument("topic", nargs="?", help="new: 综述主题，如 “视觉语言动作模型综述”")
    sp.add_argument("--name", help="new: 指定综述短名（省略从主题自动生成）")
    sp.add_argument("--overwrite", action="store_true", help="new: 覆盖已存在的综述骨架")
    sp.set_defaults(func=cmd_review)

    sp = sub.add_parser("exp", help="实验/复现：vram 判级 / new 建工作区 / push·pull 传送 / start·run·probe·sessions·kill 远程执行")
    sp.add_argument("action", choices=["vram", "new", "push", "pull", "start", "run", "probe", "sessions", "kill"])
    sp.add_argument("target", nargs="?", help="new: 笔记/arXiv id；push/pull/start/run/probe/sessions/kill: 工作区路径")
    sp.add_argument("--params", type=float, help="vram: 模型参数量（十亿，如 7 表示 7B）")
    sp.add_argument("--dtype", default="fp16", help="vram: 权重精度 fp32/fp16/bf16/fp8/int8/int4")
    sp.add_argument("--ctx", type=int, default=2048, help="vram: 上下文长度")
    sp.add_argument("--batch", type=int, default=1, help="vram: 批大小")
    sp.add_argument("--layers", type=int, default=None, help="vram: 层数（给了则精算 KV）")
    sp.add_argument("--hidden", type=int, default=None, help="vram: hidden size（给了则精算 KV）")
    sp.add_argument("--kv-dtype", default=None, help="vram: KV cache 精度（默认同权重上限 fp16）")
    sp.add_argument("--profile", help="vram: 只判这台硬件档；省略判 config 全部")
    sp.add_argument("--name", help="new: 工作区短名（省略从标题自动生成）")
    sp.add_argument("--domain", help="new: 研究方向（归档子目录）")
    sp.add_argument("--mine", metavar="实验名", help="new: 建我自己的实验（type:mine，无 setup.md）；target 可选为对标论文")
    sp.add_argument("--draft", action="store_true", help="new: 落 draft_notes/ 而非 experiments/")
    sp.add_argument("--overwrite", action="store_true", help="new: 覆盖已有骨架")
    sp.add_argument("--dry-run", action="store_true", help="push/pull/start: 预览传输，不实际改动")
    sp.add_argument("--cmd", help="run: 在远程 tmux 里执行的命令")
    sp.add_argument("--session", help="run/kill: 远程 tmux 会话名（run 省略用 helix-exp）")
    sp.add_argument("--oneshot", action="store_true", help="run: 命令跑完自动退会话（如装环境）；省略则保留会话")
    sp.add_argument("--sudo", action="store_true", help="run: 命令需 sudo（sudo 密码经 stdin 注入，不进 argv）")
    sp.add_argument("--message", "-m", help="start: 本轮实验的提交信息（省略用默认）")
    sp.add_argument("--remote-path", help="push/pull/run/start: 确认/指定远程工作区路径（首次需要，写入 sync.yaml）")
    sp.set_defaults(func=cmd_repro)

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
