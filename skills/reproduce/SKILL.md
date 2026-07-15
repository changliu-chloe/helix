---
name: reproduce
description: 当用户想复现某篇论文的实验、或跑自己的实验（给了 arXiv id/标题/已有笔记，或说要做自己的实验），需要总结实验设置、判断本机/远程 GPU 装不装得下、产出可执行方案，或把本地方案推到远程 GPU 跑、把结果拉回笔记时使用。
---

# 论文复现规划

把一篇论文的实验「翻译」成能在用户自己 GPU 上跑的复现方案。helix 负责确定性活
（显存估算/判级/建工作区骨架），**实验设置的理解、方案的填充由你（agent）完成**。

方法论借鉴 ref/deepcode 的 Paper2Code（先抽取算法与实验设置，再产出分段式复现计划），
但只做到「可执行复现方案」层，不自动写实现代码。

> **运行约定**：所有 helix 命令用 `uv run helix ...` 在项目根执行。若 `uv` 不可用，回退 `python -m helix.cli ...`。

## 前置：论文得先读过

复现依赖对论文的深入理解。若库里还没有这篇的深读笔记，**先走 deep-read 流程**
（`note new` → `fetch` 读全文 → 填笔记），再回来复现。已有笔记则直接用。

## 工作流程

### 1. 建实验工作区骨架
```bash
uv run helix exp new <笔记路径 或 arXiv id> [--domain "<方向>"] [--draft]   # 复现别人（type:repro）
uv run helix exp new --mine "<实验名>" [<对标论文笔记/id>] [--domain "<方向>"]  # 我自己的实验（type:mine）
```
- **复现别人**：传已有笔记路径最好（自动读 frontmatter 拿标题/方向/回链）；也可传 arXiv id。
- **我自己的实验**：用 `--mine "<名字>"`，无 `setup.md`（没原文可抄），`plan.md` 即实验设计；可选带一个对标论文做回链。
- 在 `experiments/<方向>/<短名>/` 生成骨架：
  - `setup.md`（仅 repro）+ `plan.md` — 你要填的实验设置/方案
  - `results/index.md` — 结果笔记（带 `type` frontmatter，进索引，双链回论文）
  - `RESULTS_LAYOUT.md` — 结果存放规则，push 时传给远程 agent（见第 5 步）
  - `sync.yaml` — 本工作区传送清单（远程机名 + push/pull 文件）
- **`--draft`**：落到 `draft_notes/` 而非 `experiments/`——需求测试、试跑方案时用这个。
- 输出 JSON 含 `workspace` 路径与 `kind`；骨架里每个 `<!-- agent: … -->` 就是你要填的。

### 2. 填 setup.md（原文实验设置，纯参考）
setup.md 只客观记录**原文怎么做的**，不谈本机怎么跑（那是 plan.md）。
读深读笔记 + 全文（`notes/papers/<方向>/assets/<id>/fulltext.md`）补全：
- **原文实验环境**：GPU 型号/卡数、互联、框架、版本
- **原文模型**：名称、参数量、精度、是否开源、HF 名
- **原文数据集/工作流**：名称、规模、划分、下载方式、有无子集（plan 会用到）
- **原文评测指标 与 baseline**：定义、对齐原文哪张表、baseline 清单
- **原文关键超参**：batch/group size、温度、序列长度等
- **代码可得性**：官方仓库 / 无 / 第三方复现 + 许可证（判分级的关键）

只写论文里有的；推断要标注。

### 3. 硬件判级（决定推荐方案）
先算清楚本机装不装得下——这决定 plan.md 的推荐方案怎么写。
```bash
uv run helix exp vram --params <B> --dtype <精度> --ctx <长度> --batch <N>
# 已知架构精算 KV：--layers <层数> --hidden <hidden size>
# 只看某台机：--profile a100-8x40g
```
- 判级：`fits_single`（单卡够）/ `fits_multi_tp`（需多卡 TP，给 TP 度）/ `needs_quant` /
  `needs_offload` / `no_fit`，并给降配阶梯。
- 用户机器都是**单机八卡**：`a100-8x40g`（8×40G=320G）、`h20-8x96g`（8×96G=768G）。
  **复现优先用 a100-8x40g**（排在 config 最前）。八卡下大模型可 TP8 跑，别默认"放不下"。
- 放不下才按阶梯：**换小模型 → int8/int4 量化 → 加大 TP 度 → offload**。

### 4. 填 plan.md（推荐方案在最前，与原文对比在最后）
plan.md 讲**本机怎么跑**，别重抄 setup.md 的原文清单。按骨架顺序：
- **§1 推荐方案**（最重要，放最前）：一句话给结论——用哪台机（优先 a100-8x40g）、哪个模型、
  什么精度/TP 度、跑哪个实验；配推荐配置表 + 显存核对结果。让用户不往下翻就能开跑。
- **§2 分步执行命令**：从建环境到出指标的可复制命令，带上 TP 度/并发等参数。
- **§3 实现组件**：要跑通/验证的核心算法，用官方仓库时说清"复用什么、对齐哪些超参"。
- **§4 验证方案与预期结果**：复现哪个实验、指标、预期区间（对齐原文表几）、验收标准。
- **§5 可复现性分级**：A/B/C + 理由（诚实判级是这功能最大价值，别硬凑）。
- **§6 与原文实验的差异**（对比放最后）：表格对比原文 vs 本机，讲清等价复现/缩比降配/复现不了的部分。

### 5. 本地/远程分离时：用传送带跑实验（笔记本地、GPU 在远程）
用户笔记在本地、实验在远程 GPU 时，helix 只管两头搬运，**跑实验是用户手动 ssh 上去跑**（人在环中）。
前提：config.yaml 配了 `remotes`，工作区 `sync.yaml` 的 `remote:` 填了机器名。

```bash
uv run helix exp push <工作区> [--dry-run]   # 推 plan.md/脚本/配置 + RESULTS_LAYOUT.md 到远程
# —— 用户 ssh 上远程，按 plan.md §2 跑实验；产物按 RESULTS_LAYOUT.md 落到 results/ ——
uv run helix exp pull <工作区> [--dry-run]   # 把 results/{metrics,plots,tables}/ 拉回本地
```
- push 必带 `RESULTS_LAYOUT.md`（告诉远程 agent 把结果放哪）；不带 `--delete`，不覆盖远程既有。
- pull 只回流到 `results/{metrics,plots,tables}/`，**绝不覆盖**手写的 setup/plan/results/index.md。
- **要写实验代码**：把 plan.md 交给**跑在远程的编码 agent** 对着官方仓库实现、对齐超参——这一步不由本 skill 编排（见下「非目标」）。

### 6. 结果回流落笔记（撰稿抓手）
pull 回来后，读 `results/{metrics,plots,tables}/` 里的原始数据，蒸馏进 `results/index.md`：
- **结果概览**：把原始指标/图整理成表 + 一句话结论。
- **与预期/原文对比**：复现→对齐原文表几差多少；我的实验→对比 baseline。
- **精读时没发现的问题**：复现/实验暴露、但精读论文时没注意到的问题——**本节价值最高，务必如实记**，没有写「暂无」。
- 填好后 `uv run helix index build` 建索引，撰稿时按 `type`（repro/mine）+ 双链检索。

## 非目标：不自动写实验代码
本 skill 到 plan.md（§2 可执行命令 + §3 要跑通/对齐什么）为止，**不生成实现代码**。理由：agent 在本地、
GPU 和官方仓库在远程，本地盲写的代码跑不了也不在仓库旁；且这是编码 agent 本就擅长的事，不重复包装。
真要写代码，用户把 plan.md 甩给跑在远程服务器上的编码 agent。详见 docs/reproduce-sync.md。

## 原则
- **推荐方案优先**：plan.md 开头就给"用哪台机、哪个模型、怎么跑"的结论，对比和背景往后放。
- **两文档分工清楚**：setup.md = 原文怎么做（参考）；plan.md = 本机怎么跑（行动）。不重复。
- **八卡思维**：用户是单机八卡，优先 a100-8x40g，大模型先考虑 TP8 而非直接判放不下。
- **诚实分级**：可复现性 A/B/C 如实判；缩比复现说清"看相对趋势不看绝对倍数"。
- **可执行**：§2 命令要能直接复制运行，别停在抽象描述。
- **测试用 --draft**：需求测试先落 `draft_notes/`，稳定了再进 `experiments/`。
- **结果必回流**：实验跑完，蒸馏进 `results/index.md` 并建索引，撰稿才捞得到；「精读漏掉的问题」一节别省。
