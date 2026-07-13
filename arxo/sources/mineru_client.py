"""MinerU 云端解析的薄封装。

通过 `mineru-open-api` CLI（`MINERU_TOKEN` 传 key）把 PDF 转成 markdown + 图。
隔离第三方接口细节，便于替换/测试。借鉴 ref/scholaraio 的调用方式。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

MINERU_CLI = "mineru-open-api"
DEFAULT_TIMEOUT = 600  # 秒；云端解析 + 轮询下载


def _find_cli() -> str | None:
    """定位 mineru-open-api CLI：优先当前解释器所在目录（同 venv/bin），再退回 PATH。

    arxo 常以 .venv/bin/arxo 直接调用，子进程 PATH 不含 .venv/bin，
    单靠 shutil.which 会漏掉同 venv 里的 CLI。
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
    """调 MinerU 云端把 PDF 转 markdown。返回 (markdown 文本, 图片路径列表)。

    失败（未装 CLI / 网络 / 非零退出）抛 RuntimeError，由上层回退。
    """
    cli = _find_cli()
    if cli is None:
        raise RuntimeError(f"未找到 {MINERU_CLI} CLI，安装：uv pip install 'arxo[fulltext]'")

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

    # 把哈希名图片按正文出现顺序重命名为 fig1/fig2…，并同步改写正文引用
    md_text, renamed = rename_images_sequentially(md_text, md_path.parent)

    # 删除 MinerU 原始 .md（引用旧哈希名，留着会成坏链）；只保留调用方写的 fulltext.md
    if md_path.name != "fulltext.md":
        md_path.unlink(missing_ok=True)

    return md_text, renamed


IMG_REF_RE = None  # 延迟编译，见 rename_images_sequentially


def rename_images_sequentially(md_text: str, base_dir: Path) -> tuple[str, list[Path]]:
    """把 md 引用的图片按出现顺序重命名为 images/figN.<ext>，改写引用。

    返回 (改写后的 md, 重命名后的图片路径列表)。base_dir 是 md 所在目录。
    只处理指向本地相对路径的 ![](...) 引用（跳过 http/绝对路径）。
    """
    import re

    ref_re = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
    order: list[str] = []  # 按首次出现去重的原始引用路径
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

    # 清理未被正文引用的孤儿图（MinerU 常抽出装饰/子图，正文并不引用）
    kept = {p.name for p in renamed}
    images_dir = base_dir / "images"
    if images_dir.is_dir():
        for f in images_dir.iterdir():
            if f.is_file() and f.name not in kept:
                f.unlink(missing_ok=True)

    return new_md, renamed


def _find_markdown(out_dir: Path, stem: str) -> tuple[str, Path | None]:
    """在输出目录找 .md（优先与 PDF 同名，退化到任意 .md）。"""
    candidates = sorted(out_dir.rglob("*.md"))
    if not candidates:
        return "", None
    exact = [p for p in candidates if p.stem == stem]
    chosen = exact[0] if exact else candidates[0]
    return chosen.read_text(encoding="utf-8", errors="replace"), chosen
