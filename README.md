# arxo

论文检索追踪 + 深读理解 CLI。

从 arXiv / Semantic Scholar / DBLP 检索并追踪你关注领域的最新论文，做深度阅读与结构化 Markdown 笔记，并建立可检索的本地索引。

## 定位

- **混合形态**：Python CLI 负责检索/抓取/解析/打分/索引等确定性工作；`skills/` 下的 SKILL.md 供外部 coding agent（Claude Code 等）调用来编排"深读/总结"这类需要 LLM 的环节。CLI 本身不硬编码任何 LLM provider。
- **配置驱动**：检索方向、打分权重全部由 `config.yaml` 决定。
- **笔记为主 + 索引可查**：深读结果落 Markdown（可对接 Obsidian vault），另建 SQLite FTS5 全文索引供检索。

## 安装

```bash
pip install -e .
```

## 快速开始

```bash
arxo status                              # 查看配置与研究领域
arxo search "vision language action" --top-n 5   # 检索并打分（迭代 1）
```

先编辑 `config.yaml`，把 `research_domains` 换成你的关注方向。

## 命令一览

| 命令 | 说明 | 状态 |
|---|---|---|
| `arxo status` | 配置/库/索引状态 | ✅ |
| `arxo search "<query>"` | 检索 + 4维打分 | 迭代 1 |
| `arxo fetch <id>` | 抓取单篇全文/图片 | 迭代 2 |
| `arxo note new/scan/link` | 笔记生成 + wikilink | 迭代 2 |
| `arxo index build/search` | FTS5 全文索引 | 迭代 3 |

## 设计来源

融合 `ref/evil-read-arxiv`（检索排序 + 深读笔记 + wikilink）与 `ref/scholaraio`（CLI 子命令 + FTS5 索引 + skill 决策手册）两个项目的运作模式。
