# 技术设计规范：Linux 内核补丁抓取与 AI 分析工具 (kp) - 阶段一

## 1. 概述与设计原则

本项目旨在构建一个针对 Linux 内核补丁邮件（Linux Kernel Mailing Lists / lore.kernel.org）的自动化抓取、AI 筛选与深入分析工具。

### 核心设计原则
1. **分层、低耦合、灵活的架构**：
   - 适配器层（Lei / B4 外部工具通信）、核心领域层（清洗、聚合、提示词生成）、持久化层（Run 会话文件管理）、CLI 表示层严格分离。
2. **轻量、低开销**：
   - 使用 Python 3.10+ 原生类型与 Pydantic，避免繁重的 ORM 与无用依赖。
   - `prompt.md` 引用清洗后数据的绝对路径，不内嵌大量数据，节约上下文开销。
3. **安全受控**：
   - 测试与日常运行时严格实施安全过滤，单次查询时间跨度不得超过 3 小时（解析 `d:` 条件）。

---

## 2. 系统架构与模块划分

```
┌──────────────────────────────────────────────────────────┐
│                      CLI 表示层                          │
│               src/kp/cli.py (Click / Typer)              │
│                 Subcommand: `kp fetch`                   │
└────────────────────────────┬─────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────┐
│                     应用编排层                           │
│               src/kp/core/pipeline.py                    │
│   FetchPipeline (Validate -> Fetch -> Clean -> Persist)  │
└──────┬─────────────────────┬─────────────────────┬───────┘
       │                     │                     │
┌──────▼─────┐ ┌─────────────▼─────────────┐ ┌─────▼───────┐
│ 配置管理层 │ │        领域核心层         │ │外部适配器层│
│src/kp/     │ │      src/kp/core/         │ │src/kp/     │
│config.py   │ │  - aggregator.py (聚合)   │ │adapters/   │
│config.toml │ │  - prompt.py (提示词生成) │ │- lore.py   │
└────────────┘ └─────────────┬─────────────┘ └─────────────┘
                             │
┌────────────────────────────▼─────────────────────────────┐
│                       存储持久化层                       │
│                 src/kp/storage/session.py                │
│             data/runs/<run_id>/ (JSON, MD)               │
└──────────────────────────────────────────────────────────┘
```

---

## 3. 配置系统设计 (Configuration)

支持通过 TOML 格式配置文件管理全局及运行参数，加载优先级：
1. CLI 命令行参数（显式覆盖）
2. 项目工作区配置文件（`./kp.toml` 或 `./config.toml`）
3. 用户全局配置文件（`~/.config/kp/config.toml`）
4. 内置默认配置

### 3.1 配置文件结构 (`kp.toml`)
```toml
[safety]
# 最大允许查询时间跨度（分钟），默认 180 分钟（3 小时）
max_time_span_minutes = 180
# 是否强制要求 query 必须包含 d: 时间范围
require_time_filter = true

[lore]
# 默认使用的 lore public-inbox 地址
inbox_url = "https://lore.kernel.org/all/"
# lei 命令执行超时时间（秒）
timeout_seconds = 60

[storage]
# 数据持久化根目录
data_dir = "data/runs"
```

### 3.2 配置模型 (`AppConfig`)
```python
from pydantic import BaseModel, Field

class SafetyConfig(BaseModel):
    max_time_span_minutes: int = 180
    require_time_filter: bool = True

class LoreConfig(BaseModel):
    inbox_url: str = "https://lore.kernel.org/all/"
    timeout_seconds: int = 60

class StorageConfig(BaseModel):
    data_dir: str = "data/runs"

class AppConfig(BaseModel):
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    lore: LoreConfig = Field(default_factory=LoreConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
```

---

## 4. 数据模型定义 (Data Models)

```python
from pydantic import BaseModel, Field
from typing import List, Optional

class RawMessage(BaseModel):
    """直接映射 lei q 返回的单条邮件元数据"""
    blob: Optional[str] = None
    m: str                                                  # Message-ID
    s: str                                                  # Subject
    f: List[List[Optional[str]]]                            # From: [["Name", "email"]]
    t: Optional[List[List[Optional[str]]]] = None          # To: [["Name", "email"], ...]
    c: Optional[List[List[Optional[str]]]] = None          # Cc: [["Name", "email"], ...]
    dt: Optional[str] = None                                # Date (ISO8601)
    rt: Optional[str] = None                                # Received Time
    refs: Optional[List[str]] = Field(default_factory=list) # Referenced Message-IDs

class PatchItem(BaseModel):
    """补丁集中的单封 Patch 描述"""
    index: int                                              # Patch 序号 (如 1)
    total: int                                              # Patch 总数 (如 6)
    title: str                                              # 原始完整标题 (保留 [PATCH 1/6] ...)
    message_id: str                                         # 单封 Patch 的 Message-ID
    date: Optional[str] = None                              # 发送时间

class Patchset(BaseModel):
    """清洗与聚合后的完整补丁集"""
    id: str                                                 # 下载全套 patchset 的代表性 Message-ID (0/N 或 1/N 或独立 patch ID)
    title: str                                              # 系列标题 (Cover Letter 标题或 Patch 1 标题)
    author_name: str                                        # 作者姓名
    author_email: str                                       # 作者邮箱
    date: Optional[str] = None                              # 发送时间
    is_cover_letter: bool                                   # 是否含有 0/N Cover Letter
    total_patches: int                                      # 系列包含的 patch 总数
    patches: List[PatchItem]                                # 包含的所有 patch 列表 (按 index 排序)

class RunManifest(BaseModel):
    """运行会话摘要清单"""
    run_id: str                                             # 会话 ID (如 20260830_175000_3a8f1b)
    timestamp: str                                          # 执行时间戳 (ISO)
    query: str                                              # 执行的查询语句
    total_raw_messages: int                                 # 原始消息数
    total_patchsets: int                                    # 聚合后的补丁集数
```

---

## 5. 适配器与安全校验 (LoreClient & Safety Validator)

### 5.1 安全时间校验规则 (`SafetyValidator`)
在调用 `lei q` 之前，必须对 `--query` 参数进行安全解析，并结合配置项 `SafetyConfig` 进行校验：
1. **强制存在时间过滤**：
   - 若 `require_time_filter=True`，检查 query 中是否包含 `d:` 过滤语法（如 `d:2.hours.ago..`、`d:90.minutes.ago..`）。
   - 若未提供 `d:` 条件，立即抛出 `SafetyValidationError`，阻止拉取全量数据。
2. **时间跨度限制**：
   - **相对时间语法**：
     - `d:X.hours.ago..`：校验 $X \le \text{max\_time\_span\_hours}$（默认 48 小时）；
     - `d:X.minutes.ago..`：校验 $X / 60 \le \text{max\_time\_span\_hours}$；
     - `d:X.days.ago..`：校验 $X \times 24 \le \text{max\_time\_span\_hours}$；
     - 禁止使用 `week`, `month`, `year` 等大粒度跨度（除非配置放宽限制）。
   - **绝对时间语法**：
     - `d:YYYY-MM-DDTHH:MM:SSZ..`：计算与当前时间的跨度，必须 $\le \text{max\_time\_span\_hours}$。
   - 超出限制一律抛出 `SafetyValidationError`，并输出明确友好的修复提示。


### 5.2 `LoreClient`
- 命令构造：`lei q -t -I <inbox_url> "<query>" -f json`
- 执行与错误处理：
  - 验证 `lei` 二进制是否存在。
  - 处理返回的 JSON 结构并反序列化为 `List[RawMessage]`。
  - 若 `lei` 返回非 0 状态码，捕获 stderr 并抛出 `LoreExecutionError`。

---

## 6. Patchset 聚合算法 (`PatchsetAggregator`)

### 6.1 邮件主题解析
使用正则表达式提取标题中的 patch 序号元数据：
- 识别 `[...PATCH... 0/N]` -> Cover Letter (`index=0, total=N`)
- 识别 `[...PATCH... X/N]` ($X \ge 1$) -> Subpatch (`index=X, total=N`)
- 识别 `[...PATCH...]`（无分卷号或 `1/1`） -> Standalone Patch (`index=1, total=1`)

### 6.2 补丁集关联机制
1. 每个独立的系列（Thread Cluster）通过其唯一代表 Message-ID 标识。
2. 若邮件为 Cover Letter（0/N），其自身的 `m` 成为该 Cluster 的 Root ID。
3. 若邮件为分卷补丁（1/N ~ N/N），通过其 `refs` 查找最早引用的 Root ID 并归并。
4. 若为独立 Patch，以其自身 `m` 作为 Root ID。
5. 最终生成的 `Patchset.id` 设为 Cover Letter 的 `m`（若有）或 Patch 1 的 `m`，确保可直接用于 `b4 mbox <id>`。
6. `Patchset.patches` 按 `index` 从小到大排序。

---

## 7. 持久化与提示词生成

### 7.1 会话目录结构 (`SessionManager`)
每次执行生成独立目录：`data/runs/<timestamp>_<random_id>/`（或 `StorageConfig.data_dir` 指定目录）
- `manifest.json`：运行元数据（时间、Query、统计数）
- `raw_metadata.json`：`lei q` 原始 JSON
- `patchsets.json`：清洗聚合后的 `List[Patchset]`
- `prompt.md`：AI 提示词文件

### 7.2 提示词模板 (`PromptBuilder`)
`prompt.md` 包含：
1. 资深 Linux 内核专家角色定位与审查目标。
2. 指向 `patchsets.json` 的绝对路径。
3. 评估准则（子系统重要性、Bug 级别、架构重构、RFC 价值）。
4. 标准化 JSON 输出格式约定（供阶段二消费）。

---

## 8. 验证计划 (Verification Plan)

### 8.1 自动化测试 (`pytest`)
- `test_config.py`：测试 TOML 配置文件加载、默认值回退与环境覆盖。
- `test_safety.py`：测试各种合法与非法 query 格式（缺失 d:、超过配置跨度限制、合规时间等）。
- `test_aggregator.py`：使用真实的 lore 邮件样本测试 Cover Letter、分卷补丁、独立补丁的聚合准确性。
- `test_storage.py`：测试会话目录创建与 JSON/MD 文件读写。
- `test_pipeline.py`：使用 Mock 测试端到端 Pipeline 流程。

### 8.2 真实环境端到端验证
- 使用 `uv run kp fetch --query "l:linux-mm.kvack.org AND NOT s:Re AND d:15.minutes.ago.."` 执行实际抓取，检查 `data/runs/` 下生成的文件内容完整性。
