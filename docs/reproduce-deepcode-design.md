# 设计文档：参考 DeepCode 的实验复现工作流

> 本文档覆盖 helix「复现」板块中**从论文理解到代码实现、远程运行、结果回流**的 agent 工作流设计。
> 本地-远程传送带、凭据、tmux、sync.yaml 等底层能力见 [docs/reproduce-sync.md](reproduce-sync.md)；
> 本文只定义 Paper2Code 风格的上层编排与 skill 拆分。

## 1. 真实问题

现有 `skills/reproduce/SKILL.md` 已经能把一篇论文转成复现工作区：

- `setup.md`：原文实验设置；
- `plan.md`：本机/远程怎么跑；
- `sync.yaml`：本实验远程传送清单；
- `results/index.md`：结果回流后的加工笔记。

缺口在于：从论文到可执行实验仍主要依赖 agent 临场发挥。复杂论文复现时，agent 容易漏掉算法细节、实验矩阵、
baseline、数据处理、环境约束，或者直接开始写代码，最后跑不出可验证结果。

DeepCode 的 Paper2Code 值得借鉴的地方不是“让 helix 自己写代码”，而是它把复现拆成了清晰的中间产物：

1. 论文结构和概念分析；
2. 算法、公式、超参、实验设置抽取；
3. 完整实现计划；
4. 用户审阅计划；
5. 按组件实现并即时测试；
6. 运行、监控、结果验证。

helix 要吸收这套结构，但边界保持不变：**确定性能力在 CLI，LLM 编排在 skills，代码实现由本地 coding agent 完成，
远程执行经 `helix exp` 走受控通道。**

## 2. 参考 DeepCode 的核心设计点

主要参考文件：

- `ref/deepcode/prompts/code_prompts.py`
  - `PAPER_CONCEPT_ANALYSIS_PROMPT`
  - `PAPER_ALGORITHM_ANALYSIS_PROMPT`
  - `CODE_PLANNING_PROMPT`
  - `PURE_CODE_IMPLEMENTATION_SYSTEM_PROMPT`
- `ref/deepcode/workflows/code_implementation_workflow.py`
- `ref/deepcode/workflows/plan_review_runtime.py`
- `ref/deepcode/workflows/environment.py`

可吸收的原则：

| DeepCode 设计 | helix 吸收方式 |
|---|---|
| 分段读论文，按 method/algorithm/experiment/setup 定向取材 | deep-read 产物 + fulltext 分段检索，避免一次性长上下文硬读 |
| 概念分析和算法抽取分离 | `paper-to-setup` 先写事实，`setup-to-plan` 再写行动 |
| 计划必须包含 file_structure / implementation_components / validation / environment / strategy | 强化 `plan.md` 模板和 reproduce skill 填写要求 |
| plan review 由用户批准或修改 | 全量实验启动、物理机环境变更、远程路径确认都保留人审 |
| 实现时核心算法优先，每个组件立即测试 | `plan-to-code` 子流程要求先核心、后集成、边写边测 |
| 参考代码只能启发，原论文优先 | 后续如加 code reference index，必须标注 reference-only |
| 任务目录隔离、输入校验、进度记录 | 复用 `experiments/<domain>/<short>/`，记录本轮状态和 tmux 会话 |

不吸收的部分：

- 不把 DeepCode 的通用 agent runtime 搬进 helix；
- 不让 helix CLI 直接调用 LLM 或生成代码；
- 不做 Web UI / session store / 通用 sandbox；
- 不把官方实现或第三方代码当成论文真值。

## 3. 建议的 skill/子流程拆分

短期不新增过多顶层 skill，先把 `reproduce` 主 skill 内部拆成 4 个稳定子流程：

```text
deep-read
  ↓
paper-to-setup
  ↓
setup-to-plan
  ↓
plan-to-code
  ↓
run-monitor-analyze
```

### 3.1 `paper-to-setup`：论文事实抽取

输入：

- 深读笔记；
- `assets/<paper_id>/fulltext.md`；
- 论文 PDF/图表资产；
- 可选官方仓库链接、第三方复现链接。

输出：

- 填好的 `setup.md`；
- 若信息不足，在 `setup.md` 中显式标注“论文未给出 / 推断 / 需要用户确认”。

抽取内容：

- paper structure map：论文主张、方法章节、实验章节、关键表图；
- method decomposition：核心模块、模块交互、数据流；
- algorithms：伪代码、公式、损失函数、优化过程；
- training procedure：batch、epoch/steps、optimizer、lr、scheduler、precision；
- datasets：下载、预处理、划分、子集；
- baselines：是否需要复现、是否可引用官方/第三方实现；
- metrics：定义、计算方式、对齐原文哪张表；
- hardware/software：GPU、CUDA、框架、依赖版本。

约束：

- `setup.md` 只写原文事实，不写本机方案；
- 论文没有明说的内容必须标注来源和置信度；
- 不为了完整性编造超参。

### 3.2 `setup-to-plan`：可执行复现计划

输入：

- `setup.md`；
- 本地 `config.yaml` 的硬件档；
- `uv run helix exp vram ...` 显存判级；
- 当前远程机器 `uv run helix exp probe <工作区>` 的资源状态。

输出：

- 填好的 `plan.md`。

`plan.md` 必须包含：

```yaml
file_structure: 本实验需要的代码/配置/脚本结构
implementation_components: 核心算法、模型、数据、评测模块如何落到文件
validation_approach: 烟测、全量实验、预期指标、验收标准
environment_setup: uv/conda/容器方案、依赖版本、硬件要求
implementation_strategy: 分阶段实现顺序、每步测试点、降配策略
```

落到 markdown 时仍按当前用户可读结构组织：

1. 推荐方案；
2. 分步执行命令；
3. 实现组件；
4. 验证方案与预期结果；
5. 可复现性分级；
6. 与原文实验的差异。

计划审阅门槛：

- 远程路径首次确认：必须停下让用户确认 `sync.yaml.remote_path`；
- 物理机环境变更：必须列影响范围和回滚方式，等待用户确认；
- 全量长实验：必须先有烟测结果，再说明预计时长和 tmux 会话名。

### 3.3 `plan-to-code`：本地代码实现

定位：

- 这是 coding agent 的工作，不是 helix CLI 的工作；
- helix skill 只给执行协议和验收清单。

执行协议：

1. 先读 `plan.md` 和 `setup.md`；
2. 先实现核心算法/模型，再实现数据和评测，最后补 README/requirements；
3. 每实现一个组件，立即跑最小测试；
4. 优先 `uv` 管依赖，其次 conda；环境只落实验隔离层；
5. 需要远程 GPU 才能测试时，用 `exp start` 同步，再用 `exp run --session ...` 跑烟测；
6. 一轮结束后记录状态：改动摘要、启动命令、tmux 会话名、远程路径、开始时间；git 开启时记录 commit。

参考代码策略：

- 官方实现、第三方复现、相关论文代码都只能作为实现参考；
- 原论文规格优先；
- 引入参考代码片段时要记录来源和许可证风险；
- 不把参考 repo 的工程结构原样搬进实验工作区，除非它就是本次明确选用的官方仓库。

### 3.4 `run-monitor-analyze`：运行、监控、结果回流

输入：

- 已实现代码；
- `plan.md` 的验证方案；
- `sync.yaml`；
- 远程资源 probe 结果。

流程：

1. `uv run helix exp start <工作区>`：同步本轮工作区；
2. `uv run helix exp run <工作区> --cmd "<smoke>" --session helix-<短名>-tmp-smoke --oneshot`；
3. 分析烟测日志和最小结果；
4. 烟测通过后启动全量：`--session helix-<短名>-run`；
5. 长实验启动后停止轮询，告诉用户会话名、预计时长、查询方式；
6. 完成后 `exp pull` 拉回 `results/{metrics,plots,tables}/`；
7. 读原始结果，填 `results/index.md`；
8. `uv run helix index build` 让结果可检索。

`results/index.md` 必须写：

- 结果概览；
- 与预期/原文对比；
- 失败或偏差原因；
- 精读时没发现的问题；
- 可进入论文写作的图表/结论；
- 本轮运行记录：命令、会话、远程路径、开始/结束时间、commit 或快照摘要。

## 4. 与现有 skills 的关系

| skill | 角色 |
|---|---|
| `helix` | 总入口，根据“复现/实验/跑远程”路由到 `reproduce` |
| `deep-read` | 复现前置，产出论文理解和全文资产 |
| `reproduce` | 主编排，承载本文 4 个子流程 |
| `experiment-plan` | 可选增强：复杂原创实验时生成实验矩阵和消融 |
| `experiment-bridge` | 可选参考：从 plan 到代码和初跑，但要服从 helix 的 `exp`/tmux/凭据规则 |
| `run-experiment` | 不作为默认路径；helix 远程执行优先用 `uv run helix exp run` |
| `monitor-experiment` / `training-check` | 可借鉴监控逻辑，后续可沉淀成 helix 规则 |
| `analyze-results` | 结果汇总和指标比较，可用于填 `results/index.md` |
| `result-to-claim` / `experiment-audit` | 复现完成后判断证据能支持什么结论 |

## 5. CLI 与数据结构影响

短期优先改 skill 和模板，CLI 保持薄：

- `helix exp new` 生成更强的 `setup.md` / `plan.md` 引导；
- `RESULTS_LAYOUT.md` 后续可加 run manifest 约定；
- `sync.yaml` 仍只做远程和传送清单，不塞复杂执行逻辑；
- `exp run/probe/start/pull/sessions/kill` 继续是确定性原子操作。

可选新增 CLI 能力：

| 命令 | 作用 | 优先级 |
|---|---|---|
| `helix exp doctor <工作区>` | 检查 sync.yaml、remote_path、results layout、远程 GPU/磁盘、环境策略风险 | P1 |
| `helix exp cleanup <工作区>` | 按命名规范清理一次性 tmux 会话 | P1 |
| `helix exp manifest <工作区>` | 记录本轮启动命令、会话、远程路径、commit/快照摘要 | P2 |
| `helix exp logs <工作区> --session <名>` | 只读拉取远程 tmux/日志尾部，不暴露凭据 | P2 |

## 6. 安全与审批

沿用 `skills/reproduce/SKILL.md` 已写入的规则：

- 依赖优先 `uv`，其次 conda，再考虑容器；
- 项目隔离环境可自主执行；
- `sudo`、系统包管理器、CUDA/driver、全局 conda/base、Docker daemon、系统服务、shell rc、`/usr`/`/opt`/`/etc`
  修改必须先让用户审核；
- 远程实验优先 tmux；
- 区分长驻、一次性、调试会话；
- 一次性会话执行完且分析完必须清理；
- 凭据只经 CLI 子进程边界注入，绝不进入模型上下文。

## 7. 分阶段落地

### P0：只改 skill 文档和骨架模板

- 强化 `skills/reproduce/SKILL.md`：加入 4 个子流程。
- 强化 `helix/repro.py` 里的 `setup.md` / `plan.md` 骨架注释。
- `plan.md` 显式要求 file_structure / implementation_components / validation_approach / environment_setup /
  implementation_strategy 五类信息。
- 不新增依赖，不改存储结构。

### P1：增加确定性检查

- 新增 `helix exp doctor`：跑前检查环境风险、remote_path、sync.yaml、results layout、GPU/磁盘。
- 新增 `helix exp cleanup`：按 `helix-<短名>-tmp-*` 清理一次性会话。
- tests 覆盖 doctor/cleanup 的命令构造和安全边界。

### P2：运行记录和结果 manifest

- 在工作区生成 `runs/<run_id>/manifest.yaml` 或 `results/runs/<run_id>.yaml`。
- 记录命令、会话、远程路径、开始/结束时间、commit/快照摘要、结果文件。
- `results/index.md` 可从 manifest 半自动填充运行记录。

### P3：参考代码索引

- 可选实现 `code-reference-index`，索引官方仓库/相关论文实现。
- 检索结果只作为 reference-only，不能覆盖原论文规格。
- 记录来源和许可证风险。

## 8. 验收标准

一次完整复现流程完成时，应满足：

- `setup.md` 能回答“原文到底怎么做”；
- `plan.md` 能回答“这台机器上具体怎么跑”；
- 代码工作区能跑烟测；
- 全量实验在远程 tmux 会话中运行，用户可自行查看；
- 一次性会话已清理，长驻会话有明确用途；
- `results/{metrics,plots,tables}/` 有原始结果；
- `results/index.md` 有结论、偏差分析、精读漏掉的问题和运行记录；
- `uv run helix index build` 后，结果能被本地检索到。

## 9. 下一步

1. 更新 `skills/reproduce/SKILL.md`，把本文 4 个子流程写入主流程。
2. 更新 `helix/repro.py` 的 `setup.md` / `plan.md` 骨架模板。
3. 补测试确认 `exp new` 生成的新骨架包含关键提示。
4. 视需要再做 `exp doctor` / `exp cleanup`。
