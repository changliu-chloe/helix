# setup-to-plan：从原文设置到本机可执行 plan.md

目标：把 `setup.md` 的原文事实转成可执行复现计划。`plan.md` 讲本机/远程怎么跑，不重抄原文清单。

## 输入

- `setup.md`；
- 本地 `config.yaml` 的硬件档；
- `uv run helix exp vram ...` 显存判级；
- 必要时的 `uv run helix exp probe <工作区>` 资源状态。

## 输出

- 填好的 `plan.md`；
- `PROGRESS.md` 中本阶段的进展、阻塞和建议确认状态。

## plan.md 必须覆盖五类信息

```yaml
file_structure: 本实验需要的代码/配置/脚本结构
implementation_components: 核心算法、模型、数据、评测模块如何落到文件
validation_approach: 烟测、全量实验、预期指标、验收标准
environment_setup: uv/conda/容器方案、依赖版本、硬件要求
implementation_strategy: 分阶段实现顺序、每步测试点、降配策略
```

落到 markdown 时仍按用户可读结构组织：

1. 推荐方案；
2. 分步执行命令；
3. 实现组件与文件结构；
4. 验证方案与预期结果；
5. 可复现性分级；
6. 与原文实验的差异。

## 审阅门槛

- 远程路径首次确认：必须停下让用户确认 `sync.yaml.remote_path`；
- 物理机环境变更：必须列影响范围和回滚方式，等待用户确认；
- 全量长实验：必须先有烟测结果，再说明预计时长和 tmux 会话名。

## 阶段出口

当 `plan.md` 已覆盖五类信息并给出可复制命令后，在 `PROGRESS.md` 写：

- 当前阶段：`B. setup-to-plan`；
- 阶段状态：`建议用户确认`；
- 当前阻塞：远程路径/环境变更/缺失资源等，没有就写「暂无」；
- 下一步：等待用户确认 B 阶段，或进入 `plan-to-code`。
