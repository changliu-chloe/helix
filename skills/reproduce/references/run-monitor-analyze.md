# run-monitor-analyze：运行、监控、结果回流

目标：在本地或远程运行实验，监控关键状态，拉回结果并沉淀到结果笔记。
`type:mine` 先写对应 `sub_experiments/<slug>/results/index.md`，再更新顶层 `results/index.md` 汇总。

## 输入

- 已实现代码；
- `plan.md` 的方向级验证口径；
- `type:mine` 当前子实验的 `sub_experiments/<slug>/setup.md` 和 `config.yaml`；
- `sync.yaml`；
- 远程资源 probe 结果；
- 烟测日志和全量运行日志。

## 输出

- `type:repro`：`results/{metrics,plots,tables}/` 原始结果；
- `type:mine`：`sub_experiments/<slug>/results/{metrics,plots,tables}/` 原始结果；
- 填好的结果笔记（repro 顶层 `results/index.md`；mine 子实验结果 + 顶层汇总）；
- `PROGRESS.md` 中本阶段的完成情况和用户确认记录。

## 流程

1. `uv run helix exp start <工作区>`：同步本轮工作区；
2. `uv run helix exp run <工作区> --cmd "<smoke>" --session helix-<短名>-tmp-smoke --oneshot`；
3. 分析烟测日志和最小结果；
4. 烟测通过后启动全量：`--session helix-<短名>-run`；
5. 长实验启动后停止轮询，告诉用户会话名、预计时长、查询方式；
6. 完成后 `exp pull` 拉回 results；mine 会按本地已有 `sub_experiments/<slug>/` 拉各自结果；
7. 读原始结果，repro 填顶层 `results/index.md`；mine 先填子实验 `results/index.md`，再更新顶层汇总；
8. `uv run helix exp clean <工作区或子实验目录>` 预览烟测/临时产物；用户确认后加 `--yes` 删除；
9. `uv run helix index build` 让结果可检索。

## results/index.md 必须写

- 结果概览；
- 与预期/原文或 baseline 对比；
- 失败或偏差原因；
- 问题记录：`type:repro` 写精读时没发现的问题；`type:mine` 子实验写本轮暴露的问题，顶层只汇总跨子实验问题；
- 清理记录：列出保留的正式结果，以及 `exp clean` 删除了哪些烟测/临时产物；
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
