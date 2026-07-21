# hypothesis-to-plan：从实验假设到 plan.md

目标：把用户自己的实验想法转成可执行计划。这里没有原文 `setup.md`，不要套论文复现的“原文事实抽取”逻辑。

## 输入

- 用户的研究问题、方法想法或要验证的 claim；
- 可选对标论文/已有笔记；
- 可用硬件档和远程资源；
- 已知 baseline、数据集、指标或约束。

## 输出

- 填好的 `plan.md`；
- `PROGRESS.md` 中本阶段的进展、阻塞和建议确认状态。

## plan.md 必须覆盖

- hypothesis：要验证的研究假设或 claim；
- baseline：最小可信 baseline 和可选强 baseline；
- variables：自变量、因变量、控制变量；
- experiment_matrix：主实验、消融、缩比试验、失败判据；
- metrics：指标定义、统计方式、显著性/稳定性要求；
- file_structure：代码、配置、脚本结构；
- implementation_components：模型、数据、训练/推理、评测模块如何落到文件；
- validation_approach：烟测、全量实验、预期指标、验收标准；
- environment_setup：uv/conda/容器方案、依赖版本、硬件要求；
- implementation_strategy：分阶段实现顺序、每步测试点、降配策略。

## 约束

- 不把“我希望成立”写成“结果会成立”；预期必须可证伪；
- baseline 必须能回答“相比什么有改进”；
- 主实验和消融要服务于 claim，不为凑矩阵而扩大范围；
- 长实验必须先设计烟测和失败退出条件。

## 阶段出口

当 `plan.md` 已明确 hypothesis、baseline、变量、实验矩阵、指标和实现策略后，在 `PROGRESS.md` 写：

- 当前阶段：`A. hypothesis-to-plan`；
- 阶段状态：`建议用户确认`；
- 当前阻塞：缺 baseline、缺数据、指标不清、资源不足等，没有就写「暂无」；
- 下一步：等待用户确认 A 阶段，或进入 `plan-to-code`。
