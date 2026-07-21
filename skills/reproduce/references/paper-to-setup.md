# paper-to-setup：从论文事实到 setup.md

目标：把论文和深读笔记里的实验事实抽取到 `setup.md`。本阶段只记录原文怎么做，不写本机怎么跑。

## 输入

- 深读笔记；
- `assets/<paper_id>/fulltext.md`；
- 论文 PDF/图表资产；
- 可选官方仓库链接、第三方复现链接。

## 输出

- 填好的 `setup.md`；
- `PROGRESS.md` 中本阶段的进展、阻塞和建议确认状态。

## 抽取清单

- paper structure map：论文主张、方法章节、实验章节、关键表图；
- method decomposition：核心模块、模块交互、数据流；
- algorithms：伪代码、公式、损失函数、优化过程；
- training procedure：batch、epoch/steps、optimizer、lr、scheduler、precision；
- datasets：下载、预处理、划分、子集；
- baselines：是否需要复现、是否可引用官方/第三方实现；
- metrics：定义、计算方式、对齐原文哪张表；
- hardware/software：GPU、CUDA、框架、依赖版本。

## 约束

- `setup.md` 只写原文事实，不写本机方案；
- 论文没有明说的内容必须标注「论文未给出 / 推断 / 需要用户确认」和置信度；
- 不为了完整性编造超参；
- 官方实现、第三方复现只能帮助定位事实，原论文规格优先。

## 阶段出口

当 `setup.md` 已覆盖上述清单后，在 `PROGRESS.md` 写：

- 当前阶段：`A. paper-to-setup`；
- 阶段状态：`建议用户确认`；
- 当前阻塞：没有就写「暂无」；
- 下一步：等待用户确认 A 阶段，或进入 `setup-to-plan`。
