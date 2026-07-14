---
name: helix
description: 论文科研总入口。当用户想找论文、读论文、追踪某领域最新进展、查自己的笔记库、开启研究日，或提到某篇论文（arXiv id/标题/链接）时使用。根据意图路由到 search / deep-read / daily 子流程。
---

# helix 论文科研总入口

helix 是"论文检索追踪 + 深读理解"的 CLI + skill 套件。本 skill 负责**判断用户意图并路由**到对应子流程。

> **运行约定**：所有 helix 命令用 `uv run helix ...` 在项目根执行（helix 装在项目 venv 里、不在全局 PATH；`uv run` 会自动定位项目 venv，从子目录也可用）。若 `uv` 不可用，回退 `python -m helix.cli ...`。

## 意图路由

先判断用户想干什么，再走对应流程：

| 用户意图 / 关键信号 | 路由到 | 典型说法 |
|---|---|---|
| 提到具体某篇论文（给了 arXiv id / 标题 / 链接），想读透 | **deep-read** | "读这篇论文 2503.22020"、"精读 CoT-VLA"、"总结一下这篇" |
| 找论文 / 追踪某方向最新进展 / 查本地笔记库 | **search** | "找些 VLA 最新论文"、"我之前读过的关于扩散模型的"、"高引用的经典论文" |
| 批量看今日推荐 / 开启研究日 | **daily** | "开启研究日"、"今天有什么新论文"、"start my day" |
| 想在自己机器上复现某篇论文的实验 | **reproduce** | "复现这篇论文"、"这篇能在我的 A100 上跑吗"、"总结实验设置给个复现方案" |

路由后按对应 skill 的流程执行。四个子 skill 分别在 `search / deep-read / daily / reproduce`。
（复现依赖论文已读过；库里没笔记时 reproduce 会先要你走 deep-read。）

## 快速命令速查

```bash
uv run helix status                          # 看配置、研究领域、库状态
uv run helix search "<query>" --top-n 10     # 跨源检索 + 打分（--source arxiv,s2,dblp）
uv run helix note new <arxiv_id>             # 抓论文建深读笔记骨架
uv run helix note link <笔记路径>            # 正文论文名自动 wikilink
uv run helix index build                     # 重建本地 FTS 索引
uv run helix index search "<query>"          # 本地笔记全文检索
```

## 常见组合场景

- **"读这篇论文：<id>"** → deep-read：`note new <id>` 建骨架 → 读全文填充 → `note link` + `index build`
- **"找 X 方向的论文并挑几篇深读"** → search 检索打分 → 取 top 几篇走 deep-read
- **"开启研究日"** → daily：批量检索 → 写推荐笔记 → top 3 深读

## 原则

- 意图不明确时，先问一句用户是想「找新论文」还是「读已知的某篇」，再路由
- 深度理解/总结由你（agent）完成，helix 只做检索/抓取/建骨架/索引这类确定性工作
- 忠实原文，不臆造引用数或结果
