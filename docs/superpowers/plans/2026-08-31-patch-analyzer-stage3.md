# Linux Kernel Patch Analyzer (kp) Stage 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Stage 3 automated AI Agent-driven deep kernel patch analysis, unified skill architecture with progressive disclosure, modular agent adapter subsystem (`agy` / `opencode`), report persistence, and `kp analyze` CLI command.

**Architecture:** A unified skill in `.agents/skills/kernel-patch-analyzer/` replaces repetitive dynamic prompts. The CLI layer (`kp analyze`) delegates to `AnalyzePipeline`, which checks direct-read artifact integrity, executes `AgentRunner` (`AgyAgentRunner` / `OpenCodeAgentRunner`) to trigger external agent analysis with minimal prompts, and persists independent Markdown reports to `data/runs/<run_id>/reports/<sanitized_id>.md`.

**Tech Stack:** Python >=3.10, Pydantic v2, Click, pytest, uv, subprocess, concurrent.futures.

**Spec:** [`docs/superpowers/specs/2026-08-31-patch-analyzer-stage3-design.md`](file:///code/agent/kp/docs/superpowers/specs/2026-08-31-patch-analyzer-stage3-design.md)

## Global Constraints

- Package and dependency management must strictly use `uv` (e.g. `uv run pytest`, `uv run kp`).
- Do not reference or access other projects under `/code/agent`.
- All tests must follow TDD (red-green-refactor) and 100% pass with `uv run pytest -v`.
- Code quality must pass `uv run ruff check`.
- Design document [`docs/design.md`](file:///code/agent/kp/docs/design.md) must stay synchronized.

---

### Task 1: Unified Project Skill Creation & Progressive Disclosure

**Files:**
- Create: `.agents/skills/kernel-patch-analyzer/SKILL.md`
- Create: `.agents/skills/kernel-patch-analyzer/references/screening.md`
- Create: `.agents/skills/kernel-patch-analyzer/references/deep-analysis.md`
- Test: `tests/test_skill_structure.py`

**Interfaces:**
- Produces: Persistent skill directory structure readable by external agents (`agy`, `opencode`)

- [ ] **Step 1: Write the failing test for skill directory and files existence**

```python
# tests/test_skill_structure.py
from pathlib import Path

def test_skill_files_exist():
    skill_dir = Path(".agents/skills/kernel-patch-analyzer")
    assert skill_dir.is_dir(), f"Skill directory {skill_dir} does not exist"
    
    skill_main = skill_dir / "SKILL.md"
    assert skill_main.is_file(), f"{skill_main} does not exist"
    content = skill_main.read_text(encoding="utf-8")
    assert "name: kernel-patch-analyzer" in content
    assert "references/screening.md" in content
    assert "references/deep-analysis.md" in content
    assert "data/runs/<run_id>/reports/<sanitized_id>.md" in content

    screening_ref = skill_dir / "references" / "screening.md"
    assert screening_ref.is_file(), f"{screening_ref} does not exist"
    screening_content = screening_ref.read_text(encoding="utf-8")
    assert "reviews.json" in screening_content

    analysis_ref = skill_dir / "references" / "deep-analysis.md"
    assert analysis_ref.is_file(), f"{analysis_ref} does not exist"
    analysis_content = analysis_ref.read_text(encoding="utf-8")
    assert "Architecture & Context" in analysis_content
    assert "Concurrency & Locking" in analysis_content
    assert "Memory & Lifecycle" in analysis_content
    assert "Regressions & Impact" in analysis_content
    assert "Community Discussion & Key Debates" in analysis_content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_skill_structure.py -v`
Expected: FAIL with "Skill directory ... does not exist"

- [ ] **Step 3: Create skill files and directory structure**

Create `.agents/skills/kernel-patch-analyzer/SKILL.md`, `references/screening.md`, and `references/deep-analysis.md` with complete screening criteria, 5-dimension analysis instructions, and Markdown report template.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_skill_structure.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add .agents/skills/kernel-patch-analyzer tests/test_skill_structure.py
git commit -m "feat(skill): add unified kernel-patch-analyzer skill with progressive disclosure"
```

---

### Task 2: Stage 3 Data Models & Agent Configuration

**Files:**
- Modify: `src/kp/config.py`
- Modify: `config.toml`
- Modify: `src/kp/models.py`
- Test: `tests/test_config.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `AgentConfig` in `AppConfig.agent`, `PatchsetAnalysis`, `AnalyzeRunResult` in `src/kp/models.py`

- [ ] **Step 1: Write the failing tests for AgentConfig and Analysis models**

In `tests/test_config.py`:
```python
def test_agent_config_defaults():
    config = load_config(None)
    assert config.agent.default == "agy"
    assert config.agent.agy_cmd == "agy"
    assert config.agent.opencode_cmd == "opencode"
    assert config.agent.timeout_seconds == 600
    assert config.agent.concurrency == 1
```

In `tests/test_models.py`:
```python
from pathlib import Path
from kp.models import PatchsetAnalysis, AnalyzeRunResult

def test_patchset_analysis_model():
    analysis = PatchsetAnalysis(
        msgid="<test@example.com>",
        sanitized_id="test_example_com",
        status="success",
        report_path=Path("data/runs/123/reports/test_example_com.md"),
        duration_seconds=12.5,
    )
    assert analysis.status == "success"
    assert analysis.report_path == Path("data/runs/123/reports/test_example_com.md")

    run_result = AnalyzeRunResult(
        run_id="run-1",
        analyses=[analysis],
        total_count=1,
        success_count=1,
        failed_count=0,
    )
    assert run_result.success_count == 1
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_config.py tests/test_models.py -v`
Expected: FAIL with AttributeError: 'AppConfig' object has no attribute 'agent' / ImportError for PatchsetAnalysis

- [ ] **Step 3: Implement AgentConfig in config.py and PatchsetAnalysis/AnalyzeRunResult in models.py**

In `src/kp/config.py`:
```python
class AgentConfig(BaseModel):
    default: str = "agy"
    agy_cmd: str = "agy"
    opencode_cmd: str = "opencode"
    timeout_seconds: int = 600
    concurrency: int = 1

# Add to AppConfig:
# agent: AgentConfig = Field(default_factory=AgentConfig)
```

In `config.toml`:
```toml
[agent]
default = "agy"
agy_cmd = "agy"
opencode_cmd = "opencode"
timeout_seconds = 600
concurrency = 1
```

In `src/kp/models.py`:
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/kp/config.py src/kp/models.py config.toml tests/test_config.py tests/test_models.py
git commit -m "feat(models): add AgentConfig and Stage 3 analysis models"
```

---

### Task 3: SessionManager Storage Extension for Reports & Patchset Discovery

**Files:**
- Modify: `src/kp/storage/session.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Produces: `SessionManager.get_reports_dir(run_id)`, `SessionManager.get_report_path(run_id, sanitized_id)`, `SessionManager.list_reports(run_id)`, `SessionManager.get_downloaded_patchset_dirs(run_id)`

- [ ] **Step 1: Write failing tests for SessionManager report helpers**

In `tests/test_storage.py`:
```python
def test_session_manager_reports_helpers(tmp_path):
    sm = SessionManager(tmp_path)
    run_id = "test-run-123"
    sm.create_session(run_id)

    reports_dir = sm.get_reports_dir(run_id)
    assert reports_dir.is_dir()
    assert reports_dir == tmp_path / run_id / "reports"

    report_path = sm.get_report_path(run_id, "patchset_1_msgid")
    assert report_path == tmp_path / run_id / "reports" / "patchset_1_msgid.md"

    assert sm.list_reports(run_id) == []
    report_path.write_text("# Report", encoding="utf-8")
    assert sm.list_reports(run_id) == [report_path]

def test_session_manager_get_downloaded_patchset_dirs(tmp_path):
    sm = SessionManager(tmp_path)
    run_id = "test-run-456"
    sm.create_session(run_id)
    
    assert sm.get_downloaded_patchset_dirs(run_id) == []

    p1_dir = tmp_path / run_id / "patchsets" / "msg_1"
    p1_dir.mkdir(parents=True)
    (p1_dir / "meta.json").write_text("{}", encoding="utf-8")
    
    dirs = sm.get_downloaded_patchset_dirs(run_id)
    assert len(dirs) == 1
    assert dirs[0] == p1_dir
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/test_storage.py -v`
Expected: FAIL with AttributeError: 'SessionManager' object has no attribute 'get_reports_dir'

- [ ] **Step 3: Implement methods in SessionManager**

In `src/kp/storage/session.py`:
Implement `get_reports_dir`, `get_report_path`, `list_reports`, `get_downloaded_patchset_dirs`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_storage.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/kp/storage/session.py tests/test_storage.py
git commit -m "feat(storage): add report and patchset directory management methods to SessionManager"
```

---

### Task 4: Agent Adapter Subsystem (`BaseAgentRunner`, `AgyAgentRunner`, `OpenCodeAgentRunner`)

**Files:**
- Create: `src/kp/adapters/agent.py`
- Test: `tests/test_agent_adapter.py`

**Interfaces:**
- Produces: `BaseAgentRunner`, `AgyAgentRunner`, `OpenCodeAgentRunner`, `get_agent_runner(agent_type, config)`, and exceptions `AgentError`, `AgentNotFoundError`, `AgentExecutionError`, `AgentTimeoutError`.

- [ ] **Step 1: Write failing tests for agent adapters**

In `tests/test_agent_adapter.py`:
```python
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from kp.adapters.agent import (
    BaseAgentRunner,
    AgyAgentRunner,
    OpenCodeAgentRunner,
    get_agent_runner,
    AgentNotFoundError,
    AgentExecutionError,
    AgentTimeoutError,
)
from kp.config import AgentConfig

def test_get_agent_runner():
    cfg = AgentConfig(default="agy", agy_cmd="agy", timeout_seconds=300)
    runner = get_agent_runner("agy", cfg)
    assert isinstance(runner, AgyAgentRunner)
    assert runner.cmd == "agy"
    assert runner.timeout_seconds == 300

    runner_oc = get_agent_runner("opencode", cfg)
    assert isinstance(runner_oc, OpenCodeAgentRunner)

    with pytest.raises(ValueError):
        get_agent_runner("unknown", cfg)

def test_agy_runner_executable_not_found(tmp_path):
    runner = AgyAgentRunner(cmd="nonexistent_agy_cmd")
    with pytest.raises(AgentNotFoundError):
        runner.run_analysis(tmp_path / "patchset", tmp_path / "report.md")

@patch("shutil.which", return_value="/usr/bin/agy")
@patch("subprocess.run")
def test_agy_runner_successful_execution(mock_run, mock_which, tmp_path):
    patchset_dir = tmp_path / "patchset"
    patchset_dir.mkdir()
    report_file = tmp_path / "report.md"

    def side_effect(cmd, **kwargs):
        report_file.write_text("# Successful Report", encoding="utf-8")
        return MagicMock(returncode=0, stdout="OK", stderr="")

    mock_run.side_effect = side_effect

    runner = AgyAgentRunner(cmd="agy", timeout_seconds=120)
    runner.run_analysis(patchset_dir, report_file)

    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0][0] == "agy"
    assert args[0][1] == "-p"
    assert "kernel-patch-analyzer" in args[0][2]
    assert str(patchset_dir.resolve()) in args[0][2]

@patch("shutil.which", return_value="/usr/bin/agy")
@patch("subprocess.run")
def test_agy_runner_report_not_generated(mock_run, mock_which, tmp_path):
    patchset_dir = tmp_path / "patchset"
    patchset_dir.mkdir()
    report_file = tmp_path / "report.md"
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    runner = AgyAgentRunner(cmd="agy")
    with pytest.raises(AgentExecutionError, match="report file.*was not generated"):
        runner.run_analysis(patchset_dir, report_file)

@patch("shutil.which", return_value="/usr/bin/agy")
@patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="agy", timeout=10))
def test_agy_runner_timeout(mock_run, mock_which, tmp_path):
    patchset_dir = tmp_path / "patchset"
    patchset_dir.mkdir()
    report_file = tmp_path / "report.md"

    runner = AgyAgentRunner(cmd="agy", timeout_seconds=10)
    with pytest.raises(AgentTimeoutError):
        runner.run_analysis(patchset_dir, report_file)
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/test_agent_adapter.py -v`
Expected: FAIL with ModuleNotFoundError: No module named 'kp.adapters.agent'

- [ ] **Step 3: Implement `src/kp/adapters/agent.py`**

Implement `BaseAgentRunner`, `AgyAgentRunner`, `OpenCodeAgentRunner`, `get_agent_runner` and custom exception classes.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_agent_adapter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/kp/adapters/agent.py tests/test_agent_adapter.py
git commit -m "feat(adapter): add AI agent runner adapter subsystem for agy and opencode"
```

---

### Task 5: Stage 3 Core Analyze Pipeline (`AnalyzePipeline`)

**Files:**
- Create: `src/kp/core/analyze_pipeline.py`
- Test: `tests/test_analyze_pipeline.py`

**Interfaces:**
- Produces: `AnalyzePipeline.run(run_id, target_ids, agent_type, concurrency, dry_run, runner_override) -> AnalyzeRunResult`

- [ ] **Step 1: Write failing tests for AnalyzePipeline**

In `tests/test_analyze_pipeline.py`:
```python
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from kp.config import load_config
from kp.storage.session import SessionManager
from kp.core.analyze_pipeline import AnalyzePipeline
from kp.adapters.agent import BaseAgentRunner, AgentExecutionError

class DummyRunner(BaseAgentRunner):
    def __init__(self, should_fail: bool = False):
        super().__init__(cmd="dummy")
        self.should_fail = should_fail
        self.called_with = []

    def check_available(self) -> bool:
        return True

    def run_analysis(self, patchset_dir: Path, report_output_path: Path, skill_name: str = "kernel-patch-analyzer") -> None:
        self.called_with.append((patchset_dir, report_output_path))
        if self.should_fail:
            raise AgentExecutionError("Analysis failed")
        report_output_path.write_text("# Success Report", encoding="utf-8")

def test_analyze_pipeline_session_not_found(tmp_path):
    cfg = load_config(None)
    cfg.storage.data_dir = tmp_path
    pipeline = AnalyzePipeline(cfg)
    with pytest.raises(FileNotFoundError):
        pipeline.run("nonexistent_run")

def test_analyze_pipeline_dry_run_and_integrity_check(tmp_path):
    sm = SessionManager(tmp_path)
    run_id = "test-run-1"
    sm.create_session(run_id)

    # Valid patchset
    p1 = tmp_path / run_id / "patchsets" / "msg_1"
    p1.mkdir(parents=True)
    (p1 / "meta.json").write_text('{"msgid": "<msg_1>"}', encoding="utf-8")
    (p1 / "00-cover-letter.md").write_text("Cover", encoding="utf-8")
    (p1 / "patches").mkdir()
    (p1 / "patches" / "0001.patch").write_text("Diff", encoding="utf-8")

    cfg = load_config(None)
    cfg.storage.data_dir = tmp_path
    pipeline = AnalyzePipeline(cfg, sm)

    res = pipeline.run(run_id, dry_run=True)
    assert res.total_count == 1
    assert res.analyses[0].status == "skipped"

def test_analyze_pipeline_successful_run(tmp_path):
    sm = SessionManager(tmp_path)
    run_id = "test-run-2"
    sm.create_session(run_id)

    p1 = tmp_path / run_id / "patchsets" / "msg_1"
    p1.mkdir(parents=True)
    (p1 / "meta.json").write_text('{"msgid": "<msg_1>"}', encoding="utf-8")
    (p1 / "00-cover-letter.md").write_text("Cover", encoding="utf-8")
    (p1 / "patches").mkdir()

    cfg = load_config(None)
    cfg.storage.data_dir = tmp_path
    dummy_runner = DummyRunner(should_fail=False)
    pipeline = AnalyzePipeline(cfg, sm)

    res = pipeline.run(run_id, runner_override=dummy_runner)
    assert res.total_count == 1
    assert res.success_count == 1
    assert res.failed_count == 0
    assert res.analyses[0].status == "success"
    assert res.analyses[0].report_path.exists()
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/test_analyze_pipeline.py -v`
Expected: FAIL with ModuleNotFoundError: No module named 'kp.core.analyze_pipeline'

- [ ] **Step 3: Implement `src/kp/core/analyze_pipeline.py`**

Implement `AnalyzePipeline` class with verification of direct-read files, execution via `AgentRunner` (supporting concurrency with `ThreadPoolExecutor`), error recording, and `AnalyzeRunResult` generation.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_analyze_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/kp/core/analyze_pipeline.py tests/test_analyze_pipeline.py
git commit -m "feat(core): add Stage 3 AnalyzePipeline orchestration"
```

---

### Task 6: Stage 1 & Stage 2 Prompt Cleanup and Decoupling

**Files:**
- Delete: `src/kp/core/prompt.py`
- Delete: `src/kp/core/stage3_prompt.py`
- Delete: `tests/test_prompt.py`
- Delete: `tests/test_stage3_prompt.py`
- Modify: `src/kp/core/pipeline.py`
- Modify: `src/kp/core/download_pipeline.py`
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_download_pipeline.py`

**Interfaces:**
- Modifies: `FetchPipeline.run()` -> returns `FetchRunResult(run_id, raw_count, patchset_count, run_dir)` without `prompt_path`.
- Modifies: `DownloadPipeline.run()` -> returns `DownloadRunResult(run_id, downloaded_count, run_dir)` without `stage3_prompt_path`.

- [ ] **Step 1: Update `tests/test_pipeline.py` and `tests/test_download_pipeline.py`**

Remove expectations of `prompt.md` and `stage3_prompt.md` in test assertions.

- [ ] **Step 2: Run tests to verify failures**

Run: `uv run pytest tests/test_pipeline.py tests/test_download_pipeline.py -v`

- [ ] **Step 3: Refactor FetchPipeline and DownloadPipeline, and remove redundant prompt generators**

- Delete `src/kp/core/prompt.py` and `src/kp/core/stage3_prompt.py`.
- Delete `tests/test_prompt.py` and `tests/test_stage3_prompt.py`.
- In `src/kp/core/pipeline.py`: remove `PromptBuilder` and `prompt_path` from `FetchRunResult`.
- In `src/kp/core/download_pipeline.py`: remove `Stage3PromptBuilder` and `stage3_prompt_path` from `DownloadRunResult`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pipeline.py tests/test_download_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git rm src/kp/core/prompt.py src/kp/core/stage3_prompt.py tests/test_prompt.py tests/test_stage3_prompt.py
git add src/kp/core/pipeline.py src/kp/core/download_pipeline.py tests/test_pipeline.py tests/test_download_pipeline.py
git commit -m "refactor: remove runtime prompt generators in favor of unified skill"
```

---

### Task 7: CLI Subcommand `kp analyze` & Updated Stage 1/2 Hints

**Files:**
- Modify: `src/kp/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `kp analyze --run-id <run_id> [--id <target_id>] [--agent agy|opencode] [--concurrency N] [--dry-run]`
- Updates: `kp fetch` and `kp download` CLI output hints to reference skill and `kp analyze`.

- [ ] **Step 1: Write failing tests for `kp analyze` and updated `kp fetch`/`download` output in `tests/test_cli.py`**

In `tests/test_cli.py`:
- Add test for `kp analyze --run-id ... --dry-run`.
- Add test for `kp analyze` running with mock pipeline.
- Update `test_fetch_cmd` and `test_download_cmd` output string assertions.

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL (missing analyze command and altered output strings)

- [ ] **Step 3: Implement `analyze_cmd` in `src/kp/cli.py` and update hints**

- Add `@main.command(name="analyze")` in `src/kp/cli.py`.
- Update `fetch_cmd` to mention `kernel-patch-analyzer` skill.
- Update `download_cmd` to mention `kp analyze --run-id <id>`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/kp/cli.py tests/test_cli.py
git commit -m "feat(cli): add kp analyze command and update workflow hints"
```

---

### Task 8: Full Verification, Documentation Sync & Quality Checks

**Files:**
- Modify: `README.md` (Update CLI command reference and workflow)
- Verify: `docs/design.md` (Verify 100% sync)

- [ ] **Step 1: Update README.md with Stage 3 `kp analyze` command and skill documentation**

Update README.md to describe the complete 3-stage workflow and the `kernel-patch-analyzer` skill.

- [ ] **Step 2: Run full automated test suite**

Run: `uv run pytest -v`
Expected: 100% tests pass

- [ ] **Step 3: Run Ruff check and format**

Run: `uv run ruff check`
Run: `uv run ruff format --check`
Expected: 0 errors / clean format

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: update README with Stage 3 analyze CLI and skill documentation"
```
