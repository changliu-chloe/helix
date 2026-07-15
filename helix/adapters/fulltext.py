"""Full-text fetching: PDF download, high-res figure extraction from arXiv source bundles, MinerU cloud parsing.

- download_pdf: download the PDF from arxiv.org/pdf
- download_source_figures: download the arxiv.org/e-print source tar.gz and take the original high-res figures (clearest)
- mineru_parse: call the MinerU cloud API to convert a PDF to markdown (requires api_key)

Ported from ref/evil-read-arxiv/extract-paper-images (source figure extraction) and
ref/scholaraio/.../providers/mineru.py (cloud parsing).
"""

from __future__ import annotations

import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

# Common image directory names in source bundles (lowercase match, singular and plural)
FIGURE_DIR_NAMES = {"pics", "pic", "figures", "figure", "fig", "figs", "images", "image", "img", "imgs", "plots", "graphics"}
IMG_EXTS = {".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg"}


def _download(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "helix/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def download_pdf(arxiv_id: str, out_dir: Path) -> Path:
    """Download the PDF to out_dir/<id>.pdf."""
    out_dir.mkdir(parents=True, exist_ok=True)
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    data = _download(url)
    path = out_dir / f"{arxiv_id.replace('/', '_')}.pdf"
    path.write_bytes(data)
    return path


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    """Safe extraction: skip absolute paths, .. traversal, and symlinks."""
    safe = []
    for m in tar.getmembers():
        if m.name.startswith("/") or ".." in Path(m.name).parts:
            continue
        if m.issym() or m.islnk():
            continue
        safe.append(m)
    tar.extractall(path=dest, members=safe)


def download_source_figures(arxiv_id: str, out_dir: Path) -> list[Path]:
    """Download the arXiv source bundle and extract original high-res figures to out_dir. Returns a list of figure paths (sorted by name)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    url = f"https://arxiv.org/e-print/{arxiv_id}"
    data = _download(url)

    figures: list[Path] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        tar_path = tmp_path / f"{arxiv_id.replace('/', '_')}.tar.gz"
        tar_path.write_bytes(data)
        try:
            with tarfile.open(tar_path, "r:gz") as tar:
                _safe_extract(tar, tmp_path)
        except (tarfile.TarError, OSError):
            return []  # not a tar.gz (possibly a single file); let the caller fall back

        found = _collect_figures(tmp_path)
        used: set[str] = set()
        for src in found:
            # Keep the original filename (method/teaser is more meaningful than fig1); add a suffix on conflict
            name = src.name
            if name in used:
                name = f"{src.stem}_{len(used)}{src.suffix.lower()}"
            used.add(name)
            dst = out_dir / name
            try:
                shutil.copy2(src, dst)
                figures.append(dst)
            except OSError:
                continue
    return figures


def _collect_figures(root: Path) -> list[Path]:
    """Find figures in the extracted directory: recursively match common figure dirs (case-insensitive), falling back to the root. Filter out logo/icon."""
    found: list[Path] = []
    seen: set[str] = set()
    # Recursively find figure dirs matching by name (e.g. figure/ figures/ pics/, at any depth)
    for d in sorted(p for p in root.rglob("*") if p.is_dir()):
        if d.name.lower() in FIGURE_DIR_NAMES:
            for f in sorted(d.iterdir()):
                if f.is_file() and f.suffix.lower() in IMG_EXTS and f.name not in seen:
                    seen.add(f.name)
                    found.append(f)
    if not found:
        # Scan figures directly in the root (including bitmaps, filtering logo/icon)
        for f in sorted(root.rglob("*")):
            if f.is_file() and f.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                low = f.name.lower()
                if "logo" not in low and "icon" not in low and f.name not in seen:
                    seen.add(f.name)
                    found.append(f)
    return found


def mineru_parse(pdf_path: Path, api_key: str, out_dir: Path) -> tuple[str, list[Path]]:
    """Call MinerU cloud to convert a PDF to markdown. Returns (markdown text, list of figure paths).

    Requires mineru-open-api (optional dependency). Raises RuntimeError when not
    installed or no key is present, so the caller falls back to source figures + abstract.
    """
    if not api_key:
        raise RuntimeError("未配置 MinerU api_key（config.yaml: mineru_api_key 或环境变量 MINERU_API_KEY）")
    try:
        import mineru_open_api  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "未安装 mineru-open-api，无法用 MinerU 云端解析。安装：uv pip install 'helix[fulltext]'"
        ) from e

    # The actual call is delegated to mineru-open-api: upload PDF -> poll -> download zip (contains md + images)
    from .mineru_client import parse_pdf_cloud  # thin wrapper, isolates third-party interface details

    return parse_pdf_cloud(pdf_path, api_key=api_key, out_dir=out_dir)
