# hypothesis-to-plan：从实验假设到方向 plan.md 与子实验

目标：把用户自己的实验想法转成方向级 `plan.md`，并为当前具体问题创建隔离的
`sub_experiments/<slug>/`。这里没有顶层原文 `setup.md`，不要套论文复现的“原文事实抽取”逻辑。

## 输入

- 用户的研究问题、方法想法或要验证的 claim；
- 可选对标论文/已有笔记；
- 可用硬件档和远程资源；
- 已知 baseline、数据集、指标或约束。

## 输出

- 填好的方向级 `plan.md`；
- 至少一个按用户当前需求创建的 `sub_experiments/<slug>/`，含 `setup.md`、`config.yaml`、`results/index.md`；
- `PROGRESS.md` 中本阶段的进展、阻塞和建议确认状态。

## plan.md 必须覆盖

- hypothesis：方向级研究假设或 claim；
- 总体方法边界：跨子实验不变的约束、候选 baseline、总体验收口径；
- 可用能力：可调用的 helix CLI、skill、LLM 生成方式和非敏感运行上下文；
- 子实验索引：每个 `sub_experiments/<slug>/` 的用户需求、状态、关键结果和下一步；
- result-to-claim 汇总口径：如何从多个子实验合成 supported/unsupported claim。

## 子实验 setup.md/config.yaml 必须覆盖

- baseline：本轮最小可信 baseline 和可选强 baseline；
- variables：本轮自变量、因变量、控制变量；
- experiment_matrix：本轮主实验、消融、缩比试验、失败判据；
- metrics：本轮指标定义、统计方式、显著性/稳定性要求；
- file_structure：本轮代码、配置、脚本结构；
- implementation_components：本轮模型、数据、训练/推理、评测模块如何落到文件；
- validation_approach：本轮烟测、全量实验、预期指标、验收标准；
- environment_setup：本轮 uv/conda/容器方案、依赖版本、硬件要求；
- implementation_strategy：本轮分阶段实现顺序、每步测试点、降配策略。

## 约束

- 不把“我希望成立”写成“结果会成立”；预期必须可证伪；
- baseline 必须能回答“相比什么有改进”；
- 主实验和消融要服务于 claim，不为凑矩阵而扩大范围；
- 长实验必须先设计烟测和失败退出条件；
- 新需求来时新建子实验目录，不把旧轮次文件事后搬进 archive。

## 阶段出口

当顶层 `plan.md` 已明确方向级假设，且当前具体问题已有子实验 setup/config 后，在 `PROGRESS.md` 写：

- 当前阶段：`A. hypothesis-to-plan`；
- 阶段状态：`建议用户确认`；
- 当前阻塞：缺 baseline、缺数据、指标不清、资源不足等，没有就写「暂无」；
- 下一步：等待用户确认 A 阶段，或进入 `plan-to-code`。
