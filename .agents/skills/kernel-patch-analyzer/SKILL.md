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
│ 2. 已有 run-id / 刚完成 fetch (如 "帮这个 run 打分") ──► 路径 B: 初筛打分与下载   │
│ 3. 已有 reviews.json (如 "下载推荐的补丁集")         ──► 路径 C: 补丁下载与拆解   │
│ 4. 已完成 download (如 "深度分析已下载的补丁")       ──► 路径 D: 深度分析与落盘   │
│ 5. 指定单个补丁集 ID / 链接                          ──► 路径 E: 靶向单补丁分析   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 路径 A：端到端全流程 (End-to-End)
1. **理解意图**：将用户的自然语言需求转换为合法的 `lei q` 查询语句；
2. **抓取**：运行 `uv run kp fetch -q "<query>"`，获取 `run_id`；
3. **初筛打分**：读取 `data/runs/<run_id>/patchsets.json`，根据 [初筛指南](references/screening.md) 评估打分，将结果写入 `data/runs/<run_id>/reviews.json`；
4. **下载拆解**：运行 `uv run kp download --run-id <run_id> -i data/runs/<run_id>/reviews.json`；
5. **深度分析**：运行 `uv run kp analyze --run-id <run_id>`（或直接逐个阅读直读文件），依据 [深度分析指南](references/deep-analysis.md) 完成 5 大维度分析并将报告保存至 `data/runs/<run_id>/reports/<sanitized_id>.md`。

### 路径 B：从初筛打分起步 (From Screening)
- **前置条件**：用户提供了已存在的 `run_id`，或目录下已有 `data/runs/<run_id>/patchsets.json`。
- **执行动作**：
  1. 读取 `data/runs/<run_id>/patchsets.json` (或 `manifest.json`)；
  2. 遵循 [初筛指南](references/screening.md) 完成打分与推荐判定；
  3. 将 JSON 格式结果写入 `data/runs/<run_id>/reviews.json`；
  4. 提示用户或继续运行 `uv run kp download --run-id <run_id> -i data/runs/<run_id>/reviews.json`。

### 路径 C：从补丁下载与拆解起步 (From Download)
- **前置条件**：已生成 `reviews.json`，或用户明确指定要下载的 Patchset ID（如 `--id <msgid>`）。
- **执行动作**：
  - 基于评审结果下载：`uv run kp download --run-id <run_id> -i data/runs/<run_id>/reviews.json`
  - 或指定特定 ID 下载：`uv run kp download --run-id <run_id> --id "<msgid>"`
  - `kp` 会自动将邮件线程拆解为直读友好文件（Cover Letter、Discussions Markdown 树、独立 `.patch` 文件与 `meta.json`）。

### 路径 D：从深度技术分析起步 (From Deep Analysis)
- **前置条件**：补丁集已完成下载并存在直读目录 `data/runs/<run_id>/patchsets/<sanitized_id>/`。
- **执行动作**：
  - **方式一（CLI 自动调度）**：运行 `uv run kp analyze --run-id <run_id>`；
  - **方式二（Agent 直接分析）**：直接使用文件查看工具阅读该目录下的 `00-cover-letter.md`、`discussions.md`、`patches/*.patch` 及 `meta.json`，遵循 [深度分析指南](references/deep-analysis.md) 中的 5 大维度展开技术分析，并将报告保存至 `data/runs/<run_id>/reports/<sanitized_id>.md`。

### 路径 E：靶向单个补丁集分析 (Single Patchset Target)
- **执行动作**：
  - 若用户提供了指定 Message-ID，直接组合执行：
    ```bash
    uv run kp download --run-id <run_id> --id "<msgid>"
    uv run kp analyze --run-id <run_id> --id "<msgid>"
    ```

---

## 🛠️ 2. `kp` CLI 命令速查与自然语言查询映射

### 2.1 自然语言转 `lei q` 查询规则 (`kp fetch`)

`kp fetch` 底层调用 `lei q`。构建查询语句时必须遵循以下规则：

1. **强制安全时间跨度限制**：查询条件中**必须**包含 `d:` 时间过滤。
   - 相对时间：`d:2.hours.ago..`、`d:24.hours.ago..`、`d:48.hours.ago..`、`d:1.day.ago..`
   - 绝对时间：`d:2026-08-31T08:00..2026-08-31T10:00`
2. **过滤回复邮件**：建议始终加上 `NOT s:Re`，避免拉取重复的单封回复邮件。
3. **常见内核子系统邮件列表 (List Identifier)**：
   - 内存管理 (MM)：`l:linux-mm.kvack.org`
   - 调度器 / 锁 / RCU / 核心内核：`l:linux-kernel@vger.kernel.org`
   - 文件系统 (VFS/FS)：`l:linux-fsdevel@vger.kernel.org`
   - 块设备与 IO：`l:linux-block@vger.kernel.org` 或 `l:io-uring@vger.kernel.org`
   - 网络子系统：`l:netdev@vger.kernel.org`
   - BPF / eBPF：`l:bpf@vger.kernel.org`
   - 架构特定：`l:linux-arm-kernel@lists.infradead.org`、`l:linux-riscv@lists.infradead.org`
   - 虚拟化：`l:kvm@vger.kernel.org`

#### 自然语言映射示例表
| 用户自然语言意图 | 推荐的 `kp fetch` 命令 |
|---|---|
| “分析过去两小时内存管理子系统的改动” | `uv run kp fetch -q "l:linux-mm.kvack.org AND NOT s:Re AND d:2.hours.ago.."` |
| “查看最近1小时网络子系统 netdev 补丁” | `uv run kp fetch -q "l:netdev@vger.kernel.org AND NOT s:Re AND d:1.hours.ago.."` |
| “检索过去2小时内包含 bcachefs 的补丁” | `uv run kp fetch -q "s:bcachefs AND NOT s:Re AND d:2.hours.ago.."` |
| “抓取过去90分钟 BPF 的补丁集” | `uv run kp fetch -q "l:bpf@vger.kernel.org AND NOT s:Re AND d:90.minutes.ago.."` |
| “查看 LKML 上过去2小时与 RCU 或 lock 相关的补丁” | `uv run kp fetch -q "(s:rcu OR s:lock OR s:spinlock) AND NOT s:Re AND d:2.hours.ago.."` |

---

### 2.2 CLI 常用命令汇总

```bash
# 1. 抓取元数据
uv run kp fetch -q "<lei_query>"

# 2. 下载补丁集 (支持基于 reviews.json 或指定 ID)
uv run kp download --run-id <run_id> -i data/runs/<run_id>/reviews.json
uv run kp download --run-id <run_id> --id "<msgid_1>" --id "<msgid_2>"
uv run kp download --run-id <run_id> -i data/runs/<run_id>/reviews.json --min-score 80

# 3. 执行阶段三深度分析
uv run kp analyze --run-id <run_id>                                    # 全量分析该 run 下所有补丁集
uv run kp analyze --run-id <run_id> --id "<msgid>"                     # 仅分析指定补丁集
uv run kp analyze --run-id <run_id> --agent opencode                   # 指定使用的外部 Agent
uv run kp analyze --run-id <run_id> --concurrency 2                    # 设置并发数
uv run kp analyze --run-id <run_id> --dry-run                          # 仅预检补丁集直读文件完整性
```

---

## 📁 3. 会话数据流与目录规范

所有数据均按会话保存在 `data/runs/<run_id>/` 目录下：

```text
data/runs/<run_id>/
├── manifest.json              # [阶段一] 会话清单与元数据
├── raw_metadata.json          # [阶段一] lei 返回的原始邮件列表
├── patchsets.json             # [阶段一] 并查集聚合后的补丁集列表
├── reviews.json               # [初筛产物] AI 打分与推荐列表 (0-100分)
├── filtered_patchsets.json    # [阶段二] 经筛选后实际待下载的补丁集
├── patchsets/                 # [阶段二] 直读友好型拆解目录
│   └── <sanitized_msgid>/     # 转义后的安全目录名
│       ├── 00-cover-letter.md # 系列背景、动机与整体 Diffstat
│       ├── discussions.md     # 社区 Review 讨论树 (Markdown 引用排版)
│       ├── patches/           # 独立拆解的标准 Git Patch 文件
│       │   ├── 0001-xxx.patch # 包含 Commit Message、Trailers 与统一 Diff
│       │   └── 0002-xxx.patch
│       ├── meta.json          # 轻量级索引元数据
│       ├── parsed_series.json # 结构化数据
│       └── series.mbx         # 原始邮件线程 Mbox
└── reports/                   # [阶段三产物] 各补丁集独立深度技术分析报告
    ├── <sanitized_msgid_1>.md
    └── <sanitized_msgid_2>.md
```

---

## 📖 4. 渐进式披露参考文档 (Progressive Disclosure)

根据当前所处阶段，查阅对应的细分准则文档：

- **阶段一初筛打分与 `reviews.json` 生成规范**：请查阅 [初筛指南 (references/screening.md)](references/screening.md)
  - 涵盖核心子系统权重、变更性质、RFC 价值评估标准与 JSON Schema。
- **阶段三深度技术分析 5 大核心维度与报告模板**：请查阅 [深度分析指南 (references/deep-analysis.md)](references/deep-analysis.md)
  - 涵盖：① 背景动机与架构设计、② 锁与并发安全、③ 内存与资源生命周期、④ 潜在回归与性能/兼容性风险、⑤ 社区审阅洞察与争议点，以及标准 Markdown 报告模板。
