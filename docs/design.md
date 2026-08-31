# Linux Kernel Patch Analyzer (kp) 系统架构与技术设计文档

本文档是 `kp` (Linux Kernel Patch Analyzer) 项目的全局系统架构与技术设计全景文档。**所有在此代码库工作的 Agent 和开发者在进行任何架构变更、功能新增或流程调整时，必须自主同步维护和更新本文档。**

---

## 1. 系统概述与设计目标

`kp` 是一个面向 Linux 内核补丁邮件列表（lore.kernel.org / LKML）的自动化抓取、AI 评审筛选、深度技术分析与报告生成的轻量级 Python 工具。

### 核心设计原则
1. **分层低耦合 (Layered & Decoupled)**：
   - 适配器层（外部工具通信）、领域核心层（清洗、聚合、解析、格式化）、编排层（业务流水线）、持久化层（会话文件管理）与 CLI 表示层严格单向依赖。
2. **轻量与低开销 (Lightweight & Low Overhead)**：
   - 采用 Python 3.10+ 原生类型与 Pydantic v2，无重型框架或数据库依赖。
   - 所有运行时数据持久化为本地结构化文件。
3. **AI 直读友好 (AI-Friendly Direct Read)**：
   - 避免将海量 Diff 和多层讨论塞进庞大的深层 JSON 中，而是通过文件系统进行自然解耦（Markdown 说明、Markdown 引用讨论树、独立 `.patch` 文件），使 AI Agent 与人类无需编写脚本即可直接阅读。
4. **安全受控 (Safety Controlled)**：
   - 严格拦截无时间限制或跨度 > 48 小时的全量抓取查询。

---

## 2. 系统全景架构

```
┌──────────────────────────────────────────────────────────┐
│                      CLI 表示层                          │
│               src/kp/cli.py (Click)                      │
│        `kp fetch`  /  `kp download`  /  `kp analyze`     │
└────────────────────────────┬─────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────┐
│                    应用流水线编排层                      │
│                src/kp/core/pipeline.py                   │
│            src/kp/core/download_pipeline.py              │
│            src/kp/core/analyze_pipeline.py               │
│    FetchPipeline  /  DownloadPipeline  / AnalyzePipeline │
└──────┬─────────────────────┬─────────────────────┬───────┘
       │                     │                     │
┌──────▼─────┐ ┌─────────────▼─────────────┐ ┌─────▼───────┐
│ 配置管理层 │ │        领域核心层         │ │外部适配器层│
│src/kp/     │ │src/kp/core/               │ │src/kp/     │
│config.py   │ │- aggregator.py (线程聚合) │ │adapters/   │
│config.toml │ │- parser.py (Mbox解析清洗) │ │- lore.py   │
│            │ │- formatters.py (直读生成) │ │- b4.py     │
│            │ └───────────────────────────┘ │- agent.py  │
│            │                               │ (agy, etc.)│
└────────────┘                               └─────┬───────┘
                                                   │
┌──────────────────────────────────────────────────▼───────┐
│                  项目级 Skill (渐进式披露)               │
│          .agents/skills/kernel-patch-analyzer/           │
│          ├── SKILL.md                                    │
│          └── references/                                 │
│              ├── screening.md                            │
│              └── deep-analysis.md                        │
└──────────────────────────────────────────────────────────┘
```

---

## 3. 分阶段业务流与数据生命周期

### 阶段一：元数据抓取、聚合与初步筛选 (Fetch & Clean)
1. **输入**：用户输入 `lei q` 查询语句（必须包含 `d:` 时间过滤）。
2. **安全校验**：`SafetyValidator` 校验查询跨度 <= 48 小时。
3. **抓取**：`LoreClient` 执行 `lei q -t -f json` 拉取原始邮件元数据。
4. **聚合**：`PatchsetAggregator` 通过并查集（Union-Find）聚合邮件线程，提取代表性 Message-ID 与补丁清单。
5. **持久化**：`SessionManager` 保存 `manifest.json`、`raw_metadata.json` 与 `patchsets.json`。
6. **AI 初筛引导**：外部 AI Agent 加载 `kernel-patch-analyzer` skill (引用 `references/screening.md`) 进行初筛并生成 `reviews.json`。

### 阶段二：AI 评审打分接入、完整拉取与直读拆解 (Download & Parse)
1. **输入**：`kp download --run-id <ID> [--input reviews.json | --id <MSG_ID>]`。
2. **过滤**：解析 AI 评审结果（自动宽容提取 Markdown 代码块），过滤高分项（`score >= min_score or recommend is True`），保存 `reviews.json` 与 `filtered_patchsets.json`。
3. **下载**：`B4Client` 调用 `b4 mbox` 拉取完整线程 `series.mbx`。
4. **解析与拆解**：
   - `MboxParser` 提取 Cover Letter、Patches (commit message, trailers, diff) 与递归回复评论树 (`ParsedComment`)。
   - `formatters` 生成直读文件：`00-cover-letter.md`、`discussions.md`、`patches/0001-xxx.patch` 及轻量索引 `meta.json`。
   - 保存全量 `parsed_series.json`。

### 阶段三：AI Agent 深度内核分析与独立报告生成 (Analyze & Report)
1. **输入**：`kp analyze --run-id <ID> [--id <MSG_ID>] [--agent agy|opencode] [--force] [--dry-run]`。
2. **前置防重、内核路径与完整性校验**：
   - 校验 Linux 内核源码树路径配置（`kernel.path`，默认 `/code/linux`），若未配置或为空则抛出错误并拦截，严禁调用 Agent；
   - 检查 `data/runs/<run_id>/reports/<sanitized_id>.md` 是否已存在且非空。若已存在且未指定 `--force`，自动跳过该补丁集以避免重复消耗算力；
   - 自动校验待分析补丁集直读文件完整性（`meta.json`、`patches/`、`00-cover-letter.md`）。
3. **Agent 驱动**：`AgentRunner`（如 `AgyAgentRunner` / `OpenCodeAgentRunner`）以携带补丁集目录与 Linux 内核代码路径的指令触发外部 Agent 加载 `kernel-patch-analyzer` skill (引用 `references/deep-analysis.md`)。
4. **5 大分析维度**：背景动机与架构设计、锁与并发安全、内存与资源生命周期、潜在回归与性能/兼容性风险、社区审阅洞察与争议点。
5. **持久化**：每个补丁集独立生成并校验 Markdown 报告，保存在 `data/runs/<run_id>/reports/<sanitized_id>.md`。

---

## 4. 存储与目录结构规范

数据持久化根目录位于 `data/runs/<run_id>/`（通过 `StorageConfig.data_dir` 配置）：

```text
data/runs/<run_id>/
├── manifest.json              # 会话清单元数据 (RunManifest)
├── raw_metadata.json          # [阶段一] lei 返回的原始邮件元数据
├── patchsets.json             # [阶段一] 聚合后的 Patchset 列表
├── reviews.json               # [阶段二] 导入的 AI 打分与推荐结果
├── filtered_patchsets.json    # [阶段二] 经筛选后待下载的 Patchset 列表
├── patchsets/                 # [阶段二] 补丁集下载与拆解目录
│   └── <sanitized_msgid>/     # 路径安全的 MsgID 目录
│       ├── 00-cover-letter.md # [直读] Cover Letter 系列说明与总体 Diffstat
│       ├── discussions.md     # [直读] 社区审阅讨论与争论树（Markdown 引用排版）
│       ├── patches/           # [直读] 独立拆解的标准 Git Patch 文件
│       │   ├── 0001-xxx.patch # 包含 Commit Message、Trailers 与统一 Diff
│       │   └── 0002-xxx.patch
│       ├── meta.json          # 轻量级索引元数据（无庞大 Diff）
│       ├── parsed_series.json # 全量结构化 JSON 数据（向下兼容）
│       └── series.mbx         # b4 下载的原始线程 mbox
└── reports/                   # [阶段三] 独立深度技术分析报告目录
    ├── <sanitized_msgid_1>.md # 各补丁集深度分析报告
    └── <sanitized_msgid_2>.md
```

---

## 5. 核心模块与接口清单

| 模块路径 | 核心类 / 函数 | 职责说明 |
|---|---|---|
| `src/kp/config.py` | `AppConfig`, `SafetyConfig`, `LoreConfig`, `B4Config`, `StorageConfig`, `AgentConfig`, `KernelConfig` | TOML 配置解析、默认值回退与环境变量管理 |
| `src/kp/models.py` | `RawMessage`, `Patchset`, `PatchReview`, `ParsedComment`, `ParsedPatch`, `ParsedCoverLetter`, `ParsedPatchset`, `PatchsetAnalysis`, `AnalyzeRunResult`, `RunManifest` | 全局强类型 Pydantic 数据模型 |
| `src/kp/adapters/lore.py` | `LoreClient`, `SafetyValidator` | `lei q` 外部调用与时间跨度（<=48h）强制安全拦截 |

| `src/kp/adapters/b4.py` | `B4Client` | `b4 mbox` 外部调用、超时控制与 MsgID 安全转义 |
| `src/kp/adapters/agent.py` | `BaseAgentRunner`, `AgyAgentRunner`, `OpenCodeAgentRunner`, `get_agent_runner` | 外部 AI Agent (agy / opencode) 子进程调用、内核代码路径参数传递与产物后置校验 |
| `src/kp/core/aggregator.py` | `PatchsetAggregator` | 邮件主题正则解析、并查集线程聚合与代表 ID 提取 |
| `src/kp/core/parser.py` | `MboxParser` | Mbox 邮件解析、Git Trailers 提取、评论树环路检测与树形还原 |
| `src/kp/core/formatters.py` | `render_cover_letter_md`, `render_discussions_md`, `render_patch_file`, `render_meta_json` | AI 直读友好型 Markdown 与 Patch 文件生成 |
| `src/kp/core/pipeline.py` | `FetchPipeline` | 阶段一业务流水线编排 |
| `src/kp/core/download_pipeline.py`| `DownloadPipeline` | 阶段二业务流水线编排 |
| `src/kp/core/analyze_pipeline.py` | `AnalyzePipeline` | 阶段三业务流水线编排 (支持内核代码路径强制前置校验、已分析防重跳过与并发调度) |
| `src/kp/storage/session.py` | `SessionManager` | 会话目录管理与各类数据/Markdown/Patch/Report 文件持久化 |
| `src/kp/cli.py` | `main`, `fetch_cmd`, `download_cmd`, `analyze_cmd` | Click CLI 用户命令行接口 |
| `.agents/skills/kernel-patch-analyzer/` | `SKILL.md`, `references/` | 统一项目级 Skill (渐进式披露引导全流程) |


---

## 6. 开发、测试与维护准则

1. **测试驱动开发 (TDD)**：新增任何功能或修改已有逻辑，必须先编写失败的单元测试，再编写实现代码，确保 `uv run pytest` 100% 通过。
2. **测试环境隔离与无污染**：
   - 单元测试严禁向项目根目录下的 `data/runs` 写入任何数据；
   - 统一通过 `tests/conftest.py` 将测试会话重定向至 `/tmp/kp_pytest_runs/`；
   - 在每轮测试开始前，测试套件必须自动清理 `/tmp` 中的旧测试产物。
3. **文档自主维护要求**：
   - 任何涉及接口签名、数据模型、存储目录结构、业务流程的修改，必须在完成代码修改与测试后，**立即自主更新本文档（`docs/design.md`）**。
   - 严禁出现代码与设计文档脱节的情况。


