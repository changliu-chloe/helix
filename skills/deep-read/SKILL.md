---
name: deep-read
description: 当用户想深读、精读、总结、分析某一篇具体论文（给了 arXiv id 或标题），并把理解沉淀成结构化笔记时使用。
---

# 单篇论文深读

把一篇论文读透，产出结构化深读笔记。helix 负责抓元数据和建骨架，**深度理解与总结由你（agent）完成**。

> **运行约定**：所有 helix 命令用 `uv run helix ...` 在项目根执行（helix 装在项目 venv 里、不在全局 PATH；`uv run` 会自动定位项目 venv，从子目录也可用）。若 `uv` 不可用，回退 `python -m helix.cli ...`。

## 工作流程

### 1. 确定 arXiv id
- 用户给了 id（如 `2503.22020`）：直接用
- 用户给了标题：先 `uv run helix search "<标题关键词>" --top-n 5` 找到对应论文，取其 `paper_id`

### 2. 判断研究方向（不局限于 config 已有）
先 `uv run helix status` 看 config 已有的 research_domains，再判断这篇论文最贴切的研究方向：
- **命中已有方向**：直接用那个方向名
- **不属于任何已有方向**（尤其是 config 还很空时）：**你根据论文主题拟一个准确、简洁的新方向名**（如"多模态检索Agent"、"扩散策略"），不要硬塞进不相关的旧方向，也不要都丢"未分类"
- 若拟了**新方向**：**问用户**"这篇我归到「<新方向>」，要把它加进 config.yaml 的 research_domains 吗？"
  - 用户同意 → 编辑 config.yaml，在 research_domains 下加该方向（附几个关键词、arxiv_categories、priority）
  - 用户不要 → 只用于本篇归档，不动 config

### 3. 生成笔记骨架
```bash
uv run helix note new <arxiv_id> --domain "<第2步确定的方向>"
```
- `--domain` 指定归档方向（可以是 config 里还没有的新方向）；省略则按 config 已有方向自动判定
- 输出笔记文件路径（stdout）。骨架含 frontmatter（标题/作者/日期/分类/链接/领域）+ 摘要 + 待填小节
- 笔记按方向分目录存放：`notes/papers/<方向>/<短名>.md`
- **文件名默认取短名**：作者自命名（如 `CoT-VLA:`、`Mamba:` 冒号前的缩写）会被保留；否则取标题前几个词。完整标题仍存在 frontmatter 里，不丢信息。读完后可按第 5.5 步改成更贴切的短名。
- 已存在则跳过；要重建加 `--overwrite`（**注意：--overwrite 会覆盖已填的深读内容，慎用**）

### 4. 抓全文 + 高清图
```bash
uv run helix fetch <arxiv_id> --domain "<同上方向>"
```
- 输出 JSON：
  - `assets_dir`：资产目录
  - `fulltext`：MinerU 转的全文 markdown 路径（可能为 null）
  - `rendered_images`：**可渲染插图**清单（jpg，相对 assets 的路径如 `images/fig1.jpg`）——笔记内联用这套
  - `source_figures`：源码高清图（多为 pdf 矢量图，**存档用，不要内联到笔记**，标准 markdown 预览渲染不出 pdf）
- 全文和图存在 `notes/papers/<领域>/assets/<id>/`
- **读全文**：优先读 `assets_dir/fulltext.md`（MinerU 转的完整正文）。正文里已内联 `![](images/figN.jpg)`，**每张图紧挨其图注**（如 `Figure 1. ...`）——据此判断每张图讲什么
- 若 `fulltext` 为 null（没配 mineru_api_key 或解析失败）：退回读骨架里的摘要 + `pdf_url`，并在笔记注明"基于摘要"
- 离线或只要图：`uv run helix fetch <id> --no-mineru`

### 5. 填充深读笔记
编辑第 3 步生成的笔记文件，把 `<!-- agent: 待填写 -->` 的小节补上：
- **一句话总结**：核心贡献一句话
- **核心贡献**：3-5 个要点
- **方法**：方法/架构/关键设计，必要时用公式或伪代码
- **关键结果**：最重要的量化结果（数据集、指标、对比）
- **批判性分析**：创新点、优势、局限、适用场景，以及你的判断
- **相关工作**：用 `[[wikilink]]` 链接库里已有的相关笔记

**插图**：从 `rendered_images`（可渲染 jpg）里挑**真正有助于说明的**图，用**标准 markdown 语法**插入对应小节：
```
![Figure 1: 方法总览](assets/<id>/images/fig1.jpg)
```
- **必须用标准 `![](路径)` 语法，不要用 Obsidian 的 `![[...]]`**——后者在 VSCode/GitHub 等标准 markdown 预览里渲染不出来
- **路径前缀 `assets/<id>/`**：笔记在 `notes/papers/<方向>/`，图在其下 `assets/<id>/images/`，所以从笔记看相对路径是 `assets/<id>/images/figN.jpg`
- **只用 `rendered_images` 里的 jpg**，别引用 `source_figures` 的 `.pdf`（标准预览渲染不出 pdf）
- 怎么选图：读 `fulltext.md`，每张 `images/figN.jpg` 紧挨其图注，据此挑架构图/关键结果图，别把所有图都塞进去
- 在图下方一句话说明它讲了什么

保留 frontmatter 不动。语言跟随 config.yaml 的 `language`（zh/en）。

### 5.5 读完后定名（按需）
读透之后，判断第 3 步生成的短名是否贴切：
- **作者已自命名**（标题冒号前有缩写/自取名，如 CoT-VLA、Mamba、Self-RAG）：**保持不动**，这就是社区通用的叫法。
- **标题只是描述性的**（如 "Efficient Memory Management for LLM Serving"，短名会退化成前几个词）：按论文真正的**方法/创新名**改一个更贴切的短名。若论文里方法有名字（如 PagedAttention），用它。
```bash
uv run helix note rename <当前笔记路径> --name <新短名>
```
- rename 会**原地改名 + 自动同步全库指向它的 `[[wikilink]]`**，不丢引用；assets（按 arxiv id 存）不受影响。
- 目标名已存在会报错（不覆盖），换个名或确认后加 `--overwrite`。

### 6. 自动链接 + 建索引
```bash
uv run helix note link <笔记路径>    # 把正文里出现的其他论文名自动变成 wikilink
uv run helix index build             # 重建 FTS 索引，让这篇能被本地检索到
```

## 原则

- **忠实**：只写论文里有的内容，推断和评价要标明是你的判断
- **图文并茂**：`helix fetch` 已抓高清图到 assets，挑关键图用 `![[...]]` 嵌入，别只用文字干讲
- **可检索**：完成后一定重建索引，否则本地检索搜不到这篇
- **不臆造引用数**：arXiv 来源没有引用数，别编
