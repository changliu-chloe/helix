---
name: review
description: 当用户想做文献综述、综述某个方向、把已读论文汇总成综述、或对某研究方向大量检索后生成综述笔记时使用。两条路径：已有笔记汇总 / 方向检索后精读汇总。
allowed-tools: Bash(*), Read, Grep, Glob, Write, Edit, WebSearch, WebFetch, mcp__codex__codex, mcp__codex__codex-reply
---

# 文献综述

把某个方向的多篇论文综合成一份综述笔记。helix 负责确定性活（生成综述骨架、把打分写进 frontmatter），
**精读、打分判断、综合分析由你（agent）编排 LLM 完成**。

> **运行约定**：所有 helix 命令用 `uv run helix ...` 在项目根执行（helix 装在项目 venv 里、不在全局 PATH）。若 `uv` 不可用，回退 `python -m helix.cli ...`。

## 核心原则：漏斗式，精读后再写

综述是漏斗——**广撒网粗筛 → 入选才精读 → 精读后写进综述**。绝不对几十篇候选逐篇精读（代价爆炸），
也绝不把没精读的论文写进综述正文（不可靠）。粗筛用摘要级 relevance，入选（默认 config `review_funnel_top_n`，可与用户商量调整）才走 deep-read（含独立打分）。

## 常量

- REVIEWER_MODEL = config 的 `reviewer_model`（默认 `gpt-5.6-sol`）——经 Codex MCP 调用，须为 OpenAI 模型
- 打分独立性铁律：**每次打分都用全新 `mcp__codex__codex` 线程、零先验上下文**。绝不用做过深读的自己去评自己的总结（会虚高），也不复用 `codex-reply` 累积上下文。

## 两条路径

先判断用户是「汇总我已读的」还是「给方向、大量检索」。

### 路径 1：已有笔记汇总
用户想把库里已读的某方向论文汇总成综述。

1. **找相关笔记**：`uv run helix index search "<方向词>" --limit 20`（索引不存在先 `index build`）。
2. **确认入选集**：把命中笔记列给用户，确认纳入哪些。
3. **补打分**：逐篇看笔记 frontmatter 是否已有 `review_scores`。缺的走「打分子流程」（见下），`uv run helix note score` 写回。
4. **建综述骨架**：`uv run helix review new "<综述主题>"`（见「综合成综述」）。
5. **收尾检索**：综述写完后，再 `uv run helix search "<方向词>" --source arxiv,s2 --top-n 8` 找几篇**相关但库里还没有**的新文献，列进综述末尾「相关文献补充」，每篇一句话（不精读、不打分，标注「延伸阅读」）。

### 路径 2：方向检索 + 精读汇总
用户给一个方向（可能不够精准），要大量检索后生成综述。

1. **广撒网**：`uv run helix search "<方向词>" --source arxiv,s2,dblp --top-n 40`。方向不精准时，先跟用户对齐核心主题词，或换几组 query 重搜。
2. **摘要级粗筛**：search 输出已含四维分并按 `score_final` 排序。取 top `review_funnel_top_n`（默认 10）作为精读入选；把候选清单和入选建议列给用户，让用户人在环中增删。
3. **入选精读**：对每篇入选论文走 **deep-read skill**（`note new` → `fetch` 读全文 → 填笔记 → **codex 三维打分** → `note score`）。deep-read 已内建打分步骤，照它走即可。
4. **建综述骨架 + 综合**：见下。

## 打分子流程（codex MCP，独立评审）

**前置探测**：本流程依赖 Codex MCP。开始综述前先确认工具列表里有 `mcp__codex__codex`；没有就提示用户
先注册（见 README 搭环境第 4 步：`claude mcp add codex -s user -- codex mcp-server`，重启后生效），
并问用户是要先去配、还是先出一版**不带三维打分**的综述（逐篇表分数列填 —，正文照常综合）。别硬报错卡死。

对一篇**已精读**的论文打三维分（0-10）。照 `skills/deep-read` 第 6 步与 novelty-check 的 dossier 模式：

1. 写一个 dossier 文件（如 `.helix/review_dossier_<短名>.md`），含：
   - 论文标题、方向、**综述主题/问题**（relevance 相对它判定）
   - 论文全文路径 `notes/papers/<方向>/assets/<id>/fulltext.md`（或摘要，若无全文）
   - 三个评分问题：
     - **相关性(relevance)**：与本综述主题的贴合度
     - **创新性(novelty)**：相对已有工作的增量，最近似的前作是什么、delta 在哪
     - **可靠性(reliability)**：实验是否充分、baseline 是否强、结论是否被证据支撑、有无明显缺陷
   - 要求：每维 0-10 打分 + 一句话理由，最后给一句总评
2. 调用（**fresh 线程，勿复用**）：
   ```
   mcp__codex__codex:
     model: <REVIEWER_MODEL>
     config: {"model_reasoning_effort": "xhigh"}
     sandbox: read-only
     prompt: |
       Read the review dossier at <dossier 绝对路径> and follow all instructions in it.
   ```
3. 把结果写回论文笔记：
   ```bash
   uv run helix note score <笔记路径> --relevance <N> --novelty <N> --reliability <N> --note "<一句话总评>"
   ```
   评分的详细理由补进笔记「批判性分析」小节。

## 综合成综述

1. 建骨架：`uv run helix review new "<综述主题>" [--name <短名>]`（落 `notes/reviews/<短名>.md`）。
2. 填骨架每个 `<!-- agent: … -->`：
   - **综述范围与问题**、**方法脉络**（按技术路线归类入选论文）
   - **逐篇要点表**：每篇一行，`相关性/创新性/可靠性` 三列**取自各论文笔记 frontmatter 的 `review_scores`**（没打分的填 —），标题用 `[[wikilink]]` 指向论文笔记
   - **综合分析**：跨论文趋势、共识/分歧、研究空白、可切入机会
   - **相关文献补充**：路径 1 第 5 步 / 路径 2 收尾检索到的延伸阅读
   - **参考**：用 `[[wikilink]]` 链接所有入选笔记
   - frontmatter 的 `papers:` 列表填入选论文的笔记相对路径
3. 收尾：
   ```bash
   uv run helix note link notes/reviews/<短名>.md   # 正文论文名自动 wikilink
   uv run helix index build                          # 让综述可被本地检索
   ```

## 原则
- **精读后再写**：只有精读并打过分的论文才进综述正文；延伸阅读单列、标注未精读。
- **打分独立**：codex fresh 线程评审，不自评。分数是论文内在判断，存论文笔记 frontmatter，综述从此引用（不重复打分）。
- **忠实**：综合分析基于真实笔记与打分，不臆造趋势或引用数。
- **人在环中**：入选集、方向词、纳入范围都让用户确认，工具只给依据与草稿。
