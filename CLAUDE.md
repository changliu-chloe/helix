# CLAUDE.md — helix 开发规约

helix：人在环中的科研全流程助手（读 → 复现 → 写）。Python CLI 干确定性活（检索/解析/索引/显存判级），`skills/` 下 SKILL.md 供外部 agent 编排 LLM 环节。详见 [README.md](README.md)。

## 一、分支与合并（main 只进稳定代码）

- **每个功能/修复都在独立的 git worktree 里做**，不管是否并行。主仓库目录（`helix/`）保持在稳定分支、不动，新工作放到平级的外部目录：

  ```bash
  git worktree add ../helix-<slug> -b <type>/<slug> main   # 从 main 拉新分支，展开到外部目录
  ```

  （如 `git worktree add ../helix-write -b feat/write-module main`）。这样主目录随时可用、并行互不踩、分支被 git 强制互斥占用。**禁止在 main 上直接开发**。
- **新 worktree 是干净工作区，不带 gitignore 的本地物**（`.venv`、`helix init` 软链的 `.claude/skills`、`.helix/index.db`／笔记库／复现工作区等本地数据都不会跟过来）。进目录先初始化：

  ```bash
  cd ../helix-<slug>
  uv sync                 # 装依赖
  uv run helix init       # 幂等软链 skills
  ```

  涉及本地数据（笔记/索引/复现区）的活，用外部固定路径或指向主库，别在临时 worktree 里生成一份又随删除丢掉——对齐第二节「不丢用户数据」。
- 分支内完成 → 补/跑测试（`uv run pytest`）→ 交付说明 → **等我确认后再 merge**。不要自作主张合回 main。
- merge 前自检：测试全绿、无残留调试代码、README/命令表与实现一致。
- 合并并 `git branch -d` 后，清掉工作目录：`git worktree remove ../helix-<slug>`（只删工作区，历史/对象都在主 `.git/`，不丢）。多个分支先后 merge 时，后合的先 `git rebase main` 或 merge 一下再合，处理公共文件冲突。

## 二、迭代必须可迁移（不丢用户数据）

用户已在用旧版本，产生了笔记、索引、复现工作区等数据。任何**环境依赖变动**（新依赖、Python 版本、config 字段）或**代码/存储架构改动**都必须：

- 提供**幂等的 CLI 迁移指令**（形如 `helix migrate`），让用户以最小成本升级；参考 `helix init` 的幂等风格。
- **只搬不丢**：允许改变存储位置（笔记库 `notes_path`、`.helix/index.db`、复现工作区），但绝不允许丢失或损坏既有笔记 / 索引 / 草稿。迁移前先备份或校验，迁移应可回滚。
- config 字段变更要向后兼容：旧 config 能被读取，缺失字段给默认值。`helix migrate` 会按模板把缺失字段（连注释、空占位）**追加**进用户 config.yaml（写前备份 `config.yaml.bak`、只追加不重写既有内容、幂等），用户填值即可——字段位置由模板控制，不靠用户随手写。新增字段务必在 config.example.yaml 里带好注释与占位值。
- 在 README「搭环境」「命令一览」同步升级说明。

## 三、第一性原理 + 软件过程管理

- **回到本质**：先问「这个功能要解决的真实问题是什么」，走最短路径，不为假想需求做过度设计。
- **低耦合、高内聚**：延续现有分层——确定性逻辑在 `helix/*.py`（`config`/`index`/`notes`/`score`/`repro`/`sync`/`ssh`/`vcs`/`secrets` 各司其职），LLM 编排在 `skills/`，两者不互相硬编码。CLI 不绑定任何 LLM provider。远程实验的判断（烟测/时长/全量）归 agent，CLI 只做原子操作。
- **凭据绝不进大模型**：SSH/sudo 等敏感凭据只存 gitignore 的 `config.secrets.yaml`，只在 `helix/ssh.py` 子进程边界经 env/stdin 注入，绝不进 argv/日志/任何返回结构。新增触及远程执行的功能必须守这条。
- **改动前先读**：动某个模块前先读它和它的测试，沿用现有约定（命名、路径锚定 `base_dir`），不引入新库或新模式除非必要。
- **代码注释与 docstring 用英文**；面向用户的字符串（CLI 提示、写进笔记/复现骨架给用户读的模板内容）保留中文——helix 是中文科研工具，产品输出不算代码注释。
- **过程可控**：每个迭代自成一分支、有测试、有文档、可回滚；小步提交，提交信息用中文简述「做了什么 + 为什么」（见现有 git log 风格）。

## 常用命令

```bash
uv run helix status          # 配置/库/索引状态
uv run pytest                # 跑测试
uv run helix init            # 幂等软链 skills 到 .claude/skills
```
