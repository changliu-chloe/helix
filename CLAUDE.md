# CLAUDE.md — helix 开发规约

helix：人在环中的科研全流程助手（读 → 复现 → 写）。Python CLI 干确定性活（检索/解析/索引/显存判级），`skills/` 下 SKILL.md 供外部 agent 编排 LLM 环节。详见 [README.md](README.md)。

## 一、分支与合并（main 只进稳定代码）

- 任何功能、修复都先 `git checkout -b <type>/<slug>`（如 `feat/write-module`、`fix/index-scan`），**禁止在 main 上直接开发**。
- 分支内完成 → 补/跑测试（`uv run pytest`）→ 交付说明 → **等我确认后再 merge**。不要自作主张合回 main。
- merge 前自检：测试全绿、无残留调试代码、README/命令表与实现一致。

## 二、迭代必须可迁移（不丢用户数据）

用户已在用旧版本，产生了笔记、索引、复现工作区等数据。任何**环境依赖变动**（新依赖、Python 版本、config 字段）或**代码/存储架构改动**都必须：

- 提供**幂等的 CLI 迁移指令**（形如 `helix migrate`），让用户以最小成本升级；参考 `helix init` 的幂等风格。
- **只搬不丢**：允许改变存储位置（笔记库 `notes_path`、`.helix/index.db`、复现工作区），但绝不允许丢失或损坏既有笔记 / 索引 / 草稿。迁移前先备份或校验，迁移应可回滚。
- config 字段变更要向后兼容：旧 config 能被读取，缺失字段给默认值，并提示用户新增项。
- 在 README「搭环境」「命令一览」同步升级说明。

## 三、第一性原理 + 软件过程管理

- **回到本质**：先问「这个功能要解决的真实问题是什么」，走最短路径，不为假想需求做过度设计。
- **低耦合、高内聚**：延续现有分层——确定性逻辑在 `helix/*.py`（`config`/`index`/`notes`/`score`/`repro` 各司其职），LLM 编排在 `skills/`，两者不互相硬编码。CLI 不绑定任何 LLM provider。
- **改动前先读**：动某个模块前先读它和它的测试，沿用现有约定（命名、路径锚定 `base_dir`），不引入新库或新模式除非必要。
- **代码注释与 docstring 用英文**；面向用户的字符串（CLI 提示、写进笔记/复现骨架给用户读的模板内容）保留中文——helix 是中文科研工具，产品输出不算代码注释。
- **过程可控**：每个迭代自成一分支、有测试、有文档、可回滚；小步提交，提交信息用中文简述「做了什么 + 为什么」（见现有 git log 风格）。

## 常用命令

```bash
uv run helix status          # 配置/库/索引状态
uv run pytest                # 跑测试
uv run helix init            # 幂等软链 skills 到 .claude/skills
```
