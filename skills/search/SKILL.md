---
name: search
description: 当用户想检索论文、查本地笔记库、跨 arXiv/S2/DBLP 找文献、按关键词或领域搜索时使用。路由到 helix 的本地 FTS 检索或跨源检索。
---

# 论文检索路由

helix 有两类检索，先判断用户意图选对命令。

> **运行约定**：所有 helix 命令用 `uv run helix ...` 在项目根执行（helix 装在项目 venv 里、不在全局 PATH；`uv run` 会自动定位项目 venv）。若 `uv` 不可用，回退 `python -m helix.cli ...`。

## 决策逻辑

1. **查已读过的/本地笔记库** → 用本地 FTS5 全文索引
   - 关键信号："我之前读过的"、"我笔记里"、"本地"、"我收藏的关于 X 的论文"
   - 命令：`uv run helix index search "<查询词>" --limit <N>`
   - 若报"索引不存在"，先执行 `uv run helix index build` 再检索
   - 笔记有更新后也要先 `uv run helix index build` 重建索引

2. **找新论文/追踪最新进展** → 跨源检索
   - 关键信号："最新的"、"arXiv 上"、"高引用的"、"经典论文"、"会议论文"
   - 命令：`uv run helix search "<查询词>" --source <sources> --top-n <N>`
   - 来源选择：
     - `arxiv`（默认）：最新预印本，适合追踪前沿
     - `s2`：Semantic Scholar，带引用数，适合找高引用经典论文（非 arXiv 也能搜到）
     - `dblp`：会议/期刊论文，带权威 venue（CVPR/NeurIPS 等）
     - 多源用逗号连：`--source arxiv,s2,dblp`（自动合并去重）

3. **按 config 领域批量追踪**（无明确查询词）
   - 命令：`uv run helix search --top-n 10`（留空 query，按 config.yaml 的 research_domains 分类检索近 30 天）

## 输出说明

`uv run helix search` 输出 JSON，每篇论文含四维打分（relevance/recency/popularity/quality）和最终分 `score_final`（0-10）。已按最终分降序排列。stderr 打印进度和排名摘要。

`uv run helix index search` 输出命中笔记的 path/title/snippet（含 `[高亮]`）/bm25 rank。

## 查询词技巧

- 主题词保持稳定，不要把作者名、年份混进 query
- arXiv 关键词模式默认不限日期；要限时间加 `--days 30`
- 结果太少时去掉限定词，只留核心主题词重搜

## 注意

- S2 匿名接口限流严重。若 `--source s2` 频繁失败，检查 config.yaml 是否已配 `semantic_scholar_api_key`
- 单源失败不影响其他源，helix 会自动跳过失败的源继续
