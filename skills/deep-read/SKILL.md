---
name: deep-read
description: 当用户想深读、精读、总结、分析某一篇具体论文（给了 arXiv id 或标题），并把理解沉淀成结构化笔记时使用。
---

# 单篇论文深读

把一篇论文读透，产出结构化深读笔记。arxo 负责抓元数据和建骨架，**深度理解与总结由你（agent）完成**。

> **运行约定**：所有 arxo 命令用 `uv run arxo ...` 在项目根执行（arxo 装在项目 venv 里、不在全局 PATH；`uv run` 会自动定位项目 venv，从子目录也可用）。若 `uv` 不可用，回退 `python -m arxo.cli ...`。

## 工作流程

### 1. 确定 arXiv id
- 用户给了 id（如 `2503.22020`）：直接用
- 用户给了标题：先 `uv run arxo search "<标题关键词>" --top-n 5` 找到对应论文，取其 `paper_id`

### 2. 判断研究方向（不局限于 config 已有）
先 `uv run arxo status` 看 config 已有的 research_domains，再判断这篇论文最贴切的研究方向：
- **命中已有方向**：直接用那个方向名
- **不属于任何已有方向**（尤其是 config 还很空时）：**你根据论文主题拟一个准确、简洁的新方向名**（如"多模态检索Agent"、"扩散策略"），不要硬塞进不相关的旧方向，也不要都丢"未分类"
- 若拟了**新方向**：**问用户**"这篇我归到「<新方向>」，要把它加进 config.yaml 的 research_domains 吗？"
  - 用户同意 → 编辑 config.yaml，在 research_domains 下加该方向（附几个关键词、arxiv_categories、priority）
  - 用户不要 → 只用于本篇归档，不动 config

### 3. 生成笔记骨架
```bash
uv run arxo note new <arxiv_id> --domain "<第2步确定的方向>"
```
- `--domain` 指定归档方向（可以是 config 里还没有的新方向）；省略则按 config 已有方向自动判定
- 输出笔记文件路径（stdout）。骨架含 frontmatter（标题/作者/日期/分类/链接/领域）+ 摘要 + 待填小节
- 笔记按方向分目录存放：`notes/papers/<方向>/<标题>.md`
- 已存在则跳过；要重建加 `--overwrite`（**注意：--overwrite 会覆盖已填的深读内容，慎用**）

### 4. 抓全文 + 高清图
```bash
uv run arxo fetch <arxiv_id> --domain "<同上方向>"
```
- 输出 JSON：`assets_dir`（资产目录）、`fulltext`（MinerU 转的全文 markdown 路径，可能为 null）、`figures`（高清图清单）
- 全文和图存在 `notes/papers/<领域>/assets/<id>/`
- **读全文**：优先读 `assets_dir/fulltext.md`（MinerU 转的完整正文），重点抓研究问题、方法、关键实验、结论、局限
- 若 `fulltext` 为 null（没配 mineru_api_key 或解析失败）：退回读骨架里的摘要 + `pdf_url`，并在笔记注明"基于摘要"
- 离线或只要图：`uv run arxo fetch <id> --no-mineru`

### 5. 填充深读笔记
编辑第 3 步生成的笔记文件，把 `<!-- agent: 待填写 -->` 的小节补上：
- **一句话总结**：核心贡献一句话
- **核心贡献**：3-5 个要点
- **方法**：方法/架构/关键设计，必要时用公式或伪代码
- **关键结果**：最重要的量化结果（数据集、指标、对比）
- **批判性分析**：创新点、优势、局限、适用场景，以及你的判断
- **相关工作**：用 `[[wikilink]]` 链接库里已有的相关笔记

**插图**：从第 4 步 `figures` 清单里挑**真正有助于说明的**图（通常是架构图 method/teaser、关键结果图 ablation/rollout），在对应小节用 Obsidian 嵌入语法插入：
```
![[assets/<id>/method.png]]
```
- 图名有含义（method/teaser/ablation…），按名选图，别把所有图都塞进去
- 源码图常是 `.pdf` 矢量图，Obsidian 也能嵌入；优先选 `.png`
- 在图下方一句话说明它讲了什么

保留 frontmatter 不动。语言跟随 config.yaml 的 `language`（zh/en）。

### 6. 自动链接 + 建索引
```bash
uv run arxo note link <笔记路径>    # 把正文里出现的其他论文名自动变成 wikilink
uv run arxo index build             # 重建 FTS 索引，让这篇能被本地检索到
```

## 原则

- **忠实**：只写论文里有的内容，推断和评价要标明是你的判断
- **图文并茂**：`arxo fetch` 已抓高清图到 assets，挑关键图用 `![[...]]` 嵌入，别只用文字干讲
- **可检索**：完成后一定重建索引，否则本地检索搜不到这篇
- **不臆造引用数**：arXiv 来源没有引用数，别编
