"""全文抓取：PDF 下载、arXiv 源码包高清图提取、MinerU 云端解析。

- download_pdf：从 arxiv.org/pdf 下 PDF
- download_source_figures：下 arxiv.org/e-print 源码 tar.gz，取原始高清图（最清晰）
- mineru_parse：调 MinerU 云端 API 把 PDF 转 markdown（需 api_key）

移植自 ref/evil-read-arxiv/extract-paper-images（源码抽图）与
ref/scholaraio/.../providers/mineru.py（云端解析）。
"""

from __future__ import annotations

import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

# 源码包里常见的图片目录名（小写匹配，含单复数）
FIGURE_DIR_NAMES = {"pics", "pic", "figures", "figure", "fig", "figs", "images", "image", "img", "imgs", "plots", "graphics"}
IMG_EXTS = {".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg"}


def _download(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "helix/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def download_pdf(arxiv_id: str, out_dir: Path) -> Path:
    """下载 PDF 到 out_dir/<id>.pdf。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    data = _download(url)
    path = out_dir / f"{arxiv_id.replace('/', '_')}.pdf"
    path.write_bytes(data)
    return path


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    """安全解包：跳过绝对路径、.. 穿越、符号链接。"""
    safe = []
    for m in tar.getmembers():
        if m.name.startswith("/") or ".." in Path(m.name).parts:
            continue
        if m.issym() or m.islnk():
            continue
        safe.append(m)
    tar.extractall(path=dest, members=safe)


def download_source_figures(arxiv_id: str, out_dir: Path) -> list[Path]:
    """下 arXiv 源码包，提取原始高清图到 out_dir。返回图片路径列表（已按名排序）。"""
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
            return []  # 不是 tar.gz（可能是单文件），交给调用方回退

        found = _collect_figures(tmp_path)
        used: set[str] = set()
        for src in found:
            # 保留原始文件名（method/teaser 比 fig1 更有意义），冲突时加序号
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
    """在解包目录里找图片：递归匹配常见图目录（大小写不敏感），退化到根目录。过滤 logo/icon。"""
    found: list[Path] = []
    seen: set[str] = set()
    # 递归找名字匹配的图目录（如 figure/ figures/ pics/，任意深度）
    for d in sorted(p for p in root.rglob("*") if p.is_dir()):
        if d.name.lower() in FIGURE_DIR_NAMES:
            for f in sorted(d.iterdir()):
                if f.is_file() and f.suffix.lower() in IMG_EXTS and f.name not in seen:
                    seen.add(f.name)
                    found.append(f)
    if not found:
        # 根目录直接扫图（含位图，过滤 logo/icon）
        for f in sorted(root.rglob("*")):
            if f.is_file() and f.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                low = f.name.lower()
                if "logo" not in low and "icon" not in low and f.name not in seen:
                    seen.add(f.name)
                    found.append(f)
    return found


def mineru_parse(pdf_path: Path, api_key: str, out_dir: Path) -> tuple[str, list[Path]]:
    """调 MinerU 云端把 PDF 转 markdown。返回 (markdown 文本, 图片路径列表)。

    需要 mineru-open-api（可选依赖）。未安装或无 key 时抛 RuntimeError，
    由调用方回退到源码图 + 摘要。
    """
    if not api_key:
        raise RuntimeError("未配置 MinerU api_key（config.yaml: mineru_api_key 或环境变量 MINERU_API_KEY）")
    try:
        import mineru_open_api  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "未安装 mineru-open-api，无法用 MinerU 云端解析。安装：uv pip install 'helix[fulltext]'"
        ) from e

    # 具体调用交由 mineru-open-api 完成：上传 PDF → 轮询 → 下载 zip（含 md + images）
    from .mineru_client import parse_pdf_cloud  # 薄封装，隔离第三方接口细节

    return parse_pdf_cloud(pdf_path, api_key=api_key, out_dir=out_dir)
