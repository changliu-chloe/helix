"""Thin wrapper around MinerU cloud parsing.

Converts a PDF to markdown + figures via the `mineru-open-api` CLI (passing the key through `MINERU_TOKEN`).
Isolates third-party interface details for easy replacement/testing. Modeled on ref/scholaraio's calling approach.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

MINERU_CLI = "mineru-open-api"
DEFAULT_TIMEOUT = 600  # seconds; cloud parsing + polling download


def _find_cli() -> str | None:
    """Locate the mineru-open-api CLI: prefer the current interpreter's directory (same venv/bin), then fall back to PATH.

    helix is often invoked directly as .venv/bin/helix, and the subprocess PATH
    does not include .venv/bin, so relying on shutil.which alone would miss the CLI in the same venv.
    """
    sibling = Path(sys.executable).parent / MINERU_CLI
    if sibling.exists():
        return str(sibling)
    return shutil.which(MINERU_CLI)


def parse_pdf_cloud(
    pdf_path: Path,
    api_key: str,
    out_dir: Path,
    language: str = "en",
    model: str = "pipeline",
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[str, list[Path]]:
    """Call MinerU cloud to convert a PDF to markdown. Returns (markdown text, list of figure paths).

    On failure (CLI not installed / network / non-zero exit) raises RuntimeError, so the upper layer falls back.
    """
    cli = _find_cli()
    if cli is None:
        raise RuntimeError(f"未找到 {MINERU_CLI} CLI，安装：uv pip install 'helix[fulltext]'")

    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        cli, "extract", str(pdf_path),
        "-o", str(out_dir),
        "--language", language,
        "--model", model,
        "--timeout", str(timeout),
    ]
    env = {**os.environ, "MINERU_TOKEN": api_key}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30, env=env)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"MinerU 解析超时（>{timeout}s）") from e
    if proc.returncode != 0:
        raise RuntimeError(f"MinerU 解析失败（退出码 {proc.returncode}）：{(proc.stderr or '')[:200]}")

    md_text, md_path = _find_markdown(out_dir, pdf_path.stem)
    if md_path is None:
        raise RuntimeError("MinerU 未产出 markdown 文件")

    # Rename hash-named images to fig1/fig2... in body appearance order, and rewrite the in-body references accordingly
    md_text, renamed = rename_images_sequentially(md_text, md_path.parent)

    # Delete MinerU's original .md (it references the old hash names and would become a broken link); keep only the fulltext.md written by the caller
    if md_path.name != "fulltext.md":
        md_path.unlink(missing_ok=True)

    return md_text, renamed


IMG_REF_RE = None  # compiled lazily, see rename_images_sequentially


def rename_images_sequentially(md_text: str, base_dir: Path) -> tuple[str, list[Path]]:
    """Rename images referenced by the md to images/figN.<ext> in appearance order, rewriting the references.

    Returns (rewritten md, list of renamed figure paths). base_dir is the directory containing the md.
    Only handles ![](...) references pointing to local relative paths (skips http/absolute paths).
    """
    import re

    ref_re = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
    order: list[str] = []  # original reference paths, deduped by first appearance
    for m in ref_re.finditer(md_text):
        ref = m.group(1).strip()
        if ref.startswith(("http://", "https://", "/")) or ref in order:
            continue
        order.append(ref)

    mapping: dict[str, str] = {}
    renamed: list[Path] = []
    counter = 0
    for ref in order:
        src = (base_dir / ref).resolve()
        if not src.exists() or src.suffix.lower() not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
            continue
        counter += 1
        new_rel = f"images/fig{counter}{src.suffix.lower()}"
        dst = base_dir / new_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            if src.resolve() != dst.resolve():
                shutil.move(str(src), str(dst))
            mapping[ref] = new_rel
            renamed.append(dst)
        except OSError:
            continue

    def _sub(m: "re.Match") -> str:
        ref = m.group(1).strip()
        if ref in mapping:
            return m.group(0).replace(m.group(1), mapping[ref])
        return m.group(0)

    new_md = ref_re.sub(_sub, md_text)

    # Clean up orphan figures not referenced by the body (MinerU often extracts decorative/sub-figures the body never references)
    kept = {p.name for p in renamed}
    images_dir = base_dir / "images"
    if images_dir.is_dir():
        for f in images_dir.iterdir():
            if f.is_file() and f.name not in kept:
                f.unlink(missing_ok=True)

    return new_md, renamed


def _find_markdown(out_dir: Path, stem: str) -> tuple[str, Path | None]:
    """Find a .md in the output directory (prefer one matching the PDF name, falling back to any .md)."""
    candidates = sorted(out_dir.rglob("*.md"))
    if not candidates:
        return "", None
    exact = [p for p in candidates if p.stem == stem]
    chosen = exact[0] if exact else candidates[0]
    return chosen.read_text(encoding="utf-8", errors="replace"), chosen
