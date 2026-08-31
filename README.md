# Linux Kernel Patch Analyzer (`kp`)

[![Python >=3.10](https://img.shields.io/badge/python->=3.10-blue.svg)](https://www.python.org/)
[![uv](https://img.shields.io/badge/package%20manager-uv-purple.svg)](https://github.com/astral-sh/uv)
[![Test](https://img.shields.io/badge/tests-143%20passed-success.svg)](tests/)

`kp` 是一个用 Python 编写的 Linux 内核补丁邮件列表（lore.kernel.org / LKML）自动化抓取、AI 价值打分筛选、完整补丁集拉取与结构化清洗、AI 深度技术剖析与报告生成的全流程自动化工具。


系统设计遵循 **AI 直读友好** 与 **轻量分层** 原则，将庞大的邮件线程拆解为易于大模型直接阅读与分析的 Markdown 说明、Markdown 引用讨论树以及独立的原生 `.patch` 代码文件，结合项目级 Skill 辅助开发者与 AI Agent 开展高质量的 Linux 内核代码深度技术分析。

---

## 🌟 核心特性

- **完整 3 阶段流水线编排**：
  - **阶段一 (`kp fetch`)**：基于 `lei q` 抓取补丁邮件元数据，利用并查集（Union-Find）自动聚合同一补丁集的所有邮件，生成会话数据。
  - **阶段二 (`kp download`)**：接收 AI 评审打分结果（或直接指定 ID），通过 `b4 mbox` 下载高价值补丁集的完整邮件线程，还原**嵌套树形讨论结构**并自动拆解为直读友好型文件。
  - **阶段三 (`kp analyze`)**：驱动外部 AI Agent（`agy` / `opencode`）或在 AI IDE 中直接结合内置 Skill，从 **5 大核心技术维度**开展深度内核剖析，自动生成独立的 Markdown 技术分析报告。
- **项目级 Skill 与渐进式披露**：
  - 内置 `.agents/skills/kernel-patch-analyzer/` 统一项目级 Skill，无缝对接各类 AI Agent（如 Google Antigravity、OpenCode 等），通过 `references/screening.md` 和 `references/deep-analysis.md` 提供结构化领域指引。
- **AI 直读友好型存储结构**：
  - 杜绝生成几万行嵌套转义字符串的深层单 JSON 文件；
  - 自动生成 `00-cover-letter.md`、`discussions.md`（论坛式 `>` 引用排版）与 `patches/*.patch`，AI Agent 直接使用文件查看工具阅读，**零 Python 脚本提取开销**。
- **安全受控**：
  - 内置 `SafetyValidator` 强制校验查询时间跨度不得超过 48 小时（解析 `d:` 条件），保护内核邮件公共基础设施。
- **强类型与高测试覆盖**：
  - 基于 Pydantic v2 进行严格数据建模与强类型校验；
  - 150+ 单元与集成测试 100% 通过（TDD 驱动开发）。

---

## 📦 环境依赖与安装

- **操作系统**: Linux
- **Python**: `>=3.10`
- **包管理工具**: [`uv`](https://github.com/astral-sh/uv)
- **底层内核工具**:
  - `lei` (来自 `public-inbox`)
  - `b4` (已预装或通过系统包管理器安装)
  - `git`
- **外部 AI Agent (可选，用于阶段三自动分析)**:
  - `agy` (Google Antigravity CLI) 或 `opencode`

```bash
# 克隆仓库
git clone <repo_url>
cd kp

# 使用 uv 同步依赖与虚拟环境
uv sync
```

---

## 🚀 快速上手

### 1. 阶段一：抓取补丁元数据 (`kp fetch`)

```bash
# 查询最近 2 小时 linux-mm 邮件列表中的新补丁集
uv run kp fetch --query "l:linux-mm.kvack.org AND NOT s:Re AND d:2.hours.ago.."
```

执行后将输出会话 ID 与会话目录：
```text
[*] 执行查询: l:linux-mm.kvack.org AND NOT s:Re AND d:2.hours.ago..
[✓] 抓取完成！
    - 运行 ID: 20260830_141211
    - 原始邮件数: 35
    - 聚合 Patchset 数: 4
    - 会话目录: /path/to/kp/data/runs/20260830_141211

[提示] 可使用 skill 'kernel-patch-analyzer' 进行补丁初筛与打分 (输出 reviews.json)，或直接执行 kp download --run-id 20260830_141211 --id <target_id>。
```

### 2. 进行第一轮 AI 筛选打分

使用 AI 助手加载 `kernel-patch-analyzer` skill 对 `patchsets.json` 进行初筛打分，生成标准的 JSON 评审结果（保存为 `reviews.json` 或保存在会话目录下）：
```json
[
  {
    "id": "20260830120000.12345-1-author@example.com",
    "title": "[PATCH v2 0/2] mm/example: optimize memory allocation throughput",
    "score": 88,
    "recommend": true,
    "reason": "重构内存分配与回收路径，减少锁竞争并提升并发吞吐，具备较高技术价值"
  }
]
```

### 3. 阶段二：完整拉取、结构化清洗与直读拆解 (`kp download`)

```bash
# 方式 A：根据 AI 评审文件自动筛选并拉取高分 Patchset（默认 min-score 70）
uv run kp download --run-id 20260830_141211 --input reviews.json --min-score 80

# 方式 B：直接指定 Patchset Message-ID 进行拉取与拆解（支持指定多个 --id）
uv run kp download --run-id 20260830_141211 --id 20260830120000.12345-1-author@example.com

# 方式 C：通过标准输入管道传入评审 JSON
cat reviews.json | uv run kp download --run-id 20260830_141211 --input -
```

### 4. 阶段三：AI 深度技术剖析与报告生成 (`kp analyze`)

阶段三通过 `kp analyze` 自动化调度 AI Agent（agy / opencode）结合本地 Linux 内核源码树开展深度分析：

```bash
# 4.1 预检（Dry Run）：检查待分析补丁集直读文件完整性，不触发 Agent
uv run kp analyze --run-id 20260830_141211 --dry-run

# 4.2 全量深度分析：调用默认 Agent (agy) 分析该会话下所有已下载补丁集
uv run kp analyze --run-id 20260830_141211

# 4.3 指定补丁集 ID 与指定 Agent / 并发度：
uv run kp analyze --run-id 20260830_141211 \
    --id 20260830120000.12345-1-author@example.com \
    --agent agy \
    --concurrency 2

# 4.4 使用 opencode 运行分析：
uv run kp analyze --run-id 20260830_141211 --agent opencode

# 4.5 强制重新分析（默认会自动跳过已生成有效报告的补丁集）：
uv run kp analyze --run-id 20260830_141211 --force

```

执行后，各补丁集的独立分析报告将保存在 `data/runs/<run_id>/reports/<sanitized_id>.md`。

---

## 🧠 Skill 与 AI Agent 协作模式

`kp` 自带项目级 Skill：[`.agents/skills/kernel-patch-analyzer/`](.agents/skills/kernel-patch-analyzer/)，可被 Google Antigravity、OpenCode 等 AI Agent 识别与加载：

1. **初筛打分阶段 (Screening)**：
   - 当前对话 Agent 查阅 [`references/screening.md`](.agents/skills/kernel-patch-analyzer/references/screening.md)；
   - 对 `data/runs/<run_id>/patchsets.json` 各补丁集按 4 大维度（子系统重要性、改动规模、代码成熟度、维护者关注度）进行 0-100 分量化打分并生成 `reviews.json`。
2. **深度分析阶段 (Deep Technical Analysis)**：
   - 调度命令：运行 `uv run kp analyze --run-id <run_id>`；
   - 由 `kp analyze` 调度外部 Agent 子进程，查阅 [`references/deep-analysis.md`](.agents/skills/kernel-patch-analyzer/references/deep-analysis.md)；
   - 结合补丁集直读文件（`00-cover-letter.md`、`discussions.md`、`patches/*.patch`）与本地 Linux 内核源码树，从 **5 大分析维度**（背景动机与架构设计、锁与并发安全、内存与资源生命周期、潜在回归与性能/兼容性风险、社区审阅洞察与争议点）撰写深度分析报告并写入 `data/runs/<run_id>/reports/<sanitized_id>.md`。

---

## 📂 会话数据存储目录结构

每次运行的所有数据均保存在 `data/runs/<run_id>/` 目录下：

```text
data/runs/<run_id>/
├── manifest.json              # 会话基础清单元数据
├── raw_metadata.json          # [阶段一] lei 返回的原始邮件列表
├── patchsets.json             # [阶段一] 初步聚合的补丁集列表
├── reviews.json               # [阶段二] 导入的 AI 评审打分结果
├── filtered_patchsets.json    # [阶段二] 经筛选后被拉取的补丁集列表
├── patchsets/                 # [阶段二] 补丁集拆解直读目录
│   └── <sanitized_msgid>/
│       ├── 00-cover-letter.md # [直读] Cover Letter 系列说明与总体 Diffstat
│       ├── discussions.md     # [直读] 社区 Maintainer/Reviewer 审阅评论树
│       ├── patches/           # [直读] 独立拆解的标准 Git Patch 文件
│       │   ├── 0001-xxx.patch # 包含 Commit Message、Trailers 与统一 Diff
│       │   └── 0002-xxx.patch
│       ├── meta.json          # 轻量级索引元数据（不含庞大 Diff）
│       ├── parsed_series.json # 全量结构化 JSON 数据
│       └── series.mbx         # b4 下载的原始完整线程 mbox
└── reports/                   # [阶段三] 独立深度技术分析报告目录
    ├── <sanitized_msgid_1>.md # 深度技术剖析报告 (5 大维度分析)
    └── <sanitized_msgid_2>.md
```

---

## ⚙️ 配置文件 (`config.toml`)

项目支持工作区根目录的 `config.toml`（或 `kp.toml`、`~/.config/kp/config.toml`）配置：

```toml
[safety]
# 最大允许查询时间跨度（小时），默认 48 小时
max_time_span_hours = 48
# 是否强制要求 query 必须包含 d: 时间范围
require_time_filter = true

[lore]
# 默认使用的 lore public-inbox 地址
inbox_url = "https://lore.kernel.org/all/"
# lei 命令执行超时时间（秒）
timeout_seconds = 60

[b4]
# b4 命令执行超时时间（秒）
timeout_seconds = 120

[kernel]
# Linux 内核源代码路径
path = "/code/linux"

[storage]
# 数据持久化根目录
data_dir = "data/runs"

[agent]
# 默认深度分析 AI Agent ('agy' 或 'opencode')
default = "agy"
# agy 命令行可执行文件路径或名称
agy_cmd = "agy"
# opencode 命令行可执行文件路径或名称
opencode_cmd = "opencode"
# 单个 Agent 分析超时时间（秒，默认 20 分钟）
timeout_seconds = 1200
# 并发分析数
concurrency = 1
```


---

## 🧪 测试与质量保障

```bash
# 运行全量单元与集成测试
uv run pytest -v

# 运行代码规范检查与格式校验
uv run ruff check
uv run ruff format --check
```

---

## 📖 相关技术文档

- **系统全景设计文档**: [`docs/design.md`](docs/design.md)
- **Agent 协作与操作指南**: [`AGENTS.md`](AGENTS.md)
- **阶段一设计规范**: [`docs/superpowers/specs/2026-08-30-patch-analyzer-stage1-design.md`](docs/superpowers/specs/2026-08-30-patch-analyzer-stage1-design.md)
- **阶段二设计规范**: [`docs/superpowers/specs/2026-08-30-patch-analyzer-stage2-design.md`](docs/superpowers/specs/2026-08-30-patch-analyzer-stage2-design.md)
- **阶段三设计规范**: [`docs/superpowers/specs/2026-08-31-patch-analyzer-stage3-design.md`](docs/superpowers/specs/2026-08-31-patch-analyzer-stage3-design.md)

---

## 📄 License

MIT
