# AGENTS.md — Linux Kernel Patch Analyzer (`kp`) Agent 协作指南

本文档是任何 AI Agent 在本仓库（`/code/agent/kp`）开展工作的核心行为准则与操作手册。

---

## 1. 项目概览与核心定位

`kp` 是一个用 Python 编写的 Linux 内核补丁抓取与 AI 自动化分析工具，由 `uv` 进行依赖管理。
系统通过分阶段流水线，完成从 LKML / lore.kernel.org 抓取补丁、AI 价值打分筛选、完整邮件线程拉取与结构化清洗，到最终供 AI 深度技术分析的全流程。

- **核心技术栈**: Python >=3.10, Pydantic v2, Click, pytest, `b4`, `lei`。
- **环境要求**: 包管理必须使用 `uv`（如 `uv run pytest`, `uv run kp`）。
- **隔离原则**: 严格禁止参考或访问 `/code/agent` 下的其他项目。

---

## 2. 核心铁律：设计文档自主维护 (Mandatory Design Doc Maintenance)

> [!IMPORTANT]
> **设计文档与代码必须时刻保持 100% 一致。**
> 任何 Agent 在本仓库进行任何功能开发、接口变动、数据模型演进或存储格式调整时，**必须自主同步维护并更新设计文档**，严禁留待用户提醒。

### 自主维护执行规则：
1. **主设计文档**: [`docs/design.md`](docs/design.md) 是全系统的单一事实来源（Single Source of Truth）。
2. **触发更新的时机**:
   - 修改或新增数据模型（`src/kp/models.py`）；
   - 修改或新增 CLI 命令与参数选项（`src/kp/cli.py`）；
   - 调整存储目录或文件命名结构（`src/kp/storage/session.py`）；
   - 增加或重构核心模块、适配器或流水线（`src/kp/core/`、`src/kp/adapters/`）；
   - 提出新的设计优化（如输出格式变更、新的处理阶段）。
3. **完成标准**:
   - 任何提交（Commit）或向用户汇报交付之前，必须检查并确认 `docs/design.md` 以及相关 Spec（`docs/superpowers/specs/`）已如实反映当前代码状态。

---

## 3. 架构与设计原则

1. **分层单向依赖**:
   - CLI 层 (`src/kp/cli.py`) -> 流水线编排层 (`src/kp/core/*pipeline.py`) -> 领域核心层 (`src/kp/core/`) & 适配器层 (`src/kp/adapters/`) -> 存储层 (`src/kp/storage/`).
   - 严禁逆向或跨层混乱调用。
2. **AI 直读友好型存储**:
   - 避免生成超大且深层嵌套的单 JSON 文件。
   - 补丁集应拆解为直读 Markdown（`00-cover-letter.md`、`discussions.md`）和原生补丁（`patches/*.patch`），辅以轻量 `meta.json`。
3. **严格安全受控**:
   - `SafetyValidator` 强制校验查询时间跨度不得超过 48 小时（解析 `d:` 条件）。


---

## 4. 开发与测试工作流

1. **测试驱动开发 (TDD)**:
   - 编写或修改代码前，必须先编写测试并见证其失败（RED），再实现最小代码使其通过（GREEN）。
   - 单元测试运行命令：`uv run pytest -v`
   - 单文件测试：`uv run pytest tests/test_xxx.py -v`
2. **代码质量与 Lint**:
   - 格式化与检查：`uv run ruff check` / `uv run ruff format`
   - 类型安全：使用 Python 3.10+ 类型注解，利用 Pydantic v2 进行运行时强校验。
3. **高内聚低耦合**:
   - 各类核心组件（如 `LoreClient`, `B4Client`, `MboxParser`, `SessionManager`）保持清晰的依赖注入接口，确保单元测试可独立 Mock 验证。

---

## 5. 关键文件与上下文索引 (Context Pointers)

- **系统设计与架构全景**: [`docs/design.md`](docs/design.md)
- **阶段一设计规范**: [`docs/superpowers/specs/2026-08-30-patch-analyzer-stage1-design.md`](docs/superpowers/specs/2026-08-30-patch-analyzer-stage1-design.md)
- **阶段二设计规范**: [`docs/superpowers/specs/2026-08-30-patch-analyzer-stage2-design.md`](docs/superpowers/specs/2026-08-30-patch-analyzer-stage2-design.md)
- **阶段三设计规范**: [`docs/superpowers/specs/2026-08-31-patch-analyzer-stage3-design.md`](docs/superpowers/specs/2026-08-31-patch-analyzer-stage3-design.md)
- **数据模型定义**: [`src/kp/models.py`](src/kp/models.py)
- **CLI 命令定义**: [`src/kp/cli.py`](src/kp/cli.py)
- **会话与持久化管理**: [`src/kp/storage/session.py`](src/kp/storage/session.py)
