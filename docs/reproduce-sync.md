# 设计文档：复现/实验的本地-远程传送带（「复现」板块）

> 本文档覆盖 helix「复现」板块中**本地笔记与远程 GPU 执行分离**这一类需求：复现工作区形态、
> 结果回流、我自己的实验落笔记、以及本地/远程之间的文件传送带。同类后续需求（远程配置演进、
> 传送策略调整、实验笔记类型扩展等）并入本文档，不另开文件。

## 1. 真实问题

用户的笔记（深读、综述、复现方案）都在**本地**（可对接 Obsidian vault），但实验跑在**远程 GPU
服务器**上。两边不能强行合并：

- 让用户把笔记全搬服务器 → 不符合本地记笔记的习惯。
- 让实验产物（仓库/权重/数据/日志，动辄几十上百 GB）回流本地 → 物理上不现实。

但「读 → 复现 → 写」要成一条链，实验结果又**必须**进笔记：撰稿写相关工作要文献笔记，写实验/对比
要复现结果，写贡献要我自己的实验设置、实现、结果。而且**复现别人的论文时，往往会暴露出精读阶段
没发现的问题**——这类发现价值极高，必须落成笔记，不能只留在服务器的日志里。

所以真问题不是「笔记要不要和复现分开」（本来就该分开），而是缺一条**本地方案 → 远程执行 →
结果回流本地笔记**的传送带，以及结果回流后**怎么落成可供撰稿检索的笔记**。

## 2. 核心决策

### 2.1 复现产物分三类，各归其位

| 类别 | 内容 | 归属 | 理由 |
|---|---|---|---|
| 思考 | setup.md（原文设置）、plan.md（本机方案）、结果解读 | 本地，跟笔记一起 | 小、手写、直接喂给「写」 |
| 执行 | clone 的仓库、模型权重、数据、日志、checkpoint | 只在远程 | 大、要 GPU/盘，永不回本地 |
| 蒸馏结果 | 指标数值、关键表、小图 | 远程产生 → 回流本地 | 落进笔记才能撰稿 |

传送带只搬第三类（蒸馏结果），第二类永远留远程，第一类本来就在本地。

### 2.2 工作区根目录 `repro/` → `experiments/`，一棵树用 `type` 装两种活

复现别人的论文、和我自己的实验，结构高度同构（都要方案、都要跑、都要落结果），没必要两套命令两棵树。
统一到 `experiments/`，靠 frontmatter 的 `type` 区分：

```
experiments/<方向>/<短名>/
  setup.md              # 原文实验设置（仅 type:repro 有；type:mine 无原文可抄）
  plan.md               # type:repro=本机复现方案；type:mine=我的实验设计
  sync.yaml             # 声明用哪台远程 + push/pull 清单
  RESULTS_LAYOUT.md     # 规则文件：指导远程 agent 把结果放哪（push 时随行）
  results/
    index.md            # 加工后的结果 + 解读 + 「精读时漏掉的问题」一节；frontmatter 带 type
    metrics/            # 原始指标（json/csv）
    plots/              # 图
    tables/             # 表
```

`results/` 是文件夹而非单文件：`index.md` 是人读/撰稿检索的加工结果，`metrics/`、`plots/`、
`tables/` 装 pull 回来的原始数据。`results/index.md` 的 frontmatter 是撰稿检索的抓手：

```yaml
type: repro          # repro=复现别人 → 实验/对比；mine=我自己的实验 → Contribution
domain: 示例-VLA模型
links: [[论文短名]]   # repro 指向被复现论文；mine 指向对标/借鉴的论文
```

- `type: paper`（已有深读笔记）→ 撰稿的 Related Work
- `type: repro` → 实验/对比
- `type: mine` → 贡献

「写」板块据此按 `type + 方向 + 双链图` 一次捞齐三种素材。

### 2.3 结果成 `results/` 文件夹（原始 + 加工），`index.md` 双链回论文

复现/实验结果单开 `results/` 文件夹，不追加进那篇论文的深读笔记。理由：

- 原始数据（指标/图/表）和加工结论（index.md）分层，各自演进；
- 复现内容和精读内容解耦；我自己的实验能独立成篇，撰稿时好检索；
- `index.md` 强制留一节「精读时漏掉的问题」，把复现暴露的新发现沉淀下来（本板块最大价值之一）。

`results/index.md` 用 wikilink 指回论文短名，双链图保证「读」和「复现」仍连成一体。索引只收 `index.md`
（加工结果），原始数据不进 FTS。

### 2.3.1 规则文件 `RESULTS_LAYOUT.md`：本地/远程结果结构的单一契约

push 时**必带** `RESULTS_LAYOUT.md`，指导远程服务器上的编码 agent 把实验产物落到约定位置。它是本地
pull glob 与远程 agent 写盘之间的契约——远程按它放，本地 pull 才知道去哪抓。先做**最简版**，按需迭代：

```markdown
# 实验结果存放规则（远程 agent 请遵守）
跑完实验，把产物放到工作区的 results/ 下：
- results/metrics/  指标数据（*.json / *.csv），文件名带实验标识
- results/plots/    图（*.png / *.pdf）
- results/tables/   表（*.csv / *.md）
不要把权重、checkpoint、完整日志放进 results/（那些留在远程，不回流）。
```

本地 `helix exp` 生成骨架时写出这份规则；`sync.yaml` 的 pull glob 默认对齐这三个子目录。后续要加约定
（命名规范、run 分目录、manifest 等）就迭代这一个文件，push/pull 两端自动跟上。

### 2.4 传送带：CLI 带护栏的 rsync，不碰远程执行

命令短名收敛为 `exp`：

- `helix exp new <笔记|id>` — 建复现骨架（type:repro，含 setup.md）
- `helix exp new --mine "<实验名>"` — 建我的实验骨架（type:mine，无 setup.md，plan.md 即实验设计）
- `helix exp push <工作区> [--dry-run]` — 推 sync.yaml 声明的脚本/配置 + **必带 RESULTS_LAYOUT.md** 到远程对应目录
- `helix exp pull <工作区> [--dry-run]` — 按 glob 拉结果进 `results/{metrics,plots,tables}/`（不碰 `results/index.md`）

**跑实验仍是用户手动 ssh 上去跑**（plan.md §2 给可复制命令），helix 只管两头搬运——人在环中，
CLI 不变成远程执行器（那样 blast radius 太大、也越权决策）。

**`type:mine` 用 `plan.md` 当实验设计**，不另立 `design.md`——复现别人和跑自己的实验共用同一文件位，
只是内容语义不同（repro=本机复现方案；mine=我的实验设计），少一个概念、骨架按 type 填不同引导即可。

config 里 `remotes` 只登记「机器长什么样」（连接方式 + 远程根 + 挂哪个硬件档），是可复用的机器册；
**每个工作区一份 `sync.yaml`** 才说「这个实验用哪台 remote、push/pull 哪些文件」，贴着实验走、可随
工作区一起 push、各实验互不干扰。职责分开：

```yaml
# config.yaml —— 机器册（一次配，所有实验复用；缺了即传送带关闭，旧 config 照跑）
remotes:
  gpu-a100:
    host: gpu-a100                    # 用 ~/.ssh/config alias，别写明文密码
    remote_repro_root: /data/helix-experiments
    hardware_profile: a100-8x40g      # 复用已有硬件判级档
```

```yaml
# experiments/<方向>/<短名>/sync.yaml —— 本实验的传送清单
remote: gpu-a100                      # 引用 config.remotes 里的机器名
push: [plan.md, scripts/**, configs/**, RESULTS_LAYOUT.md]   # RESULTS_LAYOUT.md 必带
pull: [results/metrics/**, results/plots/**, results/tables/**]
```

## 3. 范围与非目标

- **不做自动写实验代码的 skill**（不复刻 ref/deepcode 的 Paper2Code codegen）。理由：
  1. 物理错位——agent 在本地、GPU 和官方仓库在远程，本地盲写的代码跑不了也不在仓库旁；
  2. 重复包装——用户本就在用编码 agent（Claude Code/Codex），helix 该补裸 agent 缺的能力
     （检索/判级/笔记图谱/传送带），不重新发明写代码；
  3. Paper2Code 解的是「无官方仓库、从零起 repo」的小概率场景，不值得占核心资源。
- **交接边界**：reproduce skill 到 plan.md 为止（§2 可执行命令 + §3 要跑通/对齐什么）。真要写代码，
  用户把 plan.md 甩给**跑在远程服务器上的编码 agent**，对着官方仓库实现、对齐超参。这一步不是 helix skill 编排。
- CLI 不绑定任何 LLM provider（延续全局约定）。
- push/pull 不做远程命令执行、不做实验调度。

## 4. 安全与数据安全（对齐「不丢用户数据」）

- push/pull **默认无 `--delete`**，带 `--dry-run`；路径锁死在工作区 / `remote_repro_root/<方向>/<短名>/` 内。
- pull 只写入 `results/{metrics,plots,tables}/`，**绝不覆盖**手写的 setup.md / plan.md / results/index.md / RESULTS_LAYOUT.md。
- 远程凭据优先走 `~/.ssh/config` alias；`host` 里出现明文密码则告警。
- `remotes` 是新可选块，旧 config 照读。

## 5. 迁移（`repro/` → `experiments/` 属存储架构改动，必须只搬不丢、幂等、可回滚）

`helix migrate` 增补：

- 检测旧 `repro/` 存在 → 提示（或 `--yes` 执行）整体移到 `experiments/`；移前校验、移后核对文件数，
  **绝不静默删**。
- config 旧 `repro_dir` 字段仍能读，映射到新 `experiments_dir`；缺 `experiments_dir` 给默认值 `experiments` 并提示。
- 给已有工作区补 `results/index.md` / `sync.yaml` / `RESULTS_LAYOUT.md`（幂等，已存在跳过）；
  旧的单文件 `results.md`（若有）迁成 `results/index.md`。

正在用旧版的用户 `git pull` + `helix migrate` 一步平滑升级，笔记/复现数据一个不丢。

## 6. 分期

1. **重命名 + type**：`repro_dir`→`experiments_dir`（向后兼容读旧字段）、`exp` 子命令组、
   `results/index.md` 骨架 + `type` frontmatter、`RESULTS_LAYOUT.md` 骨架、migrate 搬 `repro/`→`experiments/`。
2. **传送带**：`remotes` config、`sync.yaml`、`exp push/pull`（rsync 封装 + 护栏 + `--dry-run`，push 必带 RESULTS_LAYOUT.md）。
3. **回流落笔记**：reproduce skill 读 `results/{metrics,plots,tables}/` 蒸馏进 `results/index.md`，
   写「精读漏掉的问题」一节，建索引；「写」板块按 `type` 捞素材（并入「写」板块设计文档）。
