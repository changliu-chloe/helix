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

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

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

# Result artifacts with these tokens are treated as transient and can be cleaned at the end of
# an experiment round. Keep the rule conservative: official result files should use stable names.
TRANSIENT_ARTIFACT_RE = re.compile(
    r"(^|[^a-z0-9])(smoke|tmp|temp|trial|dryrun|dry-run|debug|warmup)([^a-z0-9]|$)",
    re.IGNORECASE,
)
PROTECTED_RESULT_FILENAMES = {"index.md", ".gitkeep"}


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
    """Concise workspace directory name from a paper title (shared short-title logic)."""
    from . import naming

    return naming.short_title(title)


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

## 论文结构与方法拆解
<!-- agent: paper-to-setup 从深读笔记和 fulltext.md 抽取：
- paper structure map：论文主张、方法章节、实验章节、关键表图
- method decomposition：核心模块、模块交互、数据流
只写原文事实；论文未给出/推断/需要用户确认的内容要标注来源与置信度。 -->

## 原文算法 / 公式 / 训练过程
<!-- agent: 伪代码、公式、损失函数、优化过程、训练/推理流程、关键实现细节。
标明对应论文章节、公式号、算法框或图表；不要把本机实现方案写在这里。 -->

## 原文实验环境
<!-- agent: 原文用的 GPU 型号/卡数、互联、框架（vLLM/SGLang/…）、CUDA/Python 版本、依赖版本 -->

## 原文模型
<!-- agent: 模型名与规模（参数量）、精度（fp16/fp8/…）、是否开源可下载、HF 名称 -->

## 原文数据集 / 工作流
<!-- agent: 数据集名、规模、划分、下载方式、预处理流程；有无子集可缩比（这条信息 plan.md 会用到） -->

## 原文评测指标 与 baseline
<!-- agent: 指标定义与计算方式、对齐原文表几、baseline 有哪些（开源/需自复现）、是否可直接引用官方结果 -->

## 原文关键超参
<!-- agent: batch/group size、温度、序列长度、学习率等复现必需的配置值 -->

## 代码可得性
<!-- agent: 官方仓库链接 / 无 / 第三方复现；许可证。是判可复现性分级的关键 -->
"""


def build_mine_plan_skeleton(title: str, note_rel: str, cfg: Config) -> str:
    """Skeleton for a user's own experiment direction (type:mine).

    plan.md stays at the direction level. Concrete runs live in sub_experiments/<slug>/ so
    each user-driven sub-experiment has its own setup, config, and results.
    """
    ref = f"> 对标/借鉴：[[{note_rel}]]\n" if note_rel else ""
    return f"""# 实验方向：{title}

{ref}> 这是我自己的实验（type:mine），从 hypothesis-to-plan 开始。本文件只管大方向、总假设和证据口径；每个具体子实验放到 `sub_experiments/<slug>/`，不要把不同轮次的设置和结果混在顶层。

## 1. 研究问题 / 总假设
<!-- agent: hypothesis：这条研究线要验证什么总假设/claim、回答什么问题；和对标论文的关系（改进/对比/消融）。
预期必须可证伪。具体 baseline、变量、超参和命令写进对应子实验的 setup.md/config.yaml。 -->

## 2. 总体方法边界
<!-- agent: 只写跨子实验都成立的设计约束、不可变控制条件、核心 baseline 候选和验收口径。
如果某个设置只服务一轮实验，放进 sub_experiments/<slug>/setup.md，不写在这里。 -->

## 3. 可用能力与生成方式
可用硬件档：
{_profile_lines(cfg)}

<!-- agent: 子实验设置可以由用户需求触发，也可以调用 helix CLI、相关 skill 或 LLM 生成。
记录可复用的非敏感上下文：模型/数据/cache 路径、常用评测脚本、允许使用的 skill、禁止变动的环境边界。 -->

```bash
uv run helix exp vram --params <B> --dtype <精度> --ctx <长度> --batch <N> [--layers L --hidden H]
uv run helix exp sub <本工作区> --name "<子实验短名>"
```

## 4. 子实验索引
<!-- agent: 每新增一轮具体实验，先 `helix exp sub ...` 建隔离目录，再把本表补一行。
不要把旧轮次文件搬进 archive；从一开始就把 setup/config/results 放在对应子实验目录。 -->

| 子实验 | 用户需求 / 问题 | 状态 | 关键结果 | 下一步 |
|---|---|---|---|---|
| `sub_experiments/<slug>/` | | planning | | |

## 5. 结果到 claim / 下一轮决策（汇总证据）
<!-- agent: result-to-claim 的总口径：汇总各子实验 results/index.md 后，判断 supported_claim、
unsupported_claim、evidence_strength 和 next_action。单轮结果先写在子实验内，顶层 results/index.md 只放汇总。 -->
"""


def build_sub_experiments_readme(title: str) -> str:
    """Guide for user-driven sub-experiment folders under a type:mine workspace."""
    return f"""# 子实验目录：{title}

每个具体子实验都新建一个独立目录：

```text
sub_experiments/<slug>/
  setup.md        # 本轮用户需求、baseline、变量、命令和验收标准
  config.yaml     # 本轮结构化配置；可由 CLI / skill / LLM 生成后人工确认
  results/
    index.md      # 本轮结果总结
    metrics/      # 原始指标
    plots/        # 图
    tables/       # 表
```

烟测、调试、临时试跑产物请在文件名或目录名里带 `smoke` / `tmp` / `debug` / `trial` / `dryrun` / `warmup`，
例如 `results/metrics/smoke_latency.json`。实验结束后先预览再清理：

```bash
uv run helix exp clean sub_experiments/<slug>
uv run helix exp clean sub_experiments/<slug> --yes
```

不要把一轮实验结束后的文件再搬进 archive。新需求来时直接创建新 `<slug>`，让设置、配置和结果从一开始就隔离。
"""


def sub_experiment_slug(name: str) -> str:
    """Filesystem-safe sub-experiment folder name."""
    from . import naming

    return naming.safe_filename(name, "sub_experiment")


def build_sub_experiment_setup_skeleton(title: str, slug: str) -> str:
    """Skeleton for one concrete user-driven sub-experiment."""
    return f"""# 子实验设置：{title}

> 所属方向：`../../plan.md` ｜ 配置：`config.yaml` ｜ 结果：`results/index.md`

## 1. 用户需求 / 触发问题
<!-- agent: 这轮具体要回答什么问题；为什么需要新建子实验而不是复用旧目录。 -->

## 2. 假设、baseline 与变量
<!-- agent: 写清本轮 hypothesis、baseline、自变量、因变量、控制变量、失败判据。 -->

## 3. 设置生成方式
<!-- agent: 本轮设置从哪里来：用户指定 / helix CLI / reproduce skill / 其他 skill / LLM 生成。
若调用 LLM 或 skill 生成配置，记录输入摘要和人工确认点；不要写 secret。 -->

## 4. 实现组件与文件结构
<!-- agent: 本轮需要改哪些代码、脚本、配置；核心算法/数据/评测模块分别落在哪。 -->

## 5. 硬件、环境与分步命令
<!-- agent: 从建环境到出指标的可复制命令。先烟测，再全量；长实验写预计时长和 tmux 会话名。 -->
```bash
# uv run helix exp vram ...
# uv run helix exp start ../.. -m "feat: {slug} ..."
# uv run helix exp run ../.. --cmd "<命令>" --session "helix-{slug}-run"
```

## 6. 评测与验收标准
<!-- agent: 指标、baseline 对比、预期区间、通过/失败标准，以及哪些结果支持/不支持本轮假设。 -->

## 7. 收尾清理
<!-- agent: 实验结束后先整理结果目录。烟测/调试/临时试跑产物命名带 smoke/tmp/debug/trial/dryrun/warmup，
正式结果用稳定名称。先 `uv run helix exp clean <本子实验目录>` 预览，再经用户确认后加 `--yes` 删除。 -->
"""


def build_sub_experiment_config_skeleton(title: str, slug: str) -> str:
    """Structured, non-sensitive config template for one sub-experiment."""
    spec = {
        "name": slug,
        "title": title,
        "status": "planning",
        "generated_by": {
            "source": "",  # user | helix-cli | skill | llm | mixed
            "details": "",
            "confirmed_by_user": False,
        },
        "hypothesis": "",
        "baseline": [],
        "variables": {
            "independent": [],
            "dependent": [],
            "controlled": [],
        },
        "metrics": [],
        "datasets": {
            "raw": "",
            "processed": "",
        },
        "commands": {
            "smoke": "",
            "full": "",
            "analyze": "",
            "cleanup_preview": "uv run helix exp clean <sub_experiment_dir>",
            "cleanup_confirmed": "uv run helix exp clean <sub_experiment_dir> --yes",
        },
        "artifacts": {
            "metrics": "results/metrics/",
            "plots": "results/plots/",
            "tables": "results/tables/",
        },
        "notes": [],
    }
    return "# 本文件只写非敏感实验配置；token、密码、私有下载链接不要放进来。\n" + yaml.safe_dump(
        spec, allow_unicode=True, sort_keys=False, default_flow_style=False,
    )


def build_sub_experiment_results_index(title: str, slug: str) -> str:
    """Curated result note for one sub-experiment."""
    fm = {
        "title": f"{title} · 子实验结果",
        "type": "mine",
        "scope": "sub_experiment",
        "sub_experiment": slug,
        "tags": ["helix", "experiment", "mine", "sub_experiment"],
        "links": ["../../plan.md"],
    }
    body = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f"""---
{body}---
# 子实验结果：{title}

> 设置：`../setup.md` ｜ 配置：`../config.yaml` ｜ 原始数据在 `metrics/`、`plots/`、`tables/`

## 结果概览
<!-- agent: 把本子实验 results/ 下的原始指标/图/表蒸馏成一句话结论 + 小表。 -->

## 与 baseline / 验收标准的对比
<!-- agent: 对齐 setup.md 的指标和验收标准，说明是否支持本轮 hypothesis。 -->

## 暴露的问题与混杂因素
<!-- agent: 实现、运行、评测过程中发现的问题；没有就写「暂无」。 -->

## 对顶层 claim 的影响
<!-- agent: 这轮结果给 ../../results/index.md 的 supported_claim / unsupported_claim 提供什么证据。 -->
"""


def build_plan_skeleton(title: str, note_rel: str, cfg: Config) -> str:
    """Skeleton for the reproduction action plan. Recommended plan first, comparison with the paper last.

    Division of labor with setup.md: setup.md records "how the paper did it" (reference), plan.md gives "how to run it locally" (action).
    Don't re-copy setup.md's original model/dataset lists here -- reference setup.md if needed.
    """
    return f"""# 复现方案：{title}

> 来源笔记：[[{note_rel}]] ｜ 原文实验设置见同目录 setup.md（本文件只讲"本机怎么跑"）

<!-- agent: setup-to-plan 必须把原文事实转成可执行计划，并覆盖五类信息：
- file_structure：本实验需要的代码/配置/脚本结构
- implementation_components：核心算法、模型、数据、评测模块如何落到文件
- validation_approach：烟测、全量实验、预期指标、验收标准
- environment_setup：uv/conda/容器方案、依赖版本、硬件要求
- implementation_strategy：分阶段实现顺序、每步测试点、降配策略
首次远程路径、物理机环境变更、全量长实验启动前都要停下让用户确认。 -->

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
uv run helix exp vram --params <B> --dtype <精度> --ctx <长度> --batch <N> [--layers L --hidden H]
```
<!-- agent: 贴判级结论：fits_single / fits_multi_tp(TP=?) / needs_quant… -->

## 2. 分步执行命令
<!-- agent: 覆盖 environment_setup 和 implementation_strategy：从建环境到出指标的可复制命令，按推荐方案写实。
先烟测、再全量；长实验写明预计时长和 tmux 会话名。
```bash
# 1. 建环境 + clone 官方仓库
# 2. 下模型/数据（HF 命令）
# 3. 起服务/跑复现（带上 TP 度、并发等参数）
# 4. 评测出指标
```
-->

## 3. 实现组件与文件结构
<!-- agent: 覆盖 file_structure 和 implementation_components：
- 需要哪些代码/配置/脚本文件，各自负责什么
- 核心算法/模块对应论文哪节/哪个公式/哪个伪代码
- 数据处理、模型加载、训练/推理、评测如何连接
用官方仓库时说清"复用什么、要对齐哪些超参"，别重写；参考代码要记录来源和许可证风险。 -->

## 4. 验证方案与预期结果
<!-- agent: 覆盖 validation_approach：复现哪个实验、数据集子集、算什么指标、预期数值区间（对齐原文表几）、
烟测命令、全量命令、验收标准（如"吞吐提升在原文 ±X% 内即算成功"；缩比复现则"看相对趋势不看绝对倍数"）。 -->

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


def build_results_index_skeleton(title: str, note_rel: str, kind: str, domain: str) -> str:
    """Skeleton for results/index.md -- the curated results note (goes into the FTS index, links back to the paper).

    kind: "repro" (reproducing someone else's paper) or "mine" (my own experiment). frontmatter type drives
    write-phase retrieval: repro -> experiments/comparison, mine -> contribution.
    """
    fm = {
        "title": f"{title} · 结果" if kind == "repro" else f"{title}（我的实验）· 结果",
        "type": kind,                       # repro | mine
        "domain": domain,
        "tags": ["helix", "experiment", kind],
        "links": [note_rel] if note_rel else [],  # repro: paper reproduced; mine: papers built on/compared against
    }
    body = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False)
    link = f"[[{note_rel}]]" if note_rel else "（无）"
    origin = "复现的论文" if kind == "repro" else "对标/借鉴的论文"
    compare_heading = "与预期/原文的对比" if kind == "repro" else "与预期 / baseline 的对比"
    compare_prompt = (
        "复现→对齐原文表几、差多少；等价复现/缩比降配讲清楚"
        if kind == "repro"
        else "我的实验→对比 baseline，说明是否达到 plan.md 的验收标准"
    )
    problem_heading = "精读时没发现的问题" if kind == "repro" else "跨子实验暴露的问题"
    problem_prompt = (
        "复现/实验过程暴露、但精读论文时没注意到的问题——本节价值最高，务必如实记。"
        if kind == "repro"
        else "汇总各 sub_experiments/<slug>/results/index.md 里的问题、混杂因素、数据或 baseline 风险。"
    )
    claim_section = ""
    if kind == "mine":
        claim_section = """
## 结果支持的 claim / 下一轮动作
<!-- agent: result-to-claim：只写跨子实验汇总结论。单轮结果先写到对应
sub_experiments/<slug>/results/index.md，再在这里汇总 intended_claim、supported_claim、
unsupported_claim、证据强度、可能混杂因素和 next_action。 -->
"""
    raw_hint = (
        "原始数据在 results/{metrics,plots,tables}/"
        if kind == "repro"
        else "单轮原始数据在 sub_experiments/<slug>/results/{metrics,plots,tables}/"
    )
    return f"""---
{body}---
# 结果：{title}

> {origin}：{link} ｜ 方向见同目录 plan.md ｜ {raw_hint}

## 结果概览
<!-- agent: {'把 results/metrics、results/plots、results/tables 里的原始数据蒸馏成表/图 + 一句话结论' if kind == 'repro' else '汇总各子实验 results/index.md，给出当前总证据状态；不要在这里粘单轮流水账'} -->

## {compare_heading}
<!-- agent: {compare_prompt} -->
{claim_section}

## {problem_heading}
<!-- agent: {problem_prompt}
没有就写「暂无」，别硬凑。 -->

## 撰稿可用素材
<!-- agent: 哪些结果/图表可直接进论文；对应哪一节（相关工作 / 实验 / 贡献） -->
"""


def build_progress_skeleton(title: str, kind: str) -> str:
    """User-confirmed reproduction progress tracker. The CLI only creates it; agents maintain it as text."""
    if kind == "repro":
        heading = "复现进度"
        stage_a = "- [ ] A. paper-to-setup：原文事实抽取（等待用户确认）"
        stage_b = "- [ ] B. setup-to-plan：本机/远程可执行计划（等待用户确认）"
        stage_c = "- [ ] C. plan-to-code：代码实现与最小测试/烟测（等待用户确认）"
        stage_d = "- [ ] D. run-monitor-analyze：全量运行、分析、结果回流（等待用户确认）"
        current = "A. paper-to-setup"
        next_step = "填 setup.md：抽取论文结构、算法/公式、数据、指标、baseline、环境和代码可得性。"
        note = "阶段完成权归用户：agent 只能写「建议确认」，不能替用户勾选确认。"
    else:
        heading = "实验进度"
        stage_a = "- [ ] A. hypothesis-to-plan：方向假设、子实验 setup/config 和验收标准（等待用户确认）"
        stage_b = "- [ ] B. plan-to-code：代码实现与最小测试/烟测（等待用户确认）"
        stage_c = "- [ ] C. run-monitor-analyze：全量运行、分析、结果回流（等待用户确认）"
        stage_d = "- [ ] D. result-to-claim：判断结果支持/不支持什么 claim，决定下一轮动作（等待用户确认）"
        current = "A. hypothesis-to-plan"
        next_step = "填顶层 plan.md 的方向假设；用 `helix exp sub <工作区> --name <slug>` 为当前具体问题创建子实验 setup/config/results。"
        note = "这是用户自己的实验；不生成顶层 setup.md，具体设置写在 sub_experiments/<slug>/setup.md。阶段完成权归用户。"
    return f"""# {heading}：{title}

> {note}

## 当前阶段
{current}

## 阶段清单
{stage_a}
{stage_b}
{stage_c}
{stage_d}

## 用户确认记录
- A 完成：待确认
- B 完成：待确认
- C 完成：待确认
- D 完成：待确认

## 当前阻塞
暂无

## 下一步
{next_step}

## 运行记录
<!-- agent: 每轮记录改动摘要、启动命令、tmux 会话名、远程路径、开始/结束时间、commit 或快照摘要。 -->
"""


# Minimal contract file pushed to the remote: tells the coding agent where to drop experiment
# artifacts, so the local pull glob has a stable place to fetch from. Kept deliberately simple;
# iterate this one file (naming rules, per-run dirs, manifest) as needs grow -- push/pull follow.
RESULTS_LAYOUT = """# 实验结果存放规则（远程 agent 请遵守）

跑完实验，把产物放到本工作区的 results/ 下（helix exp pull 只从这三个子目录回拉）：

- results/metrics/  指标数据（*.json / *.csv），文件名带实验标识
- results/plots/    图（*.png / *.pdf）
- results/tables/   表（*.csv / *.md）

烟测、调试、临时试跑产物请在文件名或目录名里带 `smoke` / `tmp` / `debug` / `trial` / `dryrun` / `warmup`。
实验结束后先 `uv run helix exp clean <工作区>` 预览，再确认是否加 `--yes` 删除。

写产物前先 `mkdir -p results/{metrics,plots,tables}`——push 只传声明的文件、不建空目录树，
目录不存在直接写会失败。
不要把模型权重、checkpoint、完整日志放进 results/——那些留在远程，不回流本地。
"""


MINE_RESULTS_LAYOUT = """# 实验结果存放规则（远程 agent 请遵守）

这是 `type:mine` 工作区。顶层 `plan.md` 只管研究方向；具体实验必须写入子实验目录：

- `sub_experiments/<slug>/setup.md`：本轮设置
- `sub_experiments/<slug>/config.yaml`：本轮非敏感配置
- `sub_experiments/<slug>/results/index.md`：本轮结果总结
- `sub_experiments/<slug>/results/metrics/`：指标数据（*.json / *.csv）
- `sub_experiments/<slug>/results/plots/`：图（*.png / *.pdf）
- `sub_experiments/<slug>/results/tables/`：表（*.csv / *.md）

烟测、调试、临时试跑产物请在文件名或目录名里带 `smoke` / `tmp` / `debug` / `trial` / `dryrun` / `warmup`。
实验结束后先 `uv run helix exp clean <工作区或子实验目录>` 预览，再确认是否加 `--yes` 删除。

新需求来时新建一个 `<slug>`，不要把旧文件事后搬进 archive。写产物前先：

```bash
mkdir -p sub_experiments/<slug>/results/{metrics,plots,tables}
```

顶层 `results/index.md` 只写跨子实验汇总，不放单轮原始数据。
不要把模型权重、checkpoint、完整日志放进 results/——那些留在远程，不回流本地。
"""


def build_results_layout(kind: str) -> str:
    """Result-placement contract pushed to the remote agent."""
    return MINE_RESULTS_LAYOUT if kind == "mine" else RESULTS_LAYOUT


def build_sync_yaml(kind: str) -> str:
    """Per-workspace sync.yaml: which remote this experiment uses + which files push/pull.

    Lives next to the experiment (travels with the workspace). `remote:` references a name in config.remotes.
    """
    push = ["sync.yaml", "PROGRESS.md", "plan.md", "scripts/**", "configs/**", "RESULTS_LAYOUT.md"]
    if kind == "repro":
        push.insert(2, "setup.md")
    if kind == "mine":
        push.insert(push.index("RESULTS_LAYOUT.md"), "sub_experiments/**")
    pull = ["results/metrics/**", "results/plots/**", "results/tables/**"]
    if kind == "mine":
        pull.extend([
            "sub_experiments/*/results/metrics/**",
            "sub_experiments/*/results/plots/**",
            "sub_experiments/*/results/tables/**",
        ])
    spec = {
        "remote": "",  # fill with a name from config.remotes; empty = transport disabled for this workspace
        "remote_path": "",  # empty = confirm on first push via --remote-path; then reused
        "push": push,
        "pull": pull,
        "agent_view": {
            "models": {
                "base_model": "",  # remote/local path or HF id visible to the agent; no tokens
                "tokenizer": "",
                "checkpoints": "",
            },
            "datasets": {
                "raw": "",  # dataset root/path visible to the agent
                "processed": "",
                "cache": "",
            },
            "runtime": {
                "workdir": ".",  # relative to remote_path after push
                "env": "",  # uv venv / conda env / container name, non-sensitive only
            },
            "notes": [],
        },
    }
    header = ("# 本实验的传送清单。remote 填 config.yaml remotes 里的机器名。\n"
              "# remote_path: 远程工作区路径（首次 push 时由你用 --remote-path 确认后写入）。\n"
              "# push: 推到远程的文件（RESULTS_LAYOUT.md 必带，是远程写盘约定）。\n"
              "# pull: 从远程回拉的结果（对齐 RESULTS_LAYOUT.md 的三个子目录）。\n"
              "# agent_view: 暴露给 agent 的非敏感运行上下文（模型/数据/cache/env 路径等）。\n")
    return header + yaml.safe_dump(spec, allow_unicode=True, sort_keys=False, default_flow_style=False)


def build_experiment_workspace(
    title: str, note_rel: str, domain: str, short_name: str, cfg: Config,
    *, kind: str = "repro", draft: bool = False, overwrite: bool = False,
) -> tuple[Path, list[str]]:
    """Generate an experiment workspace skeleton under experiments/<domain>/<short_name>/ (or draft_notes/).

    kind="repro" (reproduce a paper): setup.md + plan.md + PROGRESS.md + results/index.md + RESULTS_LAYOUT.md + sync.yaml.
    kind="mine" (my own experiment): direction-level plan.md + PROGRESS.md + aggregate results/index.md +
        sub_experiments/README.md + RESULTS_LAYOUT.md + sync.yaml (no top-level setup.md).

    Returns (workspace dir, list of newly created relative paths). Verifies non-empty after persisting, else raises OSError.
    """
    if kind not in ("repro", "mine"):
        raise ValueError(f"未知实验类型 '{kind}'，应为 repro 或 mine")
    ws = cfg.experiment_workspace_path(domain, short_name, draft=draft)
    ws.mkdir(parents=True, exist_ok=True)

    # (relative path, content) — setup.md only for repro; plan.md differs by kind.
    items: list[tuple[str, str]] = []
    if kind == "repro":
        items.append(("setup.md", build_setup_skeleton(title, note_rel, cfg)))
        items.append(("plan.md", build_plan_skeleton(title, note_rel, cfg)))
    else:
        items.append(("plan.md", build_mine_plan_skeleton(title, note_rel, cfg)))
        items.append(("sub_experiments/README.md", build_sub_experiments_readme(title)))
    items.append(("PROGRESS.md", build_progress_skeleton(title, kind)))
    items.append(("results/index.md", build_results_index_skeleton(title, note_rel, kind, domain)))
    items.append(("RESULTS_LAYOUT.md", build_results_layout(kind)))
    items.append(("sync.yaml", build_sync_yaml(kind)))

    created: list[str] = []
    for rel, content in items:
        fpath = ws / rel
        if fpath.exists() and not overwrite:
            continue
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content, encoding="utf-8")
        if not fpath.exists() or fpath.stat().st_size == 0:
            raise OSError(f"实验骨架写入失败，文件未落盘：{fpath}")
        created.append(rel)
    return ws, created


def build_sub_experiment(
    workspace: Path, name: str, *, title: str | None = None, overwrite: bool = False,
) -> tuple[Path, list[str]]:
    """Create one isolated sub-experiment under an existing type:mine workspace."""
    slug = sub_experiment_slug(name)
    sub = workspace / "sub_experiments" / slug
    sub.mkdir(parents=True, exist_ok=True)
    display = title or name
    items = [
        ("setup.md", build_sub_experiment_setup_skeleton(display, slug)),
        ("config.yaml", build_sub_experiment_config_skeleton(display, slug)),
        ("results/index.md", build_sub_experiment_results_index(display, slug)),
        ("results/metrics/.gitkeep", ""),
        ("results/plots/.gitkeep", ""),
        ("results/tables/.gitkeep", ""),
    ]
    created: list[str] = []
    for rel, content in items:
        fpath = sub / rel
        if fpath.exists() and not overwrite:
            continue
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content, encoding="utf-8")
        if not fpath.exists():
            raise OSError(f"子实验骨架写入失败，文件未落盘：{fpath}")
        created.append(str(Path("sub_experiments") / slug / rel))
    return sub, created


@dataclass
class CleanupResult:
    """Deterministic cleanup report for transient experiment result artifacts."""

    target: str
    dry_run: bool
    candidates: list[str]
    deleted: list[str]
    warnings: list[str]

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "dry_run": self.dry_run,
            "candidates": self.candidates,
            "deleted": self.deleted,
            "warnings": self.warnings,
        }


def _result_roots_for_cleanup(target: Path) -> list[Path]:
    """Result roots to clean for an experiment workspace or one sub-experiment path."""
    roots: list[Path] = []
    if (target / "results").is_dir():
        roots.append(target / "results")
    sub_root = target / "sub_experiments"
    if sub_root.is_dir():
        for child in sorted(p for p in sub_root.iterdir() if p.is_dir()):
            if (child / "results").is_dir():
                roots.append(child / "results")
    return sorted(set(roots))


def _is_transient_result_file(path: Path, result_root: Path) -> bool:
    """Whether a result file is safe to treat as transient by naming convention."""
    if path.name in PROTECTED_RESULT_FILENAMES:
        return False
    try:
        rel = path.relative_to(result_root)
    except ValueError:
        return False
    return any(TRANSIENT_ARTIFACT_RE.search(part) for part in rel.parts)


def cleanup_transient_artifacts(target: Path, *, yes: bool = False) -> CleanupResult:
    """Preview or delete transient result artifacts under one experiment/sub-experiment.

    Safety contract:
    - only touches files under results/ or sub_experiments/*/results/;
    - never touches results/index.md or .gitkeep;
    - only matches explicit transient tokens such as smoke/tmp/debug/trial/dryrun/warmup;
    - dry-run by default, actual deletion requires yes=True.
    """
    target = target.expanduser().resolve()
    if not target.exists() or not target.is_dir():
        raise FileNotFoundError(f"实验目录不存在：{target}")

    roots = _result_roots_for_cleanup(target)
    warnings: list[str] = []
    if not roots:
        warnings.append("未发现 results/ 目录，无需清理")

    files: list[Path] = []
    for root in roots:
        for path in sorted(root.rglob("*")):
            if path.is_file() and _is_transient_result_file(path, root):
                files.append(path)

    candidates = [str(p.relative_to(target)) for p in files]
    deleted: list[str] = []
    if yes:
        for path in files:
            rel = str(path.relative_to(target))
            path.unlink()
            deleted.append(rel)
        for root in roots:
            for directory in sorted((p for p in root.rglob("*") if p.is_dir()),
                                    key=lambda p: len(p.parts), reverse=True):
                try:
                    directory.rmdir()
                except OSError:
                    pass

    return CleanupResult(str(target), not yes, candidates, deleted, warnings)
