"""MinerU 云端解析的薄封装。

通过 `mineru-open-api` CLI（`MINERU_TOKEN` 传 key）把 PDF 转成 markdown + 图。
隔离第三方接口细节，便于替换/测试。借鉴 ref/scholaraio 的调用方式。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

MINERU_CLI = "mineru-open-api"
DEFAULT_TIMEOUT = 600  # 秒；云端解析 + 轮询下载


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
    cli = shutil.which(MINERU_CLI)
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
    images = _find_images(out_dir)
    return md_text, images


def _find_markdown(out_dir: Path, stem: str) -> tuple[str, Path | None]:
    """在输出目录找 .md（优先与 PDF 同名，退化到任意 .md）。"""
    candidates = sorted(out_dir.rglob("*.md"))
    if not candidates:
        return "", None
    exact = [p for p in candidates if p.stem == stem]
    chosen = exact[0] if exact else candidates[0]
    return chosen.read_text(encoding="utf-8", errors="replace"), chosen


def _find_images(out_dir: Path) -> list[Path]:
    exts = {".png", ".jpg", ".jpeg"}
    return sorted(p for p in out_dir.rglob("*") if p.suffix.lower() in exts)
