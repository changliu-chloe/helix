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
# 按需编辑 config.yaml：research_domains、semantic_scholar_api_key、mineru_api_key

# 3. 启用自然语言触发（软链 skills + 规约到各 agent 的发现路径）
uv run helix init                    # 项目级：本项目目录下的 agent 生效
# uv run helix init --scope global   # 或全局：任何目录都能触发（软链到 ~/.claude/skills、~/.agents/skills）
```

> **怎么调用 helix**：装在项目 venv 里、不在全局 PATH。推荐 `uv run helix ...`（自动定位项目
> venv，任意目录可用）；或先 `source .venv/bin/activate` 后直接 `helix ...`；skills 里统一用 `uv run helix`。

`helix init` 幂等，可反复执行；生成的软链含本机绝对路径，已 gitignore，**每台机器 clone 后各自跑一次**。
它一次接线两套 agent，同一份 skills 与规约两边共享：

- **Claude Code**：读 `CLAUDE.md` + `.claude/skills/`。
- **Codex / Cursor / Trae 等**：读 `AGENTS.md` + `.agents/skills/`。`AGENTS.md` 是指向 `CLAUDE.md`
  的软链（规约单一真源在 `CLAUDE.md`，不维护第二份）；skills 目录结构两家通用，直接兼容。

做完这步，就能在上述任一 agent 里用自然语言触发 search / deep-read / daily，无需手敲命令。

### 升级（正在用的仓库 `git pull` 之后）

`git pull` 只更新代码文件，不会自动接线：新增的 skill 不会软链到 `.claude` / `.agents`、`AGENTS.md` 不会补上、新依赖不会装、config 新字段你也不会知道。拉完跑一次：

```bash
git pull
uv run helix migrate     # 幂等：重链新 skill、清失效软链，并提示还需手动做什么
```

`migrate` **默认不改你的数据**：config 缺哪些新字段只提示（不动你的 `config.yaml`），依赖有变化提示你 `uv sync --extra dev`（不自动装），笔记比索引新提示你 `index build`（不自动重建）。按它列出的「需手动处理」逐条做即可。

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
| `helix migrate` | `git pull` 后追平：重链新 skill（含 .agents / AGENTS.md）、清失效软链、提示 config/依赖/索引更新 | ✅ |
| `helix status` | 配置/库/索引状态 | ✅ |
| `helix search "<query>"` | 检索 + 4维打分（arxiv/s2/dblp 多源合并去重） | ✅ |
| `helix note new <id>` | 抓论文生成深读笔记骨架（文件用短名） | ✅ |
| `helix note rename <file> --name <短名>` | 改笔记短名 + 同步全库 wikilink | ✅ |
| `helix note scan` | 扫描笔记库建关键词映射 | ✅ |
| `helix note link <file>` | 正文关键词自动 wikilink | ✅ |
| `helix index build` | 建/更新 FTS5 全文索引 | ✅ |
| `helix index search "<q>"` | 本地全文检索（bm25 + snippet） | ✅ |
| `helix fetch <id>` | 抓全文（MinerU）+ 高清图（源码包）到 assets/ | ✅ |
| `helix repro vram --params <B>` | 显存估算 + 对各硬件档判级（装得下/量化/多卡TP/offload） | ✅ |
| `helix repro new <笔记\|id>` | 建论文复现工作区骨架（setup.md + plan.md），`--draft` 落 draft_notes | ✅ |

`helix fetch` 全文解析需 MinerU 云端 key（config `mineru_api_key`）+ `uv pip install 'helix[fulltext]'`；
不配 key 时仅抽高清图（离线可用 `--no-mineru`）。`helix index search --vector` 向量检索接口已预留。

## Skills（供外部 agent 编排）

`skills/` 下是给 coding agent（Claude Code 等）读的决策手册。CLI 干确定性活（检索/解析/索引），
agent 负责需要 LLM 的深读与总结：

- `skills/helix/` — **总入口**：判断意图并路由到下面三个子流程（"读这篇论文 <id>"、"找些 X 论文"、"开启研究日"都先进这里）
- `skills/search/` — 检索路由：本地 FTS vs 跨源检索
- `skills/deep-read/` — 单篇深读：建骨架 → 读全文填充 → 链接 + 建索引
- `skills/daily/` — 开启研究日：批量检索 → 推荐笔记 → top-N 深读
- `skills/reproduce/` — 论文复现规划：抽取实验设置 → 可复现性分级 → 按 GPU 判级适配 → 产出可执行复现方案（借鉴 ref/deepcode 的 Paper2Code）

`helix init` 后即可在对话里自然语言触发，例如直接说「读这篇论文：2503.22020」。

## 配置

编辑 `config.yaml`：
- `research_domains`：你的关注方向（关键词 / arXiv 分类 / 优先级）
- `score_weights`：四维打分权重
- `excluded_keywords`：排除词（如不想要综述可加 `survey`）
- `semantic_scholar_api_key`：S2 API key（匿名接口限流严重，强烈建议填）

## 设计来源

融合 `ref/evil-read-arxiv`（检索排序 + 深读笔记 + wikilink）与 `ref/scholaraio`（CLI 子命令 + FTS5 索引 + skill 决策手册）两个项目的运作模式。
