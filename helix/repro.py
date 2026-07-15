"""Paper reproduction planning: VRAM estimation + hardware tiering + reproduction workspace skeleton.

Design principle (consistent with the project): the CLI only does deterministic computation
(VRAM math, tiering, skeleton generation); deep understanding and filling in the reproduction
plan is done by an external agent (see skills/reproduce).

Methodology borrows from ref/deepcode's Paper2Code: first extract the experimental setup and
algorithm details, then produce a segmented reproduction plan (file structure / implementation
components / validation plan / environment dependencies / step-by-step strategy), but trimmed to
the "executable reproduction plan" layer without auto-generating code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Config, HardwareProfile

# Bytes per parameter: inference weights computed by precision
DTYPE_BYTES = {
    "fp32": 4.0, "float32": 4.0,
    "fp16": 2.0, "float16": 2.0, "bf16": 2.0, "bfloat16": 2.0,
    "fp8": 1.0, "int8": 1.0, "8bit": 1.0,
    "int4": 0.5, "4bit": 0.5, "nf4": 0.5,
}

# Safety margin reserved for tiering: actual usable VRAM = nominal × (1 - HEADROOM)
HEADROOM = 0.10
# CUDA context / framework resident overhead (GB, per GPU)
FRAMEWORK_OVERHEAD_GB = 1.5


def _dtype_bytes(dtype: str) -> float:
    key = (dtype or "fp16").lower().strip()
    if key not in DTYPE_BYTES:
        raise ValueError(f"未知精度 '{dtype}'，支持：{', '.join(sorted(set(DTYPE_BYTES)))}")
    return DTYPE_BYTES[key]


# Empirical architecture table for common dense transformers (used to estimate KV cache when only
# param count is known and no architecture is given). (params_b, num_layers, hidden). Pick the
# closest; results are marked "approximate".
_ARCH_TABLE = [
    (1.0, 24, 2048),
    (3.0, 32, 2560),
    (7.0, 32, 4096),
    (13.0, 40, 5120),
    (30.0, 60, 6656),
    (70.0, 80, 8192),
    (235.0, 94, 12288),
]


def _infer_arch(params_b: float) -> tuple[int, int]:
    """Pick the closest empirical architecture (num_layers, hidden) by param count."""
    best = min(_ARCH_TABLE, key=lambda t: abs(t[0] - params_b))
    return best[1], best[2]


@dataclass
class VramEstimate:
    """Result of one VRAM estimation (GB)."""

    params_b: float
    dtype: str
    ctx: int
    batch: int
    weights_gb: float
    kv_cache_gb: float
    overhead_gb: float
    total_gb: float
    approximate: bool          # whether KV was estimated using the empirical architecture
    num_layers: int
    hidden: int

    def to_dict(self) -> dict:
        return {
            "params_b": self.params_b,
            "dtype": self.dtype,
            "ctx": self.ctx,
            "batch": self.batch,
            "weights_gb": round(self.weights_gb, 2),
            "kv_cache_gb": round(self.kv_cache_gb, 2),
            "overhead_gb": round(self.overhead_gb, 2),
            "total_gb": round(self.total_gb, 2),
            "approximate": self.approximate,
            "num_layers": self.num_layers,
            "hidden": self.hidden,
        }


def estimate_vram(
    params_b: float,
    dtype: str = "fp16",
    ctx: int = 2048,
    batch: int = 1,
    *,
    num_layers: int | None = None,
    hidden: int | None = None,
    kv_dtype: str | None = None,
) -> VramEstimate:
    """Estimate inference VRAM (GB). Broken down into weights + KV cache + framework overhead.

    - weights = params_b × 1e9 × dtype_bytes
    - KV cache = 2(K/V) × num_layers × ctx × batch × hidden × kv_bytes
      (when no architecture is given, use the closest num_layers/hidden from the empirical
      table; the result is marked approximate)
    - framework overhead = fixed resident (CUDA context, etc.)
    Pure inference estimate, excluding training gradients/optimizer state.
    """
    if params_b <= 0:
        raise ValueError("params_b 必须为正（单位：十亿参数，如 7 表示 7B）")
    w_bytes = _dtype_bytes(dtype)
    weights_gb = params_b * 1e9 * w_bytes / (1024 ** 3)

    approximate = num_layers is None or hidden is None
    if approximate:
        il, ih = _infer_arch(params_b)
        num_layers = num_layers or il
        hidden = hidden or ih
    kv_bytes = _dtype_bytes(kv_dtype) if kv_dtype else min(w_bytes, 2.0)
    kv_cache_gb = 2 * num_layers * ctx * batch * hidden * kv_bytes / (1024 ** 3)

    overhead_gb = FRAMEWORK_OVERHEAD_GB
    total_gb = weights_gb + kv_cache_gb + overhead_gb
    return VramEstimate(
        params_b=params_b, dtype=dtype.lower(), ctx=ctx, batch=batch,
        weights_gb=weights_gb, kv_cache_gb=kv_cache_gb, overhead_gb=overhead_gb,
        total_gb=total_gb, approximate=approximate,
        num_layers=num_layers, hidden=hidden,
    )


# --------------------------------------------------------------------------- #
# Hardware tiering
# --------------------------------------------------------------------------- #

@dataclass
class FitResult:
    """Tiering result of one VRAM requirement against one hardware profile."""

    profile: str
    verdict: str               # fits_single / fits_multi_tp / needs_quant / needs_offload / no_fit
    summary: str               # one-line human-readable conclusion
    tp_gpus: int               # number of tensor-parallel GPUs needed (1=single GPU)
    usable_per_gpu_gb: float
    total_usable_gb: float
    suggestions: list[str]     # downgrade ladder

    def to_dict(self) -> dict:
        return {
            "profile": self.profile,
            "verdict": self.verdict,
            "summary": self.summary,
            "tp_gpus": self.tp_gpus,
            "usable_per_gpu_gb": round(self.usable_per_gpu_gb, 2),
            "total_usable_gb": round(self.total_usable_gb, 2),
            "suggestions": self.suggestions,
        }


def _quant_ladder(est: VramEstimate, usable_total_gb: float) -> list[str]:
    """Report whether quantization tiers more economical than the current precision would fit, as downgrade suggestions."""
    order = [("int8", 1.0), ("int4", 0.5)]
    cur = _dtype_bytes(est.dtype)
    out: list[str] = []
    for name, b in order:
        if b >= cur:
            continue
        q = estimate_vram(est.params_b, name, est.ctx, est.batch,
                          num_layers=est.num_layers, hidden=est.hidden)
        verb = "可装下" if q.total_gb <= usable_total_gb else "仍不够"
        out.append(f"{name} 量化后约 {q.total_gb:.1f}GB（{verb}）")
    return out


def fit_check(est: VramEstimate, profile: HardwareProfile) -> FitResult:
    """Determine whether a VRAM requirement fits on one hardware profile; give a tier + downgrade ladder."""
    usable_per = profile.vram_gb * (1 - HEADROOM)
    total_usable = usable_per * max(1, profile.num_gpus)
    need = est.total_gb
    name = profile.name

    # 1) Fits on a single GPU
    if need <= usable_per:
        return FitResult(name, "fits_single",
                         f"单卡装得下（需 {need:.1f}GB ≤ 可用 {usable_per:.1f}GB/卡）",
                         1, usable_per, total_usable, [])

    # 2) Fits with multi-GPU tensor parallelism (weights are splittable, judged by total usable VRAM)
    if need <= total_usable and profile.num_gpus > 1:
        import math
        tp = max(2, math.ceil(need / usable_per))
        tp = min(tp, profile.num_gpus)
        inter = f"（互联 {profile.interconnect}）" if profile.interconnect else ""
        return FitResult(name, "fits_multi_tp",
                         f"需 {tp} 卡张量并行 TP={tp}{inter}（需 {need:.1f}GB，单卡仅 {usable_per:.1f}GB）",
                         tp, usable_per, total_usable, [])

    # 3) Fits after quantization
    ladder = _quant_ladder(est, total_usable)
    quant_ok = any("可装下" in s for s in ladder)
    if quant_ok:
        return FitResult(name, "needs_quant",
                         f"全精度放不下（需 {need:.1f}GB > 可用 {total_usable:.1f}GB），需量化",
                         profile.num_gpus, usable_per, total_usable, ladder)

    # 4) None work: offload or switch to a smaller model
    sug = ladder + [
        "offload 权重到 CPU/NVMe（吞吐大幅下降，仅验证正确性时可用）",
        "换更小的同族模型（如 13B→7B→3B）作缩比复现",
        "增加卡数或换更大显存的机器",
    ]
    return FitResult(name, "no_fit" if not ladder else "needs_offload",
                     f"放不下（需 {need:.1f}GB > 可用 {total_usable:.1f}GB），需 offload/换小模型",
                     profile.num_gpus, usable_per, total_usable, sug)


def fit_check_all(est: VramEstimate, cfg: Config) -> list[FitResult]:
    """Tier against all hardware profiles in config."""
    return [fit_check(est, p) for p in cfg.hardware_profiles]


# --------------------------------------------------------------------------- #
# Reproduction workspace skeleton
# --------------------------------------------------------------------------- #

def short_name(title: str) -> str:
    """Generate a concise workspace directory name from a paper title: prefer the short title before the colon, else take the first few words."""
    import re

    if not title:
        return "untitled"
    head = title.split(":")[0].strip()
    if not (2 <= len(head) <= 30):
        head = " ".join(title.split()[:4])
    return re.sub(r'[ /\\:*?"<>|]+', "_", head).strip("_") or "untitled"


def _first_profile_name(cfg: Config) -> str:
    """Name of the preferred hardware profile for reproduction (the first one in config)."""
    return cfg.hardware_profiles[0].name if cfg.hardware_profiles else "（未配硬件档）"


def _profile_lines(cfg: Config) -> str:
    if not cfg.hardware_profiles:
        return "- （config 未配 hardware_profiles，先在 config.yaml 加机器）"
    lines = []
    for p in cfg.hardware_profiles:
        lines.append(f"- **{p.name}**：{p.gpu_model} ×{p.num_gpus}，单卡 {p.vram_gb:.0f}GB"
                     f"（合计 {p.total_vram_gb:.0f}GB，{p.interconnect or '互联未标'}）")
    return "\n".join(lines)


def build_setup_skeleton(title: str, note_rel: str, cfg: Config) -> str:
    """Skeleton for the paper's experimental setup (pure reference, corresponds to DeepCode's concept/algorithm analysis).

    Division of labor with plan.md: this only objectively records "how the paper did it", not how to run it locally (that's plan.md).
    """
    return f"""# 原文实验设置：{title}

> 来源笔记：[[{note_rel}]]
> 本文件只客观记录**原文怎么做的**（复现方案见同目录 plan.md）。只写论文里有的，推断要标注。

## 原文实验环境
<!-- agent: 原文用的 GPU 型号/卡数、互联、框架（vLLM/SGLang/…）、CUDA/Python 版本 -->

## 原文模型
<!-- agent: 模型名与规模（参数量）、精度（fp16/fp8/…）、是否开源可下载、HF 名称 -->

## 原文数据集 / 工作流
<!-- agent: 数据集名、规模、划分、下载方式；有无子集可缩比（这条信息 plan.md 会用到） -->

## 原文评测指标 与 baseline
<!-- agent: 指标定义与计算方式、对齐原文表几、baseline 有哪些（开源/需自复现） -->

## 原文关键超参
<!-- agent: batch/group size、温度、序列长度、学习率等复现必需的配置值 -->

## 代码可得性
<!-- agent: 官方仓库链接 / 无 / 第三方复现；许可证。是判可复现性分级的关键 -->
"""


def build_plan_skeleton(title: str, note_rel: str, cfg: Config) -> str:
    """Skeleton for the reproduction action plan. Recommended plan first, comparison with the paper last.

    Division of labor with setup.md: setup.md records "how the paper did it" (reference), plan.md gives "how to run it locally" (action).
    Don't re-copy setup.md's original model/dataset lists here -- reference setup.md if needed.
    """
    return f"""# 复现方案：{title}

> 来源笔记：[[{note_rel}]] ｜ 原文实验设置见同目录 setup.md（本文件只讲"本机怎么跑"）

## 1. 推荐方案（先看这里）
<!-- agent: 一句话给结论——用哪台机、哪个模型、什么精度/并行、跑哪个实验。让用户不用往下翻就能开跑。
优先用 config 里排在最前的硬件档（当前：{_first_profile_name(cfg)}）。例：
「在 a100-8x40g 上用 TP8 跑 Qwen3-32B-fp8，复现 coding serving 吞吐；显存 X GB/卡，装得下。」-->

**推荐配置**

| 项 | 选择 | 理由 |
|---|---|---|
| 硬件档 | <!-- agent: 优先 {_first_profile_name(cfg)} --> | |
| 模型 | | |
| 精度 / 并行 | | 张量并行 TP=? |
| 数据集 / 工作流 | | 子集规模 |
| 复现哪个实验 | | 对齐原文表/图几 |

**显存核对**（跑一下贴结果）：
```bash
uv run helix repro vram --params <B> --dtype <精度> --ctx <长度> --batch <N> [--layers L --hidden H]
```
<!-- agent: 贴判级结论：fits_single / fits_multi_tp(TP=?) / needs_quant… -->

## 2. 分步执行命令
<!-- agent: 从建环境到出指标的可复制命令，按推荐方案写实：
```bash
# 1. 建环境 + clone 官方仓库
# 2. 下模型/数据（HF 命令）
# 3. 起服务/跑复现（带上 TP 度、并发等参数）
# 4. 评测出指标
```
-->

## 3. 实现组件
<!-- agent: 要跑通/验证的核心算法/模块——做什么、对应论文哪节/哪个公式、关键超参。
用官方仓库时说清"复用什么、要对齐哪些超参"，别重写。 -->

## 4. 验证方案与预期结果
<!-- agent: 复现哪个实验、数据集子集、算什么指标、预期数值区间（对齐原文表几）、
验收标准（如"吞吐提升在原文 ±X% 内即算成功"；缩比复现则"看相对趋势不看绝对倍数"）。 -->

## 5. 可复现性分级
<!-- agent: 选 A/B/C 并说明理由
- **A 端到端可复现**：代码开源 + 模型数据可得 + 硬件可满足（或可降配）
- **B 缩比/局部可复现**：核心机制可复现，但原模型/集群超硬件，用小模型或子现象替代
- **C 难以复现**：无代码/依赖未开源组件/需超大集群，只能验证某个可测子现象 -->

## 6. 与原文实验的差异（对比在最后）
可用硬件档：
{_profile_lines(cfg)}

<!-- agent: 表格对比 原文设置 vs 本机方案，讲清哪些是等价复现、哪些是缩比降配、哪些复现不了。
对放不下的模型给降配阶梯：换小模型 → int8/int4 量化 → 多卡 TP → offload。 -->

| 维度 | 原文（见 setup.md） | 本机方案 | 差异说明 |
|---|---|---|---|
| 硬件 | | | |
| 模型 / 规模 | | | |
| 精度 / 并行 | | | |
| 数据集规模 | | | |
| 预期结果 | | | 绝对值 vs 相对趋势 |
"""


def build_repro_workspace(
    title: str, note_rel: str, domain: str, short_name: str, cfg: Config,
    *, draft: bool = False, overwrite: bool = False,
) -> tuple[Path, list[str]]:
    """Generate setup.md + plan.md skeletons under repro/<domain>/<short_name>/ (or draft_notes/).

    Returns (workspace dir, list of newly created filenames). Verifies non-empty after persisting, else raises OSError.
    """
    ws = cfg.repro_workspace_path(domain, short_name, draft=draft)
    ws.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    for fname, builder in (("setup.md", build_setup_skeleton), ("plan.md", build_plan_skeleton)):
        fpath = ws / fname
        if fpath.exists() and not overwrite:
            continue
        fpath.write_text(builder(title, note_rel, cfg), encoding="utf-8")
        if not fpath.exists() or fpath.stat().st_size == 0:
            raise OSError(f"复现骨架写入失败，文件未落盘：{fpath}")
        created.append(fname)
    return ws, created
