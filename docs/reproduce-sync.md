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
| 思考 | setup.md（原文设置/子实验设置）、plan.md（复现方案/研究方向）、结果解读 | 本地，跟笔记一起 | 小、手写、直接喂给「写」 |
| 执行 | clone 的仓库、模型权重、数据、日志、checkpoint | 只在远程 | 大、要 GPU/盘，永不回本地 |
| 蒸馏结果 | 指标数值、关键表、小图 | 远程产生 → 回流本地 | 落进笔记才能撰稿 |

传送带只搬第三类（蒸馏结果），第二类永远留远程，第一类本来就在本地。

### 2.2 工作区根目录 `repro/` → `experiments/`，一棵树用 `type` 装两种活

复现别人的论文、和我自己的实验，结构高度同构（都要方案、都要跑、都要落结果），没必要两套命令两棵树。
统一到 `experiments/`，靠 frontmatter 的 `type` 区分：

（实验工作区在 `workspace/experiments/` 下，与 `workspace/notes/` 同属单一 workspace 根）

```
workspace/experiments/<方向>/<短名>/
  setup.md              # 原文实验设置（仅 type:repro 有；type:mine 无顶层 setup.md）
  plan.md               # type:repro=本机复现方案；type:mine=研究方向和总假设
  sync.yaml             # 声明用哪台远程 + push/pull 清单 + agent 可见的非敏感运行视图
  RESULTS_LAYOUT.md     # 规则文件：指导远程 agent 把结果放哪（push 时随行）
  results/
    index.md            # repro=加工后的结果；mine=跨子实验汇总；frontmatter 带 type
    metrics/            # 原始指标（json/csv）
    plots/              # 图
    tables/             # 表
  sub_experiments/       # 仅 type:mine 使用：每个具体问题/轮次一个隔离目录
    <slug>/
      setup.md           # 本轮用户需求、假设、baseline、变量、命令和验收标准
      config.yaml        # 本轮非敏感结构化配置，可由 CLI / skill / LLM 生成后人工确认
      results/
        index.md         # 本轮结果总结
        metrics/
        plots/
        tables/
```

`results/` 是文件夹而非单文件：`index.md` 是人读/撰稿检索的加工结果，`metrics/`、`plots/`、
`tables/` 装 pull 回来的原始数据。`type:mine` 顶层 `results/index.md` 只做跨子实验汇总，单轮原始结果和
单轮结论放在 `sub_experiments/<slug>/results/`，避免后续需求污染旧实验。`results/index.md` 的
frontmatter 是撰稿检索的抓手：

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

`type:repro` 的 `results/index.md` 用 wikilink 指回论文短名，双链图保证「读」和「复现」仍连成一体。
`type:mine` 的顶层 `results/index.md` 汇总各 `sub_experiments/<slug>/results/index.md` 对 claim 的支持/反驳；
子实验结果页记录本轮 baseline、验收标准、指标和暴露的问题。索引只收 `index.md`（加工结果），原始数据不进 FTS。

### 2.3.1 规则文件 `RESULTS_LAYOUT.md`：本地/远程结果结构的单一契约

push 时**必带** `RESULTS_LAYOUT.md`，指导远程服务器上的编码 agent 把实验产物落到约定位置。它是本地
pull glob 与远程 agent 写盘之间的契约——远程按它放，本地 pull 才知道去哪抓。按 `type` 生成不同契约：

- `type:repro`：结果放顶层 `results/{metrics,plots,tables}/`；
- `type:mine`：具体轮次结果放 `sub_experiments/<slug>/results/{metrics,plots,tables}/`，顶层 `results/index.md`
  只写跨子实验汇总。

规则文件的核心约定：

```markdown
# 实验结果存放规则（远程 agent 请遵守）
跑完实验，把产物放到工作区约定的 results/ 下：
- results/metrics/  指标数据（*.json / *.csv），文件名带实验标识
- results/plots/    图（*.png / *.pdf）
- results/tables/   表（*.csv / *.md）
烟测、调试、临时试跑产物在文件名或目录名里带 smoke/tmp/debug/trial/dryrun/warmup。
不要把权重、checkpoint、完整日志放进 results/（那些留在远程，不回流）。
```

本地 `helix exp` 生成骨架时写出这份规则；`sync.yaml` 的 pull glob 默认对齐这些结果目录。后续要加约定
（run 分目录、manifest 等）就迭代这一个文件，push/pull 两端自动跟上。

### 2.3.2 结束清理：`exp clean` 只清临时结果，不清正式证据

实验或子实验结束后，目录整理是显式动作，不自动发生：

- `helix exp clean <工作区或子实验目录>`：只预览候选；
- `helix exp clean <工作区或子实验目录> --yes`：用户确认后删除。

清理边界：

- 只扫描 `results/` 和 `sub_experiments/*/results/`；
- 永远不碰 `results/index.md`、`.gitkeep`、`setup.md`、`plan.md`、`config.yaml`、`sync.yaml`；
- 只匹配路径片段中带 `smoke` / `tmp` / `debug` / `trial` / `dryrun` / `warmup` 的文件；
- 正式结果应使用稳定名称，不能带上述临时 token。

这个设计把“哪些产物可清理”前置到命名规范里，避免事后让 CLI 猜哪些结果有价值。

### 2.4 传送带：CLI 带护栏的 scp（远程执行见 §5）

命令短名收敛为 `exp`：

- `helix exp new <笔记|id>` — 建复现骨架（type:repro，含 setup.md）
- `helix exp new --mine "<实验名>"` — 建我的实验骨架（type:mine，无顶层 setup.md，plan.md 是研究方向）
- `helix exp sub <工作区> --name "<子实验短名>"` — 在 type:mine 下创建隔离子实验（setup.md + config.yaml + results/）
- `helix exp push <工作区> [--remote-path P] [--dry-run]` — scp 推 sync.yaml 声明的项 + **必带 RESULTS_LAYOUT.md** 到确认的远程目录
- `helix exp pull <工作区> [--dry-run]` — scp 拉结果进顶层 results 和已存在子实验 results（不碰 `index.md`）
- `helix exp clean <工作区或子实验目录> [--yes]` — 预览/清理烟测、调试、临时试跑结果

**传输用 scp**（Mac/Win/Linux 通用，走 ~/.ssh/config alias）。护栏在 scp 下如何保留见 §5.5；
远程路径首次由用户确认见 §5.6。跑实验本身见 §5（远程 tmux）。

**`type:mine` 的顶层 `plan.md` 是研究方向和总假设，不承载每轮具体设置**。具体实验由 `exp sub` 创建
`sub_experiments/<slug>/`，本轮 baseline、变量、命令、验收标准和结果都留在该目录。这样新需求来时新建子实验，
而不是把旧文件事后搬进 archive。

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
push: [sync.yaml, plan.md, scripts/**, configs/**, sub_experiments/**, RESULTS_LAYOUT.md]   # mine 含 sub_experiments
pull: [results/metrics/**, results/plots/**, results/tables/**,
       sub_experiments/*/results/metrics/**,
       sub_experiments/*/results/plots/**,
       sub_experiments/*/results/tables/**]
agent_view:
  models:
    base_model: /mnt/models/Qwen2.5-7B-Instruct   # 路径或 HF id；不写 token
    tokenizer: /mnt/models/Qwen2.5-7B-Instruct
    checkpoints: /data/checkpoints/my-exp
  datasets:
    raw: /data/datasets/raw/my-task
    processed: /data/datasets/processed/my-task
    cache: /data/cache/my-task
  runtime:
    workdir: .                                    # 相对 remote_path
    env: helix-my-exp                             # uv venv / conda env / container 名
  notes:
    - 模型和数据路径是远程机器上的既有路径，agent 可直接引用。
```

`agent_view` 是暴露给 agent 的**非敏感运行视图**，解决“模型权重在哪里、数据集在哪里、cache 用哪块盘、
环境叫什么”这类上下文问题。这里不要写 SSH 密码、sudo 密码、API token、私有下载链接、访问密钥；敏感凭据
仍只放 `config.secrets.yaml` 或由用户单独审核。

## 3. 范围与非目标

- **不做自动写实验代码的 skill**（不复刻 ref/deepcode 的 Paper2Code codegen）。理由：
  1. 重复包装——用户本就在用编码 agent（Claude Code/Codex），helix 该补裸 agent 缺的能力
     （检索/判级/笔记图谱/传送带/凭据处理），不重新发明写代码；
  2. Paper2Code 解的是「无官方仓库、从零起 repo」的小概率场景，不值得占核心资源。
- **交接边界**：写实验代码、判断烟测通没通、决定跑不跑全量，是编码 agent 的活；helix CLI 只做确定性
  原子操作（连接/传输/开会话/探硬件/凭据注入）。**注意**：本仓库现在支持「所有会话在本地进行」，
  代码在本地写、由 helix `exp start` 同步到远程跑——编码 agent 不再需要人肉登远程，见 §5。
- CLI 不绑定任何 LLM provider（延续全局约定）。
- **CLI 不做实验决策**：跑什么、跑多久、烟测通过没，都是 agent 编排；CLI 只执行 agent 拼好的命令。

## 4. 安全与数据安全（对齐「不丢用户数据」）

- push/pull **默认无 `--delete`**，带 `--dry-run`；路径锁死在工作区 / `remote_repro_root/<方向>/<短名>/` 内。
- pull 只写入顶层 `results/{metrics,plots,tables}/` 和已存在的
  `sub_experiments/*/results/{metrics,plots,tables}/`，**绝不覆盖**手写的 setup.md / plan.md / config.yaml /
  results/index.md / RESULTS_LAYOUT.md。
- 远程凭据优先走 `~/.ssh/config` alias + SSH key 免密；用密码时见 §5 的凭据模型。
- `remotes` 是新可选块，旧 config 照读。

## 5. 远程执行：本地写代码、远程跑实验（定位的主动翻转）

### 5.1 为什么 helix 现在「碰远程执行」了

初版 helix 只做文件搬运（push/pull），明确不碰远程执行——用户手动 ssh 上去跑。新需求要**所有会话都在
本地这个仓库进行**：代码和实验设计在本地和 agent 沟通产生，再传上服务器跑。这就要 helix 去 ssh、开
tmux、探硬件、跑命令。

翻转的正当理由是**凭据**：SSH/sudo 密码必须锁在 CLI 里、绝不进大模型请求。凭据留在 CLI，执行就必须由
CLI 代理——agent 只调 `helix exp run`，永远看不到明文。所以这不是功能膨胀，而是安全约束倒逼的分工。

### 5.2 分工：CLI 做原子操作，agent 做编排判断

- **CLI（确定性、接触凭据/远程）**：`exp start`（可选 git 提交本轮 + push）、`exp run`（远程 tmux 跑命令）、
  `exp probe`（探磁盘/GPU）、`exp sessions`/`exp kill`（会话管理）、`exp push/pull`（传输）。
- **agent（判断、编排）**：装什么环境、烟测通没通、跑不跑全量、时长多久、会话留不留。这些 CLI 不硬编码。
- **tmux 开在远程**：会话在远程机器上，ssh 断开实验不断，长实验可脱机——启动后 agent 直接结束会话不轮询，
  告诉用户「在 <机器> 会话 <名>，预计 <时长>」。

### 5.3 凭据模型（对齐「凭据绝不进大模型」）

- 非敏感的 host/user/ssh_key/root 在 `config.yaml` 的 `remotes`；**敏感的 SSH/sudo 密码**在单独的
  `config.secrets.yaml`（sibling，已 gitignore），用 `config.secrets.example.yaml` 作模板。
- 密码只在 `helix/ssh.py` 的子进程边界读取并注入：SSH 密码经 **env（`SSHPASS`，配合 sshpass）**，
  sudo 密码经 **stdin（`sudo -S`）**。**绝不进命令行 argv、日志，或任何返回给 CLI/agent/模型的结构**。
- 优先 SSH key 免密——则 secrets 文件整个可留空，安全性最高；密码是兜底。
- 命令一律 argv list + 无 `shell=True`（延续 sync.py 范式，防注入）。

### 5.4 每轮版本可追溯（可选 git）

「一轮」= 上次实验结束到本次开始之间的改动。**可选**功能，config 开 `git.enabled=true` + 填 name/email 才启用：

- **一实验一仓库**：git 管的是**实验工作区**（sync.yaml 同目录，`workspace/experiments/<方向>/<短名>/`），
  每个实验独立 git 仓库——不是整个 helix checkout（提交 base_dir 会把源码和所有实验混在一起，粒度错）。
- `exp start` 流程：需要则 `git init` 工作区 → 把 config 的 name/email 写进该仓库 `.git/config`（仓库级，
  不动 `~/.gitconfig`）→ 脏则 commit 本轮 → scp push。保证**远程跑的代码 == 刚提交的 commit**。
- **提交信息 = 约定式提交**：`<type>: <摘要>`，type ∈ {feat, fix, chore, refactor, docs, test, perf}。
  类型判断是 LLM 的活（CLI 看不懂 diff 语义）：agent 看本轮 diff 判类型、拼 message，经 `exp start -m` 传入；
  CLI 只原样提交。省略 `-m` 用朴素兜底默认并提示。
- **关闭（默认）**：`exp start` 跳过全部 git，只 scp push，零 git 副作用。

### 5.5 传输用 scp（跨平台），护栏如何保留

传输统一用 scp 而非 rsync:scp 是 OpenSSH 标配，Mac/Win/Linux 都有，且走 ~/.ssh/config alias（含跳板机/
key）；macOS 自带的是残缺的 openrsync（无 `--mkpath` 等），Windows 一般无 rsync。scp 没有 rsync 的
include/exclude 和 `--dry-run`，护栏改这样落地（等价）：

- **push 只传声明项**:按 sync.yaml 的 `push` 清单**逐项 scp**（枚举即白名单），不整目录扫。
- **pull 锁死结果目录**:只 scp 远程顶层 `results/{metrics,plots,tables}/`，以及本地已声明的
  `sub_experiments/<slug>/results/{metrics,plots,tables}/`，绝不碰手写文档。
- **不删**:scp 天生不镜像删除。
- **--dry-run**:打印将传的 scp 命令、不执行（模拟）。
- scp 不建多级远程目录 → push 前先 ssh `mkdir -p`（复用 ssh 层，不碰凭据）。

### 5.6 远程路径映射入文件 + 首次由用户确认

远程工作区路径不再写死自动拼，而是显式记在 `sync.yaml` 的 `remote_path`：

- 空 = 首次未确认。`exp push/pull/run/start` 会算一个建议路径（`<remote_repro_root>/<方向>/<短名>`）、
  打印、**退出码 3、不碰远程**。
- 用户带 `--remote-path <路径>` 重跑 → 写回 `sync.yaml` → 执行；之后复用，不再问。
- **单一来源**:push/pull（sync.py）和 run/probe（ssh.py）都经 `sync.resolve_remote_path` 取同一路径，
  杜绝「确认的路径」与「run 实际去的路径」不一致。

## 6. 迁移（`repro/` → `experiments/` 属存储架构改动，必须只搬不丢、幂等、可回滚）

`helix migrate` 增补：

- **统一 workspace 根**：检测用户数据 `notes/`、`experiments/`、`draft_notes/` 还散在 workspace/ 外 →
  提示（或 `--yes` 执行）搬进 `workspace/`；每个目录 copytree→核对文件数→才删源，**绝不静默删**。
  `notes_dir` 为绝对路径（外部 Obsidian vault）则跳过、留在外部。`.helix/`（索引/缓存，运行时可重建）
  留在项目根、不搬。
- 检测旧 `repro/` 存在 → 提示（或 `--yes` 执行）整体移到 `experiments/`（现位于 workspace 下）；同样先校验后核对。
- config 字段改名：migrate 把旧 `repro_dir` 在 config.yaml 里原地改成 `experiments_dir`（保留用户的值、
  删旧名，不留双 key）；loader 不再读旧字段（开发阶段，抹旧留新）。缺 `workspace_dir` 等字段按模板补进
  config.yaml（承接「migrate 按模板补 config 字段」）。改名/补字段前均备份 `config.yaml.bak`。
- 给已有工作区补 `results/index.md` / `sync.yaml` / `RESULTS_LAYOUT.md` / `PROGRESS.md`（幂等，已存在跳过）；
  旧的单文件 `results.md`（若有）迁成 `results/index.md`。
- 给旧 `type:mine` 工作区补 `sub_experiments/README.md`，并把 `sync.yaml` 的 push/pull 清单升级到子实验结果结构；
  `RESULTS_LAYOUT.md` 只有仍是旧自动生成内容时才替换，避免覆盖用户手改。
- `PROGRESS.md` 是用户确认的轻量状态，不由 CLI 自动判定阶段。迁移旧工作区时当前阶段写「待判定」；
  agent 读取 `setup.md` / `plan.md` / `sub_experiments/` / `results/index.md` / 运行记录后给阶段建议，用户确认后再勾选。

正在用旧版的用户 `git pull` + `helix migrate` 一步平滑升级，笔记/复现数据一个不丢。

## 7. 分期

1. **重命名 + type + 子实验结构**：`repro_dir`→`experiments_dir`（migrate 原地改名、不留旧字段）、
   `exp` 子命令组、`results/index.md` 骨架 + `type` frontmatter、`RESULTS_LAYOUT.md` 骨架、
   `type:mine` 的 `sub_experiments/<slug>/` 骨架、migrate 搬 `repro/`→`experiments/`。
2. **传送带**：`remotes` config、`sync.yaml`、`exp push/pull`（scp 封装 + 护栏 + `--dry-run`，push 必带 RESULTS_LAYOUT.md）。
3. **回流落笔记**：reproduce skill 读 repro 顶层 `results/{metrics,plots,tables}/` 或 mine 子实验
   `sub_experiments/<slug>/results/{metrics,plots,tables}/`，蒸馏进对应 `results/index.md`；
   mine 再汇总顶层 claim；写「精读漏掉的问题」/「实验暴露的问题」，建索引；
   「写」板块按 `type` 捞素材（并入「写」板块设计文档）。
4. **远程执行**（本次）：`secrets.py`（凭据）、`ssh.py`（tmux/probe）、`vcs.py`（git 护栏）、
   `exp start/run/probe/sessions/kill`；凭据经 env/stdin 注入、绝不进大模型。见 §5。
5. **结束清理**：`exp clean` 预览/清理结果目录中的烟测、调试、临时试跑产物；默认不删，`--yes` 才执行。
