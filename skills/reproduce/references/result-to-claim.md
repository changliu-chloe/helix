# result-to-claim：从实验结果到 claim 判断

目标：用户自己的实验跑完后，判断结果到底支持什么、不支持什么，以及下一轮应该继续、收敛还是放弃。

## 输入

- `plan.md` 中的 hypothesis、baseline、指标和验收标准；
- `results/{metrics,plots,tables}/` 原始结果；
- `results/index.md` 的结果概览；
- 运行记录、失败日志、异常现象。

## 输出

- `results/index.md` 中的 claim 判断和下一轮决策；
- `PROGRESS.md` 中本阶段的完成情况和用户确认记录。

## 判断清单

- intended_claim：原计划想支持的 claim；
- supported_claim：结果实际支持的 claim，必要时收窄范围；
- unsupported_claim：结果没有支持或直接反驳的 claim；
- evidence_strength：强/中/弱，说明依据；
- confounders：可能的混杂因素、数据泄漏、实现偏差、随机种子不稳定；
- next_action：继续全量、补消融、改方法、换 baseline、停止该方向。

## 约束

- 不能把负结果包装成正结果；
- 不用单次 seed 或单个数据子集支撑过强 claim；
- 指标和统计方式必须回到 `plan.md` 的验收标准；
- 如果结果只支持缩比趋势，必须写清不能外推到完整设置。

## 阶段出口

当 `results/index.md` 已写清支持/不支持的 claim、证据强度和下一轮动作后，在 `PROGRESS.md` 写：

- 当前阶段：`D. result-to-claim`；
- 阶段状态：`建议用户确认`；
- 当前阻塞：缺结果、证据不足、baseline 不公平、统计不稳定等，没有就写「暂无」；
- 下一步：等待用户确认 D 阶段；确认后本轮实验完成，或按 next_action 开下一轮。
