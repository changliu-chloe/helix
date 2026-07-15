# 设计文档：文献综述 + 独立评审打分（「读」板块）

> 本文档覆盖 helix「读」板块中**综述**与**论文深度打分**这一类需求。同类后续需求（综述形态演进、
> 打分维度调整、评审模型切换等）并入本文档，不另开文件。

## 1. 真实问题

用户在做文献综述时有两条路径：

1. **已有笔记汇总**：库里已读过某方向若干论文，想综合成一份综述；综述末尾再检索若干相关新文献。
2. **方向检索汇总**：给一个（可能不够精准的）方向，大量检索后生成综述。

两条路径都要求对论文做 **相关性 / 创新性 / 可靠性** 三维打分，且打分要「可靠」。

## 2. 核心决策

### 2.1 漏斗式：粗筛 → 入选才精读 → 精读后写

综述天然是漏斗。对几十篇候选逐篇精读（每篇 = MinerU 抓全文 + 长上下文阅读 + 打分）代价爆炸，
也没必要；但把没精读的论文写进综述正文又不可靠。故：

```
广撒网检索 N 篇 → 摘要级 relevance 粗筛 → top-N 入选（config review_funnel_top_n，可调）
                                              → 入选走 deep-read（含打分） → 综合成综述
```

用户「精读后再写更可靠」的原则完整保留，只是作用在漏斗窄口而非全部候选。粗筛宽口复用现有
`score.py` 四维分（便宜、确定性），窄口才上 LLM 精读 + 独立打分。

### 2.2 打分放进 deep-read，无论是否做综述

创新性与可靠性只有读完全文才判得准，故打分天然属于「精读」那一步。放进 deep-read 后：

- 路径 1（已有笔记）：笔记即深读产物，已带分，综述直接复用
- 路径 2（新方向）：粗筛 → 精读入选 → 打分随精读产生
- 单篇深读（不做综述）：也白捡一份三维分，独立有用

### 2.3 打分用独立评审（codex MCP），不自评

参考 `ref/aris`：其 `auto-paper-improvement-loop` 有一条血泪教训（`REVIEWER_BIAS_GUARD`）——
让做过深读、带着自己上下文的模型给同一篇打分，分数会从真实 3/10 虚高到 8/10；换**全新 codex 线程、
零先验上下文**，才能拿回真实的 3/10。

所以打分经 Codex MCP（`mcp__codex__codex`，`model_reasoning_effort: xhigh`）调一个独立评审模型，
**每次都用 fresh 线程**，不复用 `codex-reply`。调用形态照 aris 的 novelty-check：写 dossier 文件，
只把路径传给 codex，不把长文塞进 prompt。这是「更可靠」的关键机制。

### 2.4 两种打分不混为一谈（低耦合）

| | 现有 `score.py` 四维 | 新增 codex 三维 |
|---|---|---|
| 维度 | relevance/recency/popularity/quality | relevance/novelty/reliability |
| 依据 | 摘要，关键词匹配 | 全文，独立 LLM 判断 |
| 时机 | 检索时，确定性，便宜 | 精读时，需独立模型 |
| 用途 | 排序候选（漏斗宽口） | 单篇质量判断（写进笔记/综述） |
| 存储 | Paper.score_final（运行时） | 论文笔记 frontmatter `review_scores` |

四维分保留当粗筛，不动；三维分写进笔记 frontmatter，综述表从此读取，不重复打分。

## 3. 分层落地（遵循 CLAUDE.md）

- **确定性活在 `helix/*.py`**：
  - `review.py`：综述骨架生成（`build_review_skeleton` / `review_path_for` / `write_review`），落 `notes/reviews/<短名>.md`
  - `notes.py::set_review_scores`：把三维分写进论文笔记 frontmatter（幂等，保留 body 与其它键）
  - `config.py`：新增 `review_subdir` / `reviewer_model` / `review_funnel_top_n`（含默认值）
  - `cli.py`：`helix review new "<topic>"`、`helix note score <path> --relevance/--novelty/--reliability`
- **LLM 编排在 skills**：
  - `skills/review/SKILL.md`：编排两条路径 + 漏斗 + codex 打分子流程 + 综合成综述
  - `skills/deep-read/SKILL.md`：精读第 6 步内建 codex 三维打分
  - `skills/helix/SKILL.md`：意图路由加 review
- **CLI 绝不绑定 LLM provider**：codex 调用只在 skill 里由 agent 发起；CLI 只提供确定性 helper。

## 4. 迁移（CLAUDE.md §2，不丢数据）

- config 新字段（`review_subdir`/`reviewer_model`/`review_funnel_top_n`）：loader 给默认值，旧 config
  照读不报错；`helix migrate` 检测到并提示新增，**不改用户 config.yaml**。
- `review_scores` frontmatter 纯增量：旧笔记无此字段，综述表显示「—」。无存储搬迁。
- 新 skill `skills/review`：`init` / `migrate` 自动软链到 `.claude/skills` + `.agents/skills`。
- **Codex MCP 是环境层前置**（非 helix 能自动装）：打分依赖 agent 运行环境注册了 `codex` MCP server
  （`claude mcp add codex -s user -- codex mcp-server`，须重启，注册名须为 `codex`）。helix CLI 不代办
  （§不绑定 LLM provider）；README 搭环境第 4 步给了步骤，deep-read/review skill 会先探测可用性、
  不可用时提示用户注册并优雅降级（跳过打分/分数列填 —），不硬报错。

## 5. 数据结构

论文笔记 frontmatter 新增：

```yaml
review_scores:
  relevance: 8.0      # 0-10，对研究方向/综述主题的相关性
  novelty: 7.0        # 0-10，相对已有工作的增量
  reliability: 6.0    # 0-10，实验充分度/baseline 强度/结论可信度
  model: gpt-5.6-sol  # 评审模型
  notes: 一句话总评
  scored_at: 2026-07-15
```

综述笔记 frontmatter：`type: review` + `papers: [入选论文的笔记相对路径]`。
