# run-monitor-analyze：运行、监控、结果回流

目标：在本地或远程运行实验，监控关键状态，拉回结果并沉淀到 `results/index.md`。

## 输入

- 已实现代码；
- `plan.md` 的验证方案；
- `sync.yaml`；
- 远程资源 probe 结果；
- 烟测日志和全量运行日志。

## 输出

- `results/{metrics,plots,tables}/` 原始结果；
- 填好的 `results/index.md`；
- `PROGRESS.md` 中本阶段的完成情况和用户确认记录。

## 流程

1. `uv run helix exp start <工作区>`：同步本轮工作区；
2. `uv run helix exp run <工作区> --cmd "<smoke>" --session helix-<短名>-tmp-smoke --oneshot`；
3. 分析烟测日志和最小结果；
4. 烟测通过后启动全量：`--session helix-<短名>-run`；
5. 长实验启动后停止轮询，告诉用户会话名、预计时长、查询方式；
6. 完成后 `exp pull` 拉回 `results/{metrics,plots,tables}/`；
7. 读原始结果，填 `results/index.md`；
8. `uv run helix index build` 让结果可检索。

## results/index.md 必须写

- 结果概览；
- 与预期/原文或 baseline 对比；
- 失败或偏差原因；
- 问题记录：`type:repro` 写精读时没发现的问题；`type:mine` 写实验过程中暴露的问题、混杂因素和 baseline 风险；
- 可进入论文写作的图表/结论；
- 本轮运行记录：命令、会话、远程路径、开始/结束时间、commit 或快照摘要。

## 长实验规则

- 跑前先 `exp probe` 看磁盘够不够、GPU 空不空；
- 先小规模烟测，通过再上全量；
- 长实验启动后不持续轮询；告诉用户机器、tmux 会话名、预计时长、查询/回拉命令。

## 阶段出口

当结果已回拉、`results/index.md` 已整理、索引已重建后，在 `PROGRESS.md` 写：

- 当前阶段：`D. run-monitor-analyze`；
- 阶段状态：`建议用户确认`；
- 当前阻塞：失败运行、结果缺失、指标不达标等，没有就写「暂无」；
- 下一步：等待用户确认 D 阶段；确认后本轮复现完成。
