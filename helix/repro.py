"""论文复现规划：显存估算 + 硬件判级 + 复现工作区骨架。

设计原则（与项目一致）：CLI 只做确定性计算（显存数学、判级、生成骨架），
复现方案的深度理解与填充由外部 agent（见 skills/reproduce）完成。

方法论借鉴 ref/deepcode 的 Paper2Code：先抽取实验设置与算法细节，再产出
分段式复现计划（文件结构 / 实现组件 / 验证方案 / 环境依赖 / 分步策略），
但裁剪到"可执行复现方案"层，不自动生成代码。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Config, HardwareProfile

# 每参数字节数：推理权重按精度算
DTYPE_BYTES = {
    "fp32": 4.0, "float32": 4.0,
    "fp16": 2.0, "float16": 2.0, "bf16": 2.0, "bfloat16": 2.0,
    "fp8": 1.0, "int8": 1.0, "8bit": 1.0,
    "int4": 0.5, "4bit": 0.5, "nf4": 0.5,
}

# 判级留出的安全余量：实际可用显存 = 标称 × (1 - HEADROOM)
HEADROOM = 0.10
# CUDA context / 框架常驻开销（GB，每卡）
FRAMEWORK_OVERHEAD_GB = 1.5


def _dtype_bytes(dtype: str) -> float:
    key = (dtype or "fp16").lower().strip()
    if key not in DTYPE_BYTES:
        raise ValueError(f"未知精度 '{dtype}'，支持：{', '.join(sorted(set(DTYPE_BYTES)))}")
    return DTYPE_BYTES[key]


# 常见 dense transformer 的架构经验表（仅参数量已知、未给架构时用于估 KV cache）。
# (params_b, num_layers, hidden)。取最接近者，结果标注"近似"。
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
    """按参数量取最接近的经验架构 (num_layers, hidden)。"""
    best = min(_ARCH_TABLE, key=lambda t: abs(t[0] - params_b))
    return best[1], best[2]


@dataclass
class VramEstimate:
    """一次显存估算结果（GB）。"""

    params_b: float
    dtype: str
    ctx: int
    batch: int
    weights_gb: float
    kv_cache_gb: float
    overhead_gb: float
    total_gb: float
    approximate: bool          # KV 是否用经验架构估的
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
    """估算推理显存（GB）。拆解为 权重 + KV cache + 框架开销。

    - 权重 = params_b × 1e9 × dtype_bytes
    - KV cache = 2(K/V) × num_layers × ctx × batch × hidden × kv_bytes
      （未给架构时按经验表取最接近的 num_layers/hidden，结果标注近似）
    - 框架开销 = 固定常驻（CUDA context 等）
    纯推理估算，不含训练梯度/优化器态。
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
# 硬件判级
# --------------------------------------------------------------------------- #

@dataclass
class FitResult:
    """一个显存需求对一台硬件档的判级结果。"""

    profile: str
    verdict: str               # fits_single / fits_multi_tp / needs_quant / needs_offload / no_fit
    summary: str               # 一句话人读结论
    tp_gpus: int               # 需要的张量并行卡数（1=单卡）
    usable_per_gpu_gb: float
    total_usable_gb: float
    suggestions: list[str]     # 降配阶梯

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
    """给出比当前精度更省的量化档能否装下，作为降配建议。"""
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
    """判断显存需求能否落到一台硬件档上，给判级 + 降配阶梯。"""
    usable_per = profile.vram_gb * (1 - HEADROOM)
    total_usable = usable_per * max(1, profile.num_gpus)
    need = est.total_gb
    name = profile.name

    # 1) 单卡装得下
    if need <= usable_per:
        return FitResult(name, "fits_single",
                         f"单卡装得下（需 {need:.1f}GB ≤ 可用 {usable_per:.1f}GB/卡）",
                         1, usable_per, total_usable, [])

    # 2) 多卡张量并行装得下（权重可切分，按总可用显存判断）
    if need <= total_usable and profile.num_gpus > 1:
        import math
        tp = max(2, math.ceil(need / usable_per))
        tp = min(tp, profile.num_gpus)
        inter = f"（互联 {profile.interconnect}）" if profile.interconnect else ""
        return FitResult(name, "fits_multi_tp",
                         f"需 {tp} 卡张量并行 TP={tp}{inter}（需 {need:.1f}GB，单卡仅 {usable_per:.1f}GB）",
                         tp, usable_per, total_usable, [])

    # 3) 量化后能装下
    ladder = _quant_ladder(est, total_usable)
    quant_ok = any("可装下" in s for s in ladder)
    if quant_ok:
        return FitResult(name, "needs_quant",
                         f"全精度放不下（需 {need:.1f}GB > 可用 {total_usable:.1f}GB），需量化",
                         profile.num_gpus, usable_per, total_usable, ladder)

    # 4) 都不行：offload 或换小模型
    sug = ladder + [
        "offload 权重到 CPU/NVMe（吞吐大幅下降，仅验证正确性时可用）",
        "换更小的同族模型（如 13B→7B→3B）作缩比复现",
        "增加卡数或换更大显存的机器",
    ]
    return FitResult(name, "no_fit" if not ladder else "needs_offload",
                     f"放不下（需 {need:.1f}GB > 可用 {total_usable:.1f}GB），需 offload/换小模型",
                     profile.num_gpus, usable_per, total_usable, sug)


def fit_check_all(est: VramEstimate, cfg: Config) -> list[FitResult]:
    """对 config 里所有硬件档做判级。"""
    return [fit_check(est, p) for p in cfg.hardware_profiles]


# --------------------------------------------------------------------------- #
# 复现工作区骨架
# --------------------------------------------------------------------------- #

def _short_name(title: str) -> str:
    """从论文标题生成简洁的工作区目录名：优先冒号前短标题，否则取前几个词。"""
    import re

    if not title:
        return "untitled"
    head = title.split(":")[0].strip()
    if not (2 <= len(head) <= 30):
        head = " ".join(title.split()[:4])
    return re.sub(r'[ /\\:*?"<>|]+', "_", head).strip("_") or "untitled"


def _first_profile_name(cfg: Config) -> str:
    """复现优先用的硬件档名（config 里排最前的那台）。"""
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
    """原文实验设置骨架（纯参考，对应 DeepCode 的 concept/algorithm analysis）。

    与 plan.md 分工：这里只客观记录"原文怎么做的"，不谈本机怎么跑（那是 plan.md）。
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
    """复现行动方案骨架。推荐方案在最前，与原文对比在最后。

    与 setup.md 分工：setup.md 记录"原文怎么做的"（参考），plan.md 给"本机怎么跑"（行动）。
    不要在这里重抄 setup.md 的原文模型/数据集清单——需要就引用 setup.md。
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
    """在 repro/<方向>/<短名>/（或 draft_notes/）生成 setup.md + plan.md 骨架。

    返回 (工作区目录, 新建文件名列表)。落盘后校验非空，否则抛 OSError。
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
