---
name: kernel-patch-analyzer
description: "Linux 内核补丁初筛打分、下载解包与 AI 深度技术分析全流程指南。指导 AI Agent 根据用户自然语言意图灵活调用 kp CLI 工具，支持从任意阶段（抓取/打分/下载/深度分析）自由切入执行。"
---

# Linux 内核补丁分析器指南 (Kernel Patch Analyzer Guide)

本 Skill 旨在指导 AI Agent 如何运用 `kp` 工具链对 Linux 内核邮件列表（LKML / lore.kernel.org）上的补丁集开展全流程或分阶段自动化分析。

---

## 🧭 1. 阶段判定与多入口路由 (Workflow Router)

用户发起请求时可能处于补丁分析的**任意阶段**。Agent 应首先识别当前上下文所处的阶段，按需切入执行：

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 用户意图 / 输入状态                                对应切入点与执行路径         │
├─────────────────────────────────────────────────────────────────────────────────┤
│ 1. 自然语言描述需求 (如 "分析过去2小时内存管理补丁")  ──► 路径 A: 端到端全流程    │
│ 2. 增量例行巡检 (如 "增量检查今天的新补丁")          ──► 路径 A+: 增量巡检抓取   │
│ 3. 已有 run-id / 刚完成 fetch (如 "帮这个 run 打分") ──► 路径 B: 初筛打分与下载   │
│ 4. 已有 reviews.json (如 "下载推荐的补丁集")         ──► 路径 C: 补丁下载与拆解   │
│ 5. 已完成 download (如 "深度分析已下载的补丁")       ──► 路径 D: 深度分析与落盘   │
│ 6. 指定单个补丁集 ID / 链接                          ──► 路径 E: 靶向单补丁分析   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 路径 A：端到端全流程 (End-to-End)
1. **理解意图**：将用户的自然语言需求转换为合法的 `lei q` 查询语句；
2. **抓取**：运行 `uv run kp fetch -q "<query>"`，获取 `run_id`；
3. **初筛打分**：读取 `data/runs/<run_id>/patchsets.json`，根据 [初筛指南](references/screening.md) 评估打分 (0-10 分制)，将结果写入 `data/runs/<run_id>/reviews.json`；
4. **下载拆解**：运行 `uv run kp download -i data/runs/<run_id>/reviews.json`；
5. **深度分析**：直接运行 `uv run kp analyze -i data/runs/<run_id>/reviews.json [--concurrency 3]`（注意：并发度最高不超过 3）。无需进行任何手动文件预检或探测，`kp analyze` 会自动完成所有前置校验，最终将报告保存至全局报告库 `data/reports/YYYY-MM/<clean_id>.md`。

### 路径 A+：增量例行巡检 (Incremental Inspection)
- 运行 `uv run kp fetch -q "<query>" --since-last`。
- 系统自动基于上次同步游标抓取增量补丁，支持对大跨度进行自动分批抓取 (Auto-chunking) 与游标推进。

### 路径 B：从初筛打分起步 (From Screening)
- **前置条件**：用户提供了已存在的 `run_id`，或目录下已有 `data/runs/<run_id>/patchsets.json`。
- **执行动作**：
  1. 读取 `data/runs/<run_id>/patchsets.json` (或 `manifest.json`)；
  2. 遵循 [初筛指南](references/screening.md) 完成打分与推荐判定 (0-10 整数制)；
  3. 将 JSON 格式结果写入 `data/runs/<run_id>/reviews.json`；
  4. 提示用户或继续运行 `uv run kp download -i data/runs/<run_id>/reviews.json`。

### 路径 C：从补丁下载与拆解起步 (From Download)
- **前置条件**：已生成 `reviews.json`，或用户明确指定要下载的 Patchset ID（如 `--id <msgid>`）。
- **执行动作**：
  - 基于评审结果下载：`uv run kp download -i data/runs/<run_id>/reviews.json`
  - 或指定特定 ID 下载：`uv run kp download --id "<msgid>"`
  - 若已是最新，`kp` 会自动跳过重复下载；如需强制覆盖，可添加 `--force`。
  - `kp` 会自动将邮件线程拆解为全局直读友好文件（Cover Letter、Discussions Markdown 树、独立 `.patch` 文件与 `meta.json`）。

### 阶段 D：从深度技术分析起步 (From Deep Analysis)
- **触发条件**：用户明确要求分析已下载单个补丁集或者基于评审结果批量分析。
- **执行动作**：
  - **直接执行命令**：运行 `uv run kp analyze -i data/runs/<run_id>/reviews.json [--concurrency 3]`（基于评审分析）或 `uv run kp analyze --id "<msgid>"`（指定分析单个补丁集）；
  - 📝 **自定义关注提示词**：可通过 `-p / --prompt "重点关注..."` 或 `--prompt-file <path>` 追加针对特定业务逻辑或锁安全的重点分析要求；
  - 🔒 **并发度上限限制**：使用 `--concurrency` 时，**并发度严禁超过 3**（即 `--concurrency <= 3`，推荐设置为 2 或 3），避免启动过多外部 Agent 子进程造成系统负载过重或触发 API 配额限制；
  - ⚡ **零前置检查原则**：Agent **切勿**在执行前检查会话目录等是否存在，也**无需**预先运行 `--dry-run`。`kp analyze` 工具本身在执行时会自动进行所有的前置检查，遇错会输出清晰提示；
  - ⚠️ **严禁手动分析**：当前对话中的 Agent 严禁自行直接读取直读文件撰写报告，必须统一直接调用 `uv run kp analyze` 命令行调度子进程完成。

### 路径 E：靶向单个补丁集分析 (Single Patchset Target)
- **执行动作**：
  - 若用户提供了指定 Message-ID，直接组合执行：
    ```bash
    uv run kp download --id "<msgid>"
    uv run kp analyze --id "<msgid>"
    ```

---

## 🛠️ 2. `kp` CLI 命令速查与自然语言查询映射

### 2.1 自然语言转 `lei q` 查询规则 (`kp fetch`)

`kp fetch` 底层调用 `lei q`。构建查询语句时必须遵循以下规则与最佳实践：

1. **强制安全时间跨度限制**：查询条件中**必须**包含 `dt:` 时间过滤（除非启用 `--since-last`，此时系统会自动注入时间区间）。使用日期时间时，应确保有 `AND` 连接 `dt:` 语句。
   - 相对时间：`dt:2.hours.ago..`、`dt:24.hours.ago..`、`dt:48.hours.ago..`、`dt:1.day.ago..`
   - 绝对时间：`dt:2026-08-31T08:00:00Z..2026-08-31T10:00:00Z`
2. **过滤回复邮件**：建议始终加上 `NOT s:Re`，避免拉取重复的单封回复邮件。
3. **子系统过滤两大核心范式 (List vs. Diff Path)**：
   - **范式 A：独立邮件列表 (`l:`)** —— 适用于有**独立专用邮件列表**的子系统：
     - 内存管理 (MM)：`l:linux-mm.kvack.org`
     - 网络子系统 (Netdev)：`l:netdev@vger.kernel.org`
     - BPF / eBPF：`l:bpf@vger.kernel.org`
     - 文件系统 (VFS/FS)：`l:linux-fsdevel@vger.kernel.org`
     - 块设备与 IO：`l:linux-block@vger.kernel.org` 或 `l:io-uring@vger.kernel.org`
     - 架构特定：`l:linux-arm-kernel@lists.infradead.org`、`l:linux-riscv@lists.infradead.org`
     - 虚拟化：`l:kvm@vger.kernel.org`
   - **范式 B：Diff 变更路径 (`dfn:`)** —— 适用于**寄宿在 LKML 无独立列表的核心子系统**（调度器、锁、RCU 等）或针对具体源码目录/头文件的精准捕获：
     - **调度子系统 (Scheduler)**：`dfn:kernel/sched` 或 `(dfn:kernel/sched OR dfn:include/linux/sched)`
     - **核心锁与同步机制 (Locking)**：`dfn:kernel/locking` 或 `(dfn:kernel/locking OR dfn:include/linux/lockdep)`
     - **RCU 子系统**：`dfn:kernel/rcu` 或 `(dfn:kernel/rcu OR dfn:include/linux/rcu)`
     - *为什么核心子系统必须用 `dfn:` 而非 `s:`？*
       - `s:sched` 或 `s:lock` 存在严重噪音（误伤 `net/sched` 流量控制、`drm/sched`、`clock`、外设驱动私有锁），且会遗漏标题未带关键词的核心修改（如跨子系统的 cgroup/rseq/topology 补丁）；
       - `dfn:` 精准命中内核源码变更路径。结合 `kp` 默认的 `lei q -t`（线程级展开）与并查集聚合，只要系列中有任意补丁命中目标路径，即可完整拉取包括 Cover Letter 与社区审阅在内的整套补丁集。

#### 自然语言映射示例表
| 用户自然语言意图 | 推荐的 `kp fetch` 命令 |
|---|---|
| “增量巡检内存管理子系统的新补丁” | `uv run kp fetch -q "l:linux-mm.kvack.org AND NOT s:Re" --since-last` |
| “分析过去两小时内存管理子系统的改动” | `uv run kp fetch -q "l:linux-mm.kvack.org AND NOT s:Re AND dt:2.hours.ago.."` |
| “查看最近1小时网络子系统 netdev 补丁” | `uv run kp fetch -q "l:netdev@vger.kernel.org AND NOT s:Re AND dt:1.hours.ago.."` |
| “检索过去2小时内调度子系统 (Scheduler) 的补丁” | `uv run kp fetch -q "(dfn:kernel/sched OR dfn:include/linux/sched) AND NOT s:Re AND dt:2.hours.ago.."` |
| “抓取过去2小时内核锁与同步机制 (Locking) 补丁” | `uv run kp fetch -q "(dfn:kernel/locking OR dfn:include/linux/lockdep) AND NOT s:Re AND dt:2.hours.ago.."` |
| “查看过去2小时 RCU 子系统的补丁集” | `uv run kp fetch -q "(dfn:kernel/rcu OR dfn:include/linux/rcu) AND NOT s:Re AND dt:2.hours.ago.."` |
| “抓取过去90分钟 BPF 的补丁集” | `uv run kp fetch -q "l:bpf@vger.kernel.org AND NOT s:Re AND dt:90.minutes.ago.."` |
| “分析过去2小时文件系统 (VFS/FS) 补丁” | `uv run kp fetch -q "l:linux-fsdevel@vger.kernel.org AND NOT s:Re AND dt:2.hours.ago.."` |

---

### 2.2 CLI 常用命令汇总

```bash
# 1. 抓取元数据 (支持普通抓取或增量巡检)
uv run kp fetch -q "<lei_query>"
uv run kp fetch -q "<lei_query>" --since-last

# 2. 下载补丁集 (支持基于 reviews.json 或指定 ID，支持 --force 强制更新)
uv run kp download -i data/runs/<run_id>/reviews.json
uv run kp download --id "<msgid_1>" --id "<msgid_2>"
uv run kp download -i data/runs/<run_id>/reviews.json --min-score 8
uv run kp download --id "<msgid>" --force

# 3. 执行阶段三深度分析 (支持基于 reviews.json 或指定 ID，支持自定义提示词与强制覆盖)
uv run kp analyze -i data/runs/<run_id>/reviews.json                  # 基于评审结果筛选分析
uv run kp analyze --id "<msgid>"                                      # 仅分析指定补丁集
uv run kp analyze -i reviews.json -p "重点关注锁竞争与 RCU 同步"      # 追加自定义分析指令
uv run kp analyze -i reviews.json --prompt-file custom_prompt.txt     # 从文件读取自定义分析指令
uv run kp analyze --id "<msgid>" --agent opencode                     # 指定使用的外部 Agent
uv run kp analyze -i reviews.json --concurrency 3                     # 设置并发数 (严禁超过 3)
uv run kp analyze --id "<msgid>" --force                              # 强制重新分析已出报告的补丁集
uv run kp analyze --id "<msgid>" --dry-run                            # 仅预检补丁集直读文件完整性
```

---

## 📁 3. 全局存储与会话目录规范

数据按全局资产库与会话日志组织存储在 `data/` 下：

```text
data/
├── kp.db                      # [核心索引] SQLite 数据库 (WAL 模式，存储游标/运行记录/补丁集状态)
├── patchsets/                 # [全局补丁集资产库]
│   └── YYYY-MM/               # 按年月分桶
│       └── <clean_id>/        # 转义后的安全 Message-ID 目录
│           ├── 00-cover-letter.md # 系列背景、动机与整体 Diffstat
│           ├── discussions.md     # 社区 Review 讨论树 (Markdown 引用排版)
│           ├── patches/           # 独立拆解的标准 Git Patch 文件
│           │   ├── 0001-xxx.patch # 包含 Commit Message、Trailers 与统一 Diff
│           │   └── 0002-xxx.patch
│           ├── meta.json          # 轻量级索引元数据
│           ├── parsed_series.json # 结构化数据
│           └── series.mbx         # 原始邮件线程 Mbox
├── reports/                   # [全局报告库] 各补丁集独立深度技术分析报告
│   └── YYYY-MM/
│       ├── <clean_id_1>.md
│       └── <clean_id_2>.md
└── runs/                      # [会话执行日志]
    └── <run_id>/
        ├── manifest.json      # 会话清单与元数据
        ├── raw_metadata.json  # lei 返回的原始邮件列表
        ├── patchsets.json     # 聚合后的补丁集列表
        └── reviews.json       # AI 打分与推荐列表 (0-10分制)
```

---

## 📖 4. 渐进式披露参考文档 (Progressive Disclosure)

根据当前所处阶段，查阅对应的细分准则文档：

- **阶段一初筛打分与 `reviews.json` 生成规范**：请查阅 [初筛指南 (references/screening.md)](references/screening.md)
  - 涵盖核心子系统权重、变更性质、RFC 价值评估标准与 0-10 分制 JSON Schema（由当前对话中的 Agent 在初筛阶段直接执行并生成 `reviews.json`）。
- **阶段三深度技术分析 5 大核心维度与报告模板**：请查阅 [深度分析指南 (references/deep-analysis.md)](references/deep-analysis.md)
  - 涵盖：① 背景动机与架构设计、② 锁与并发安全、③ 内存与资源生命周期、④ 潜在回归与性能/兼容性风险、⑤ 社区审阅洞察与争议点，以及标准 Markdown 报告模板（作为 `kp analyze` 外部 Agent 分析子进程遵循的规范与 Prompt 指引）。
