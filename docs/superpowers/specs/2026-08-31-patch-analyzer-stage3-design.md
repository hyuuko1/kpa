# 技术设计规范：Linux 内核补丁抓取与 AI 分析工具 (kp) - 阶段三

本文档定义 Linux 内核补丁分析工具 `kp` 的 **阶段三：AI Agent 深度内核技术分析与报告生成**。

---

## 1. 概述与目标

阶段三聚焦于 **自动化驱动外部 AI Agent（如 `agy`、`opencode`）对拆解后的补丁集直读文件进行多维度内核深度分析，并将生成的结构化技术报告持久化**。
同时，将原本在阶段一与阶段二中重复动态生成的静态 Prompt 统一重构为 **具备渐进式披露能力的单一项目级 Skill**，使外部 AI Agent 具备全流程调度与分析能力。

### 核心目标
1. **统一 Skill 驱动全生命周期**：
   - 建立 `.agents/skills/kernel-patch-analyzer/` 统一项目级 Skill。
   - 主入口 `SKILL.md` 引导 Agent 掌握 `kp fetch -> download -> analyze` 全流程规范；
   - 通过 `references/screening.md` 与 `references/deep-analysis.md` 实现渐进式披露；
   - 移除阶段一和阶段二每次运行时重复生成的静态 Prompt 文件（`prompt.md` 与 `stage3_prompt.md`）。
2. **模块化 Agent 适配器层 (`src/kp/adapters/agent.py`)**：
   - 提供 `BaseAgentRunner` 抽象接口，实现 `AgyAgentRunner` 与 `OpenCodeAgentRunner`；
   - 负责 CLI 可用性探测、极简指令调用、超时保护与产物后置校验。
3. **阶段三编排流水线 (`src/kp/core/analyze_pipeline.py`)**：
   - 检查目标补丁集直读文件完整性（`00-cover-letter.md`、`discussions.md`、`patches/`、`meta.json`）；
   - 为各补丁集分发 Agent 分析任务；
   - 跟踪执行耗时与状态，校验报告输出。
4. **独立报告持久化**：
   - 每个补丁集生成独立的深度分析报告：`data/runs/<run_id>/reports/<sanitized_id>.md`；
   - 不生成全局汇总报告，保持补丁集分析的独立解耦。
5. **CLI 命令行扩展**：
   - 提供 `kp analyze --run-id <run_id> [--id <target_id> ...] [--agent agy|opencode] [--concurrency N] [--dry-run]`。

---

## 2. 系统全景架构与模块划分

```
┌──────────────────────────────────────────────────────────┐
│                      CLI 表示层                          │
│               src/kp/cli.py (Click)                      │
│            `kp fetch` / `kp download` / `kp analyze`     │
└────────────────────────────┬─────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────┐
│                    应用流水线编排层                      │
│               src/kp/core/pipeline.py (Fetch)            │
│            src/kp/core/download_pipeline.py (Download)   │
│            src/kp/core/analyze_pipeline.py (Analyze)     │
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

## 3. Skill 规范与结构

### 3.1 目录组织
```text
.agents/skills/kernel-patch-analyzer/
├── SKILL.md
└── references/
    ├── screening.md
    └── deep-analysis.md
```

### 3.2 `SKILL.md` (主入口)
```markdown
---
name: kernel-patch-analyzer
description: "Linux kernel patch screening, download, and deep technical analysis using the kp tool."
---

# Linux Kernel Patch Analyzer Guide

This skill guides AI agents through screening, downloading, and deeply analyzing Linux kernel patchsets using the `kp` toolkit.

## Workflow Overview

1. **Stage 1 (Screening)**:
   - Read `data/runs/<run_id>/patchsets.json` or `manifest.json`.
   - Score patchsets (0-100) and decide recommendation following `references/screening.md`.
   - Write output to `data/runs/<run_id>/reviews.json`.

2. **Stage 2 (Download & Decomposition)**:
   - Run `kp download --run-id <run_id> -i reviews.json`.
   - Generates direct-read files under `data/runs/<run_id>/patchsets/<sanitized_id>/`:
     - `00-cover-letter.md`
     - `discussions.md`
     - `patches/*.patch`
     - `meta.json`

3. **Stage 3 (Deep Analysis & Reporting)**:
   - When asked to analyze a patchset at `data/runs/<run_id>/patchsets/<sanitized_id>/`:
   - Direct-read `00-cover-letter.md`, `discussions.md`, `patches/*.patch`, and `meta.json`.
   - Perform technical analysis across the 5 core dimensions specified in `references/deep-analysis.md`.
   - **Persist the generated Markdown report directly to**:
     `data/runs/<run_id>/reports/<sanitized_id>.md`
```

### 3.3 `references/screening.md`
包含原阶段一评分维度与权重（核心子系统影响、内存/并发/性能关联、架构演进意义、Bug 严重性），以及 `reviews.json` 的 JSON Schema 定义。

### 3.4 `references/deep-analysis.md`
定义 5 大核心分析维度与输出报告标准模板：
1. **背景动机与架构设计 (Architecture & Context)**：根本问题、现有内核缺陷/瓶颈、子系统设计演进；
2. **锁与并发安全 (Concurrency & Locking)**：Spinlock/Mutex/RCU/Lockless 原语、死锁与竞争条件、ABBA 锁反序；
3. **内存与资源生命周期 (Memory & Lifecycle)**：内存泄漏、UAF、越界、Double-free、错误路径资源清理；
4. **潜在回归与性能/兼容性风险 (Regressions & Impact)**：API/ABI 破坏、架构适配性、关键路径延迟与性能；
5. **社区审阅洞察与争议点 (Community Discussion & Key Debates)**：维护者质疑重点、作者辩论答复、未决技术分歧。

**报告标准模板**：
```markdown
# 补丁集深度技术分析: [<patchset_title>] (<sanitized_id>)

## 1. 摘要与背景评述 (Executive Summary)
- **子系统**: ...
- **核心动机**: ...
- **变更规模**: ...

## 2. 关键技术方案与代码实现剖析 (Technical Deep Dive)
...

## 3. 锁、并发与内存安全评估 (Safety & Concurrency Assessment)
...

## 4. 潜在风险与回归隐患 (Risk & Regression Analysis)
...

## 5. 社区评审洞察与争议要点 (Community Review & Insights)
...
```

---

## 4. 配置与数据模型

### 4.1 配置文件扩展 (`config.toml` & `src/kp/config.py`)
```toml
[agent]
default = "agy"              # 默认使用的 Agent 类型: "agy" | "opencode"
agy_cmd = "agy"              # agy CLI 可执行路径
opencode_cmd = "opencode"    # opencode CLI 可执行路径
timeout_seconds = 600        # 单个补丁集分析超时时间 (秒)
concurrency = 1              # 并发分析数 (默认为 1 串行)
```

```python
class AgentConfig(BaseModel):
    default: str = "agy"
    agy_cmd: str = "agy"
    opencode_cmd: str = "opencode"
    timeout_seconds: int = 600
    concurrency: int = 1

class AppConfig(BaseModel):
    # ...
    agent: AgentConfig = Field(default_factory=AgentConfig)
```

### 4.2 数据模型定义 (`src/kp/models.py`)
```python
class PatchsetAnalysis(BaseModel):
    msgid: str
    sanitized_id: str
    status: Literal["success", "failed", "skipped"]
    report_path: Optional[Path] = None
    error_message: Optional[str] = None
    duration_seconds: float = 0.0

class AnalyzeRunResult(BaseModel):
    run_id: str
    analyses: List[PatchsetAnalysis] = Field(default_factory=list)
    total_count: int = 0
    success_count: int = 0
    failed_count: int = 0
```

---

## 5. 核心组件与接口设计

### 5.1 Agent 适配器层 (`src/kp/adapters/agent.py`)

#### 异常体系
- `AgentError(Exception)`
- `AgentNotFoundError(AgentError)`
- `AgentExecutionError(AgentError)`
- `AgentTimeoutError(AgentError)`

#### 接口定义
```python
class BaseAgentRunner(ABC):
    def __init__(self, cmd: str, timeout_seconds: int = 600) -> None:
        self.cmd = cmd
        self.timeout_seconds = timeout_seconds

    @abstractmethod
    def check_available(self) -> bool:
        """检查 Agent 命令是否存在 (shutil.which)"""

    @abstractmethod
    def run_analysis(
        self,
        patchset_dir: Path,
        report_output_path: Path,
        skill_name: str = "kernel-patch-analyzer",
    ) -> None:
        """调用外部 Agent 执行分析"""

class AgyAgentRunner(BaseAgentRunner):
    """Antigravity CLI (agy) 适配器"""
    def check_available(self) -> bool:
        return shutil.which(self.cmd) is not None

    def run_analysis(
        self,
        patchset_dir: Path,
        report_output_path: Path,
        skill_name: str = "kernel-patch-analyzer",
    ) -> None:
        if not self.check_available():
            raise AgentNotFoundError(f"Agent executable '{self.cmd}' not found in PATH.")

        prompt = f"使用 skill '{skill_name}' 分析补丁集：{patchset_dir.resolve()}"
        args = [self.cmd, "-p", prompt]

        try:
            res = subprocess.run(
                args,
                timeout=self.timeout_seconds,
                capture_output=True,
                text=True,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise AgentTimeoutError(f"Agent analysis timed out after {self.timeout_seconds}s") from e

        if res.returncode != 0:
            raise AgentExecutionError(f"Agent failed with exit code {res.returncode}: {res.stderr}")

        if not report_output_path.exists() or report_output_path.stat().st_size == 0:
            raise AgentExecutionError(f"Agent finished but report file '{report_output_path}' was not generated.")

class OpenCodeAgentRunner(BaseAgentRunner):
    """OpenCode CLI 适配器"""
    def check_available(self) -> bool:
        return shutil.which(self.cmd) is not None

    def run_analysis(
        self,
        patchset_dir: Path,
        report_output_path: Path,
        skill_name: str = "kernel-patch-analyzer",
    ) -> None:
        if not self.check_available():
            raise AgentNotFoundError(f"Agent executable '{self.cmd}' not found in PATH.")

        prompt = f"使用 skill '{skill_name}' 分析补丁集：{patchset_dir.resolve()}"
        args = [self.cmd, "run", prompt]

        try:
            res = subprocess.run(
                args,
                timeout=self.timeout_seconds,
                capture_output=True,
                text=True,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise AgentTimeoutError(f"Agent analysis timed out after {self.timeout_seconds}s") from e

        if res.returncode != 0:
            raise AgentExecutionError(f"Agent failed with exit code {res.returncode}: {res.stderr}")

        if not report_output_path.exists() or report_output_path.stat().st_size == 0:
            raise AgentExecutionError(f"Agent finished but report file '{report_output_path}' was not generated.")

def get_agent_runner(agent_type: str, config: AgentConfig) -> BaseAgentRunner:
    agent_type = agent_type.lower()
    if agent_type == "agy":
        return AgyAgentRunner(cmd=config.agy_cmd, timeout_seconds=config.timeout_seconds)
    elif agent_type == "opencode":
        return OpenCodeAgentRunner(cmd=config.opencode_cmd, timeout_seconds=config.timeout_seconds)
    else:
        raise ValueError(f"Unsupported agent type: {agent_type}. Supported: 'agy', 'opencode'")
```

---

### 5.2 存储管理扩展 (`src/kp/storage/session.py`)

- 新增方法：
  - `get_reports_dir(run_id: str) -> Path`：确保并返回 `data/runs/<run_id>/reports/` 目录。
  - `get_report_path(run_id: str, sanitized_id: str) -> Path`：返回 `data/runs/<run_id>/reports/{sanitized_id}.md`。
  - `list_reports(run_id: str) -> List[Path]`：列出该会话下已生成的分析报告。
  - `get_downloaded_patchset_dirs(run_id: str) -> List[Path]`：扫描获取 `patchsets/` 下已完成直读拆解的目录列表。

---

### 5.3 阶段三流水线编排 (`src/kp/core/analyze_pipeline.py`)

```python
class AnalyzePipeline:
    def __init__(self, config: AppConfig, session_manager: Optional[SessionManager] = None) -> None:
        self.config = config
        self.session_manager = session_manager or SessionManager(config.storage.data_dir)

    def run(
        self,
        run_id: str,
        target_ids: Optional[List[str]] = None,
        agent_type: Optional[str] = None,
        concurrency: Optional[int] = None,
        dry_run: bool = False,
        runner_override: Optional[BaseAgentRunner] = None,
    ) -> AnalyzeRunResult:
        # 1. 验证会话存在
        # 2. 定位待分析补丁集目录
        # 3. 校验各补丁集目录是否包含完整的直读文件 (meta.json, patches/, discussions.md, 00-cover-letter.md)
        # 4. 若 dry_run 为 True，直接返回各补丁集就绪状态
        # 5. 实例化 AgentRunner (根据 agent_type 或 config.agent)
        # 6. 并发/串行执行 runner.run_analysis(patchset_dir, report_path)
        # 7. 汇总并返回 AnalyzeRunResult
```

---

### 5.4 CLI 接口设计 (`src/kp/cli.py`)

```python
@main.command(name="analyze")
@click.option("--run-id", required=True, help="指定会话 ID (run_id)")
@click.option("--id", "target_ids", multiple=True, help="指定要分析的 Patchset ID (默认全量)")
@click.option("--agent", type=click.Choice(["agy", "opencode"], case_sensitive=False), help="指定 Agent 类型")
@click.option("--concurrency", type=int, help="并发分析数")
@click.option("--dry-run", is_flag=True, help="仅检查待分析补丁集完整性，不触发 Agent 调用")
@click.pass_context
def analyze_cmd(ctx, run_id, target_ids, agent, concurrency, dry_run):
    ...
```

---

## 6. 阶段一与阶段二重构与清理

1. **废弃并移除 Prompt 动态生成类**：
   - 移除 `src/kp/core/prompt.py` (`PromptBuilder`)；
   - 移除 `src/kp/core/stage3_prompt.py` (`Stage3PromptBuilder`)；
   - 移除 `tests/test_prompt.py` 和 `tests/test_stage3_prompt.py`。
2. **流水线返回值与 CLI 提示调整**：
   - `FetchPipeline` & `FetchRunResult`：移除 `prompt_path`，CLI 提示引导使用 `kernel-patch-analyzer` skill；
   - `DownloadPipeline` & `DownloadRunResult`：移除 `stage3_prompt_path`，CLI 提示引导直接运行 `kp analyze`。

---

## 7. 测试与验证策略 (TDD)

1. **适配器测试 (`tests/test_agent_adapter.py`)**：
   - 测试 `AgyAgentRunner` / `OpenCodeAgentRunner` 的 `check_available`；
   - 测试正常调用、超时拦截、非零退出码及报告未生成时的异常捕获；
   - 测试 `get_agent_runner` 工厂分发。
2. **存储扩展测试 (`tests/test_storage.py`)**：
   - 测试 `get_reports_dir`、`get_report_path`、`list_reports` 与 `get_downloaded_patchset_dirs`。
3. **阶段三流水线测试 (`tests/test_analyze_pipeline.py`)**：
   - 校验补丁集完整性检查逻辑与 `dry_run` 行为；
   - 注入 Mock `AgentRunner` 验证成功分析、失败处理与并发控制。
4. **CLI 测试 (`tests/test_cli.py`)**：
   - 测试 `kp analyze` 正常执行、参数覆盖、错误捕获；
   - 回归测试调整后的 `kp fetch` 与 `kp download`。
5. **Skill 规范检查**：
   - 验证 `.agents/skills/kernel-patch-analyzer/SKILL.md` 及引用文档完整性。
