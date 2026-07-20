# helix

人在环中（human-in-the-loop）的科研全流程助手。

围绕「**读 → 复现 → 写**」三个有机结合的板块，把论文科研的全流程串起来——每一步都由你（研究者）主导决策，CLI 与 skill 只做确定性工作和 LLM 编排，不替你拍板。

## 三大板块

1. **读**（已实现）：从 arXiv / Semantic Scholar / DBLP 检索追新，做结构化深读笔记、综述，建可检索的本地索引。
2. **复现**（部分实现）：从论文总结实验设置，按你的 GPU 判断能否复现、要不要降配，产出可执行复现方案。
3. **写**（规划中）：基于读过的笔记与复现结果，辅助撰写论文 / 毕设。

> 名字取「螺旋（helix）」——读、复现、写三条链交织上升，像 DNA 一样把科研工作有机缠绕成一个整体。

## 定位

- **人在环中**：关键判断（研究方向、复现可行性、写作结论）都交回给你，工具只提供依据与草稿，不越权决策。
- **混合形态**：Python CLI 负责检索/抓取/解析/打分/索引/显存判级等确定性工作；`skills/` 下的 SKILL.md 供外部 coding agent（Claude Code 等）调用来编排"深读/复现规划/写作"这类需要 LLM 的环节。CLI 本身不硬编码任何 LLM provider。
- **配置驱动**：检索方向、打分权重、硬件档全部由 `config.yaml` 决定。
- **笔记为主 + 索引可查**：深读/复现结果落 Markdown（可对接 Obsidian vault），另建 SQLite FTS5 全文索引供检索。

## 搭环境

```bash
# 1. 用 uv 建虚拟环境并安装（Python 3.13）
uv venv --python 3.13
uv pip install -e .

# 2. 复制配置模板（config.yaml 含 API key，已 gitignore，不进版本控制）
cp config.example.yaml config.yaml
# 按需编辑 config.yaml：research_domains、semantic_scholar_api_key、mineru_api_key、remotes（远程 GPU 机器）

# 2b.（可选）远程跑实验需要 SSH/sudo 密码时，另复制凭据模板（也已 gitignore，绝不进大模型）
# cp config.secrets.example.yaml config.secrets.yaml   # 优先配 SSH key 免密则无需此文件
# 用密码登录还需装 sshpass（brew install hudochenkov/sshpass/sshpass 或 apt install sshpass）

# 3. 启用自然语言触发（软链 skills + 规约到各 agent 的发现路径）
uv run helix init                    # 项目级：本项目目录下的 agent 生效
# uv run helix init --scope global   # 或全局：任何目录都能触发（软链到 ~/.claude/skills、~/.agents/skills）
```

> **怎么调用 helix**：装在项目 venv 里、不在全局 PATH。推荐 `uv run helix ...`（自动定位项目
> venv，任意目录可用）；或先 `source .venv/bin/activate` 后直接 `helix ...`；skills 里统一用 `uv run helix`。

> **数据布局**：用户数据落在单一 `workspace/` 下——`workspace/notes/{papers,daily,reviews}`、
> `workspace/experiments/`。运行时派生的 `.helix/`（FTS 索引/缓存，可重建）留在项目根、单独 gitignore。
> `notes_dir` 填绝对路径可指向外部 Obsidian vault（则留在外部）。旧版数据散在顶层的，`git pull` 后跑
> `helix migrate --yes` 搬进 workspace/（只搬不删、先校验；`.helix/` 不动）。

`helix init` 幂等，可反复执行；生成的软链含本机绝对路径，已 gitignore，**每台机器 clone 后各自跑一次**。
它一次接线两套 agent，同一份 skills 与规约两边共享：

- **Claude Code**：读 `CLAUDE.md` + `.claude/skills/`。
- **Codex / Cursor / Trae 等**：读 `AGENTS.md` + `.agents/skills/`。`AGENTS.md` 是指向 `CLAUDE.md`
  的软链（规约单一真源在 `CLAUDE.md`，不维护第二份）；skills 目录结构两家通用，直接兼容。

做完这步，就能在上述任一 agent 里用自然语言触发 search / deep-read / daily，无需手敲命令。

### 4.（可选）注册 Codex MCP —— 深读打分 / 文献综述才需要

深读（deep-read）与文献综述（review）里的**三维打分**（相关性/创新性/可靠性）用一个**独立评审模型**
经 Codex MCP 打分——独立评审避免自评虚高，是打分「可靠」的关键（见 [docs/literature-review.md](docs/literature-review.md)）。
这一步是 **agent 运行环境**的一次性前置，helix CLI 不代办（CLI 不绑定任何 LLM provider）。只用 search/daily/repro 可跳过。

以 Claude Code + Codex CLI 为例：

```bash
# 1. 装 OpenAI Codex CLI（见官方文档 https://developers.openai.com/codex）
codex --version
# 2. 一次性 ChatGPT 登录（浏览器流程，已登录可跳过）
codex login
# 3. 把 codex 注册成 Claude Code 的 MCP server（-s user 全局生效，配一次所有项目共用）
claude mcp add codex -s user -- codex mcp-server
# 4. 重启 Claude Code 后验证（应显示 codex: ... ✓ Connected）
claude mcp list | grep codex
```

- **注册名必须叫 `codex`**：skill 里用 `mcp__codex__codex` 调用，改名就调不到。
- 评审模型在 `config.yaml` 的 `reviewer_model` 配（默认 `gpt-5.6-sol`，须为 OpenAI 模型）。
- 没配也不影响 search/daily/repro；做深读/综述时 agent 会先探测 codex 是否可用，不可用会提示你先按本节注册。

### 升级（正在用的仓库 `git pull` 之后）

`git pull` 只更新代码文件，不会自动接线：新增的 skill 不会软链到 `.claude` / `.agents`、`AGENTS.md` 不会补上、新依赖不会装、config 新字段你也不会知道。拉完跑一次：

```bash
git pull
uv run helix migrate     # 幂等：重链新 skill、清失效软链，并提示还需手动做什么
```

`migrate` 会把 config 缺的新字段**按模板补进你的 `config.yaml`**（连注释、空占位一起追加到末尾；写前先备份 `config.yaml.bak`，只追加不动你现有内容，幂等），你只需填值。依赖有变化提示你 `uv sync --extra dev`（不自动装），笔记比索引新提示你 `index build`（不自动重建）。按它列出的「需手动处理」逐条做即可。

## 快速开始

```bash
uv run helix status                              # 查看配置与研究领域
uv run helix search "vision language action" --top-n 5   # 检索并打分
```

先编辑 `config.yaml`，把 `research_domains` 换成你的关注方向。

## 命令一览

| 命令 | 说明 | 状态 |
|---|---|---|
| `helix init` | 软链 skills 到 .claude/skills + .agents/skills、AGENTS.md→CLAUDE.md，启用自然语言触发（首次搭建） | ✅ |
| `helix migrate` | `git pull` 后追平：重链新 skill（含 .agents / AGENTS.md）、清失效软链、按模板补 config 缺失字段（备份+追加）、提示依赖/索引更新 | ✅ |
| `helix status` | 配置/库/索引状态 | ✅ |
| `helix search "<query>"` | 检索 + 4维打分（arxiv/s2/dblp 多源合并去重） | ✅ |
| `helix note new <id>` | 抓论文生成深读笔记骨架（文件用短名） | ✅ |
| `helix note rename <file> --name <短名>` | 改笔记短名 + 同步全库 wikilink | ✅ |
| `helix note scan` | 扫描笔记库建关键词映射 | ✅ |
| `helix note link <file>` | 正文关键词自动 wikilink | ✅ |
| `helix index build` | 建/更新 FTS5 全文索引 | ✅ |
| `helix index search "<q>"` | 本地全文检索（bm25 + snippet） | ✅ |
| `helix fetch <id>` | 抓全文（MinerU）+ 高清图（源码包）到 assets/ | ✅ |
| `helix exp vram --params <B>` | 显存估算 + 对各硬件档判级（装得下/量化/多卡TP/offload） | ✅ |
| `helix exp new <笔记\|id>` | 建复现工作区骨架（setup+plan+results/+RESULTS_LAYOUT+sync.yaml），`--draft` 落 draft_notes | ✅ |
| `helix exp new --mine "<实验名>"` | 建我自己的实验工作区（type:mine，无 setup.md，plan.md 即实验设计） | ✅ |
| `helix exp push/pull <工作区>` | 本地↔远程 GPU 传送带（scp 封装，跨平台；首次需 `--remote-path` 确认远程路径；`--dry-run` 预览；结果只回流 results/） | ✅ |
| `helix exp start <工作区>` | 开始实验：git 提交本轮改动 + push 代码上远程（远程代码=本地某 commit） | ✅ |
| `helix exp run <工作区> --cmd "..."` | 在远程 tmux 会话里跑命令（`--oneshot` 跑完退会话，`--sudo` 需提权，`--session` 指定会话名） | ✅ |
| `helix exp probe <工作区>` | 探远程磁盘/GPU 占用（JSON），跑实验前判断条件 | ✅ |
| `helix exp sessions/kill <工作区>` | 列 / 杀远程 tmux 会话 | ✅ |
| `helix note score <file> --relevance/--novelty/--reliability <N>` | 把独立评审的三维打分写进笔记 frontmatter | ✅ |
| `helix review new "<topic>"` | 建文献综述骨架（逐篇打分表 + 综合分析 + 相关文献补充） | ✅ |

`helix fetch` 全文解析需 MinerU 云端 key（config `mineru_api_key`）+ `uv pip install 'helix[fulltext]'`；
不配 key 时仅抽高清图（离线可用 `--no-mineru`）。`helix index search --vector` 向量检索接口已预留。

## Skills（供外部 agent 编排）

`skills/` 下是给 coding agent（Claude Code 等）读的决策手册。CLI 干确定性活（检索/解析/索引），
agent 负责需要 LLM 的深读与总结：

- `skills/helix/` — **总入口**：判断意图并路由到下面三个子流程（"读这篇论文 <id>"、"找些 X 论文"、"开启研究日"都先进这里）
- `skills/search/` — 检索路由：本地 FTS vs 跨源检索
- `skills/deep-read/` — 单篇深读：建骨架 → 读全文填充 → 链接 + 建索引
- `skills/daily/` — 开启研究日：批量检索 → 推荐笔记 → top-N 深读
- `skills/reproduce/` — 论文复现规划：抽取实验设置 → 可复现性分级 → 按 GPU 判级适配 → 产出可执行复现方案（借鉴 ref/deepcode 的 Paper2Code）。笔记/代码在本地、实验在远程时，agent 用 `helix exp start/run/probe/pull` 在远程 GPU 上编排跑实验（凭据锁在 CLI 不进大模型，见 [docs/reproduce-sync.md](docs/reproduce-sync.md)）
- `skills/review/` — 文献综述：两条路径（已有笔记汇总 / 方向检索汇总），漏斗式「粗筛→入选精读→综合」，逐篇由独立评审（Codex MCP）打相关性/创新性/可靠性三维分

`helix init` 后即可在对话里自然语言触发，例如直接说「读这篇论文：2503.22020」。

## 配置

编辑 `config.yaml`：
- `research_domains`：你的关注方向（关键词 / arXiv 分类 / 优先级）
- `score_weights`：四维打分权重（检索时的粗筛排序，见 score.py）
- `excluded_keywords`：排除词
- `semantic_scholar_api_key`：S2 API key（匿名接口限流严重，强烈建议填）
- `reviewer_model`：文献综述/深读时经 Codex MCP 调的独立评审模型（默认 `gpt-5.6-sol`，须为 OpenAI 模型）
- `review_funnel_top_n`：方向检索做综述时，摘要粗筛后取前 N 篇进精读（默认 10，可调）

> **两种打分别混**：检索时的四维分（relevance/recency/popularity/quality，摘要+关键词，便宜）只用来
> 排序候选、做综述漏斗的宽口粗筛；综述/深读的三维分（相关性/创新性/可靠性，全文+独立评审模型）是精读后的
> 深度判断，写进论文笔记 frontmatter 的 `review_scores`。独立评审用全新 Codex 线程零先验上下文，避免自评虚高。
> 详见 [docs/literature-review.md](docs/literature-review.md)。

## 设计来源

融合 `ref/evil-read-arxiv`（检索排序 + 深读笔记 + wikilink）与 `ref/scholaraio`（CLI 子命令 + FTS5 索引 + skill 决策手册）两个项目的运作模式。
