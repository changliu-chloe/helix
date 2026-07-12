# arxo

论文检索追踪 + 深读理解 CLI。

从 arXiv / Semantic Scholar / DBLP 检索并追踪你关注领域的最新论文，做深度阅读与结构化 Markdown 笔记，并建立可检索的本地索引。

## 定位

- **混合形态**：Python CLI 负责检索/抓取/解析/打分/索引等确定性工作；`skills/` 下的 SKILL.md 供外部 coding agent（Claude Code 等）调用来编排"深读/总结"这类需要 LLM 的环节。CLI 本身不硬编码任何 LLM provider。
- **配置驱动**：检索方向、打分权重全部由 `config.yaml` 决定。
- **笔记为主 + 索引可查**：深读结果落 Markdown（可对接 Obsidian vault），另建 SQLite FTS5 全文索引供检索。

## 搭环境

```bash
# 1. 用 uv 建虚拟环境并安装（Python 3.13）
uv venv --python 3.13
uv pip install -e .

# 2. 启用自然语言触发（把 skills 软链到 .claude/skills/）
arxo init                    # 项目级：仅本项目目录下的 Claude Code 生效
# arxo init --scope global   # 或全局：任何目录都能触发（软链到 ~/.claude/skills/）
```

`arxo init` 幂等，可反复执行；软链含本机绝对路径，已 gitignore，**每台机器 clone 后各自跑一次**。
做完这步，就能在 Claude Code 等支持 skill 的 agent 里用自然语言触发 search / deep-read / daily，
无需手敲命令。纯 CLI（`arxo search` 等）不依赖这步，随时可用。

## 快速开始

```bash
arxo status                              # 查看配置与研究领域
arxo search "vision language action" --top-n 5   # 检索并打分
```

先编辑 `config.yaml`，把 `research_domains` 换成你的关注方向。

## 命令一览

| 命令 | 说明 | 状态 |
|---|---|---|
| `arxo init` | 软链 skills 到 .claude/skills，启用自然语言触发 | ✅ |
| `arxo status` | 配置/库/索引状态 | ✅ |
| `arxo search "<query>"` | 检索 + 4维打分（arxiv/s2/dblp 多源合并去重） | ✅ |
| `arxo note new <id>` | 抓论文生成深读笔记骨架 | ✅ |
| `arxo note scan` | 扫描笔记库建关键词映射 | ✅ |
| `arxo note link <file>` | 正文关键词自动 wikilink | ✅ |
| `arxo index build` | 建/更新 FTS5 全文索引 | ✅ |
| `arxo index search "<q>"` | 本地全文检索（bm25 + snippet） | ✅ |
| `arxo fetch <id>` | 抓取全文/图片 | 计划中 |

`arxo index search --vector` 向量检索接口已预留，实现待后续（接 sentence-transformers）。

## Skills（供外部 agent 编排）

`skills/` 下是给 coding agent（Claude Code 等）读的决策手册。CLI 干确定性活（检索/解析/索引），
agent 负责需要 LLM 的深读与总结：

- `skills/search/` — 检索路由：本地 FTS vs 跨源检索
- `skills/deep-read/` — 单篇深读：建骨架 → 读全文填充 → 链接 + 建索引
- `skills/daily/` — 开启研究日：批量检索 → 推荐笔记 → top-N 深读

## 配置

编辑 `config.yaml`：
- `research_domains`：你的关注方向（关键词 / arXiv 分类 / 优先级）
- `score_weights`：四维打分权重
- `excluded_keywords`：排除词（如不想要综述可加 `survey`）
- `semantic_scholar_api_key`：S2 API key（匿名接口限流严重，强烈建议填）

## 设计来源

融合 `ref/evil-read-arxiv`（检索排序 + 深读笔记 + wikilink）与 `ref/scholaraio`（CLI 子命令 + FTS5 索引 + skill 决策手册）两个项目的运作模式。
