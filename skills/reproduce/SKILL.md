---
name: reproduce
description: 当用户想复现某篇论文的实验、或跑自己的实验（给了 arXiv id/标题/已有笔记，或说要做自己的实验），需要总结实验设置、判断本机/远程 GPU 装不装得下、产出可执行方案，或在远程 GPU 上编排跑实验（推代码、开 tmux 会话、探硬件、烟测→全量、拉结果回笔记）时使用。
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

### 5. 远程 GPU 上跑实验（代码在本地写，实验在远程跑，你来编排）
笔记和代码在本地、GPU 在远程时，**你（agent）编排整个远程实验流程**，helix CLI 做接触凭据和远程的
确定性原子操作——SSH 连接、开远程 tmux、注入凭据、探硬件、scp 传输。**凭据（SSH/sudo 密码）锁在 CLI 里，
绝不进入你的请求**：你只调命令，永远看不到明文。

前提：config.yaml 配 `remotes`（host/user/root，非敏感），工作区 `sync.yaml` 填 `remote:` 机器名；
需要密码时放 `config.secrets.yaml`（已 gitignore，helix 读取注入）。**优先 SSH key 免密，则无需 secrets**。

命令面（都对着工作区路径）：
```bash
uv run helix exp probe <工作区>                              # 探磁盘/GPU（JSON），判断实验条件
uv run helix exp start <工作区> [-m "本轮说明"]              # 开始实验：git 提交本轮 + push 代码上远程
uv run helix exp run <工作区> --cmd "<命令>" [--session <名>] [--oneshot] [--sudo]  # 远程 tmux 里跑
uv run helix exp sessions <工作区>                           # 列远程 tmux 会话
uv run helix exp kill <工作区> --session <名>                # 杀会话
uv run helix exp pull <工作区> [--dry-run]                   # 拉 results/{metrics,plots,tables}/ 回本地
```

**首次确认远程路径**：某工作区第一次 push/start/run/pull 时，`sync.yaml` 的 `remote_path` 还空着，helix
会打印建议路径（`<remote_repro_root>/<方向>/<短名>`）并以退出码 3 停下、**不碰远程**。你把建议路径转述给
用户确认（或让用户改），拿到确认后带 `--remote-path <路径>` 重跑——helix 写回 sync.yaml，之后不再问。
传输用 scp（Mac/Win/Linux 通用），走 `~/.ssh/config` alias（含跳板机/key）。

编排时严格守下面 6 条（这是本 skill 的核心职责）：

1. **会话精简**：一次性的活（装环境、下数据）用 `--oneshot`，跑完自动退会话；长驻的活（跑实验）不加，
   保留会话。干完活主动 `exp sessions` 看一眼，把不再用的会话 `exp kill` 掉，别堆积。
2. **换源装环境、不动物理机**（规则 2+6）：环境一律建在隔离层——`uv venv` / miniconda env / 容器镜像，
   **不改物理机全局环境**。装包换国内源提速（如 `uv pip install -i <mirror> ...` 或 conda 配 channel）。
   装环境这类用 `--oneshot`。
3. **先烟测、再全量、预估时长**（规则 3）：
   - 跑前先 `exp probe` 看磁盘够不够、GPU 空不空，条件不满足先告诉用户别硬跑。
   - 先小规模烟测（小 batch/少步数/子集），通过再上全量。
   - 预估全量时长。**若实验会跑很久：启动后直接结束当前会话、不轮询**，明确告诉用户
     「实验在 <机器> 的 tmux 会话 <名> 里跑，预计约 <时长>，回头用 `exp sessions`/`exp pull` 查」。
4. **每轮版本可追溯**（规则 4）：一轮 = 上次实验结束到这次开始之间的改动。代码在本地改，用户说开始实验时，
   用 `exp start` ——它先把本轮改动 git 提交、再 push 上远程，确保**远程跑的代码 = 本地某个 commit**。
   有条件先在本地跑单测再 start。
5. **凭据不经手**（规则 5）：你只调 helix 命令，SSH/sudo 密码由 CLI 从 secrets 文件注入远程，
   绝不出现在你的上下文或任何请求里。需要 sudo 的命令加 `--sudo`，密码走 stdin，你无需也拿不到它。
6. **要写实验代码**：把 plan.md 交给**这个在本地跑的编码 agent（就是你）** 对着远程仓库实现——本地改完
   用 `exp start` 同步上去。helix 不替你写代码（见「非目标」）。

### 6. 结果回流落笔记（撰稿抓手）
`exp pull` 回来后，读 `results/{metrics,plots,tables}/` 里的原始数据，蒸馏进 `results/index.md`：
- **结果概览**：把原始指标/图整理成表 + 一句话结论。
- **与预期/原文对比**：复现→对齐原文表几差多少；我的实验→对比 baseline。
- **精读时没发现的问题**：复现/实验暴露、但精读论文时没注意到的问题——**本节价值最高，务必如实记**，没有写「暂无」。
- 填好后 `uv run helix index build` 建索引，撰稿时按 `type`（repro/mine）+ 双链检索。

## 非目标：helix 不替你写代码、不替你决策
helix CLI 只做确定性原子操作（连接/传输/开会话/探硬件/凭据注入）。**写实验代码、判断烟测通没通、
决定跑不跑全量，都是你（编码 agent）的活**，helix 不包装。理由：这些本就是编码 agent 擅长的判断，
CLI 硬编码只会僵化。凭据处理归 CLI 是因为它必须不进大模型，不是因为 CLI 更懂。详见 docs/reproduce-sync.md。

## 原则
- **推荐方案优先**：plan.md 开头就给"用哪台机、哪个模型、怎么跑"的结论，对比和背景往后放。
- **两文档分工清楚**：setup.md = 原文怎么做（参考）；plan.md = 本机怎么跑（行动）。不重复。
- **八卡思维**：用户是单机八卡，优先 a100-8x40g，大模型先考虑 TP8 而非直接判放不下。
- **诚实分级**：可复现性 A/B/C 如实判；缩比复现说清"看相对趋势不看绝对倍数"。
- **可执行**：§2 命令要能直接复制运行，别停在抽象描述。
- **测试用 --draft**：需求测试先落 `draft_notes/`，稳定了再进 `experiments/`。
- **结果必回流**：实验跑完，蒸馏进 `results/index.md` 并建索引，撰稿才捞得到；「精读漏掉的问题」一节别省。
