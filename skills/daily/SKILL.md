---
name: daily
description: 当用户说"开启研究日""今日论文""start my day""看看今天有什么新论文"时使用。批量检索最新论文、打分排序、生成每日推荐笔记，并对最高分的几篇触发深读。
---

# 开启研究日

生成今日论文推荐笔记：批量检索 → 打分排序 → 写推荐笔记 → top 几篇深读。

## 工作流程

### 1. 检索并打分
按 config.yaml 的研究领域检索最新论文：
```bash
arxo search --top-n 10 --days 30
```
- 无 query 时按 config 的 research_domains 分类检索近 30 天
- 想覆盖高引用经典论文，可加 `--source arxiv,s2`（需配 api_key，否则 s2 易限流）
- 输出 JSON，含每篇的四维打分和 `score_final`，已按分排序

### 2. 生成每日推荐笔记
在 `notes/daily/YYYY-MM-DD-推荐.md`（en 环境用 `YYYY-MM-DD-recommendations.md`）写推荐笔记：

frontmatter：
```yaml
---
date: YYYY-MM-DD
tags: [arxo, daily]
---
```

结构：
1. **今日概览**：基于 top 论文总结主要方向、趋势、质量分布、阅读建议
2. **推荐列表**：所有论文按分排序，统一格式
   - 标题（wikilink 到深读笔记，若已深读）、作者、链接、来源、分数
   - 一句话总结 + 核心贡献（从摘要提炼）

### 3. top 3 触发深读
对分数最高的 3 篇（且库里还没有笔记的），走 deep-read skill：
- `arxo note new <id>` 建骨架
- 读全文填充深读笔记
- 在每日推荐笔记里把这几篇的标题改成 `[[wikilink]]` 指向深读笔记

### 4. 收尾
```bash
arxo note link notes/daily/YYYY-MM-DD-推荐.md   # 正文里的论文名自动链接到已有笔记
arxo index build                                # 重建索引
```

## 原则

- **去重**：先 `arxo index search` 或看 notes/papers 下是否已有该论文笔记，已有则引用不重复深读
- **快速**：每日笔记让用户快速扫过，只有 top 3 详细深读，其余只写基本信息
- **忠实**：概览和总结基于真实摘要/打分，不臆造
- **日期**：用今天的真实日期（不确定就先确认）
