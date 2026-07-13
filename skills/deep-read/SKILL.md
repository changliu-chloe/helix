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

### 2. 生成笔记骨架
```bash
uv run arxo note new <arxiv_id>
```
- 输出笔记文件路径（stdout）。骨架含 frontmatter（标题/作者/日期/分类/链接/领域）+ 摘要 + 待填小节
- 笔记按命中领域分目录存放：`notes/papers/<领域>/<标题>.md`
- 已存在则跳过；要重建加 `--overwrite`

### 3. 抓全文 + 高清图
```bash
uv run arxo fetch <arxiv_id>
```
- 输出 JSON：`assets_dir`（资产目录）、`fulltext`（MinerU 转的全文 markdown 路径，可能为 null）、`figures`（高清图清单）
- 全文和图存在 `notes/papers/<领域>/assets/<id>/`
- **读全文**：优先读 `assets_dir/fulltext.md`（MinerU 转的完整正文），重点抓研究问题、方法、关键实验、结论、局限
- 若 `fulltext` 为 null（没配 mineru_api_key 或解析失败）：退回读骨架里的摘要 + `pdf_url`，并在笔记注明"基于摘要"
- 离线或只要图：`uv run arxo fetch <id> --no-mineru`

### 4. 填充深读笔记
编辑第 2 步生成的笔记文件，把 `<!-- agent: 待填写 -->` 的小节补上：
- **一句话总结**：核心贡献一句话
- **核心贡献**：3-5 个要点
- **方法**：方法/架构/关键设计，必要时用公式或伪代码
- **关键结果**：最重要的量化结果（数据集、指标、对比）
- **批判性分析**：创新点、优势、局限、适用场景，以及你的判断
- **相关工作**：用 `[[wikilink]]` 链接库里已有的相关笔记

**插图**：从第 3 步 `figures` 清单里挑**真正有助于说明的**图（通常是架构图 method/teaser、关键结果图 ablation/rollout），在对应小节用 Obsidian 嵌入语法插入：
```
![[assets/<id>/method.png]]
```
- 图名有含义（method/teaser/ablation…），按名选图，别把所有图都塞进去
- 源码图常是 `.pdf` 矢量图，Obsidian 也能嵌入；优先选 `.png`
- 在图下方一句话说明它讲了什么

保留 frontmatter 不动。语言跟随 config.yaml 的 `language`（zh/en）。

### 5. 自动链接 + 建索引
```bash
uv run arxo note link <笔记路径>    # 把正文里出现的其他论文名自动变成 wikilink
uv run arxo index build             # 重建 FTS 索引，让这篇能被本地检索到
```

## 原则

- **忠实**：只写论文里有的内容，推断和评价要标明是你的判断
- **图文并茂**：`arxo fetch` 已抓高清图到 assets，挑关键图用 `![[...]]` 嵌入，别只用文字干讲
- **可检索**：完成后一定重建索引，否则本地检索搜不到这篇
- **不臆造引用数**：arXiv 来源没有引用数，别编
