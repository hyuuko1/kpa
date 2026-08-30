# Linux Kernel Patch Analyzer (kp) - 阶段二实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现阶段二：AI 评审结果解析、基于 `b4` 的完整 Patchset 拉取、保留树形评论的 Mbox 结构化清洗，以及阶段三深度分析提示词构建与 CLI 扩展。

**Architecture:** 
- 适配器层 (`B4Client`) 调用底层 `b4 mbox` 下载完整讨论线程；
- 核心解析层 (`MboxParser`) 使用 Python 标准库解码 mbox，提取 Cover Letter、Patches (diff/trailers/commit message) 与 Maintainer 嵌套树形回复 (`ParsedComment`) 并输出 `parsed_series.json`；
- 编排层 (`DownloadPipeline`) 与存储层 (`SessionManager`) 协同处理 AI 评审打分过滤、批量下载清洗与生成阶段三提示词 (`stage3_prompt.md`)；
- CLI 层 (`kp download`) 提供按 ID、按评审结果文件及管道输入的组合式下载命令。

**Tech Stack:** Python 3.10+, Pydantic v2, Click, mailbox/email (Python standard library), b4 (CLI tool), pytest.

**Spec:** [`docs/superpowers/specs/2026-08-30-patch-analyzer-stage2-design.md`](file:///code/agent/kp/docs/superpowers/specs/2026-08-30-patch-analyzer-stage2-design.md)

## Global Constraints

- 严禁参考 `/code/agent` 中的其他项目。
- 遵循分层架构，保持低耦合、轻量与低开销。
- 所有代码均必须编写完备的自动化单元测试（TDD 流程），全量通过 `uv run pytest`。

---

### Task 1: 扩展阶段二数据模型与配置

**Files:**
- Modify: `src/kp/models.py`
- Modify: `src/kp/config.py`
- Modify: `tests/test_models.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `PatchReview(id: str, title: Optional[str], score: int, recommend: bool, reason: str)`
  - `ParsedComment(author: str, date: Optional[str], message_id: str, in_reply_to: Optional[str], body: str, replies: List[ParsedComment])`
  - `ParsedCoverLetter(subject: str, author: str, date: Optional[str], message_id: str, body: str, diffstat: Optional[str])`
  - `ParsedPatch(index: int, total: int, subject: str, author: str, date: Optional[str], message_id: str, commit_message: str, trailers: List[str], diffstat: Optional[str], diff: str, comments: List[ParsedComment])`
  - `ParsedPatchset(id: str, title: str, total_patches: int, cover_letter: Optional[ParsedCoverLetter], patches: List[ParsedPatch], general_comments: List[ParsedComment])`
  - `B4Config(timeout_seconds: int = 120)` in `AppConfig`

- [ ] **Step 1: 编写数据模型与配置测试用例**

在 `tests/test_models.py` 中添加阶段二模型的序列化与反序列化测试（包括 `ParsedComment` 树形嵌套测试），在 `tests/test_config.py` 中添加 `b4` 配置加载测试。

```python
# tests/test_models.py 追加
from kp.models import PatchReview, ParsedComment, ParsedCoverLetter, ParsedPatch, ParsedPatchset

def test_patch_review_model():
    review = PatchReview(id="msg123", score=85, recommend=True, reason="Important fix")
    assert review.id == "msg123"
    assert review.score == 85
    assert review.recommend is True

def test_parsed_comment_tree_model():
    child = ParsedComment(
        author="Reviewer <rev@kernel.org>",
        message_id="msg2",
        in_reply_to="msg1",
        body="Looks good, thanks.",
    )
    parent = ParsedComment(
        author="Author <auth@kernel.org>",
        message_id="msg1",
        body="Please review this patch.",
        replies=[child],
    )
    assert len(parent.replies) == 1
    assert parent.replies[0].message_id == "msg2"
    
    # JSON 往返测试
    json_data = parent.model_dump_json()
    loaded = ParsedComment.model_validate_json(json_data)
    assert loaded.replies[0].author == "Reviewer <rev@kernel.org>"

def test_parsed_patchset_model():
    patch = ParsedPatch(
        index=1,
        total=1,
        subject="[PATCH] fix something",
        author="Dev <dev@test.org>",
        message_id="patch1",
        commit_message="Fix a bug in mm",
        trailers=["Signed-off-by: Dev <dev@test.org>"],
        diff="--- a/mm.c\n+++ b/mm.c\n@@ ...",
    )
    patchset = ParsedPatchset(
        id="patch1",
        title="[PATCH] fix something",
        total_patches=1,
        patches=[patch],
    )
    assert patchset.total_patches == 1
    assert patchset.cover_letter is None
    assert len(patchset.patches) == 1
```

- [ ] **Step 2: 运行测试并验证失败**

Run: `uv run pytest tests/test_models.py tests/test_config.py -v`
Expected: FAIL (cannot import `PatchReview`, `ParsedComment`, etc.)

- [ ] **Step 3: 实现数据模型与 B4 配置**

在 `src/kp/models.py` 中添加 `PatchReview`, `ParsedComment`, `ParsedCoverLetter`, `ParsedPatch`, `ParsedPatchset`。
在 `src/kp/config.py` 中添加 `B4Config` 并集成到 `AppConfig`。

- [ ] **Step 4: 运行测试并验证通过**

Run: `uv run pytest tests/test_models.py tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add src/kp/models.py src/kp/config.py tests/test_models.py tests/test_config.py
git commit -m "feat: add Stage 2 data models and B4Config"
```

---

### Task 2: 实现 B4 适配器 (`src/kp/adapters/b4.py`)

**Files:**
- Create: `src/kp/adapters/b4.py`
- Create: `tests/test_b4_adapter.py`

**Interfaces:**
- Produces:
  - `B4Client(config: B4Config)`
  - `B4Client.fetch_thread(msgid: str, output_dir: Path, mbox_name: str = "series.mbx") -> Path`
  - `B4Client.sanitize_id(msgid: str) -> str`
  - `B4NotFoundError(Exception)`
  - `B4ExecutionError(Exception)`

- [ ] **Step 1: 编写 B4 适配器测试用例 (Mock 命令调用与错误分支)**

```python
# tests/test_b4_adapter.py
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from kp.config import B4Config
from kp.adapters.b4 import B4Client, B4ExecutionError, B4NotFoundError

def test_sanitize_id():
    client = B4Client(B4Config())
    raw = "<20260830-test.123@domain.org>"
    sanitized = client.sanitize_id(raw)
    assert "<" not in sanitized and ">" not in sanitized
    assert "@" not in sanitized
    assert sanitized == "20260830-test.123_domain.org"

@patch("shutil.which")
def test_b4_not_found(mock_which):
    mock_which.return_value = None
    client = B4Client(B4Config())
    with pytest.raises(B4NotFoundError):
        client.fetch_thread("test@msgid", Path("/tmp"))

@patch("shutil.which", return_value="/usr/bin/b4")
@patch("subprocess.run")
def test_fetch_thread_success(mock_run, mock_which, tmp_path):
    mock_run.return_value = MagicMock(returncode=0, stdout="Downloaded", stderr="")
    target_mbox = tmp_path / "series.mbx"
    target_mbox.write_text("From xxx\nSubject: test\n", encoding="utf-8")

    client = B4Client(B4Config(timeout_seconds=30))
    result_path = client.fetch_thread("test@msgid", tmp_path, mbox_name="series.mbx")
    
    assert result_path == target_mbox
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[0] == "/usr/bin/b4"
    assert "mbox" in args
    assert "test@msgid" in args
    assert "-o" in args
    assert str(tmp_path) in args

@patch("shutil.which", return_value="/usr/bin/b4")
@patch("subprocess.run")
def test_fetch_thread_execution_failure(mock_run, mock_which, tmp_path):
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Error: msgid not found")
    client = B4Client(B4Config())
    with pytest.raises(B4ExecutionError) as exc_info:
        client.fetch_thread("notfound@msgid", tmp_path)
    assert "b4 mbox failed" in str(exc_info.value)
```

- [ ] **Step 2: 运行测试并验证失败**

Run: `uv run pytest tests/test_b4_adapter.py -v`
Expected: FAIL (cannot import `B4Client`)

- [ ] **Step 3: 实现 `B4Client` 与异常类**

编写 `src/kp/adapters/b4.py`，实现 `fetch_thread`、`sanitize_id` 以及超时、命令退出码检查与文件存在性校验。

- [ ] **Step 4: 运行测试并验证通过**

Run: `uv run pytest tests/test_b4_adapter.py -v`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add src/kp/adapters/b4.py tests/test_b4_adapter.py
git commit -m "feat: implement B4Client adapter and sanitize_id"
```

---

### Task 3: 实现 Mbox 结构化清洗与树形评论解析器 (`src/kp/core/parser.py`)

**Files:**
- Create: `src/kp/core/parser.py`
- Create: `tests/test_parser.py`

**Interfaces:**
- Produces:
  - `MboxParser`
  - `MboxParser.parse(mbox_path: Path, patchset_id: str, title: str = "") -> ParsedPatchset`

- [ ] **Step 1: 编写 Mbox 解析器单元测试**

测试包含三种场景：
1. 单 Patch 独立邮件；
2. 多 Patch 系列带 Cover Letter；
3. 带有 Reviewer 多层嵌套回复（Author -> Reviewer A -> Author -> Reviewer A & Reviewer B）的讨论树还原。

```python
# tests/test_parser.py
from pathlib import Path
from kp.core.parser import MboxParser

def test_parse_single_patch(tmp_path):
    mbox_file = tmp_path / "single.mbx"
    mbox_file.write_text(
"""From git@z Thu Jan  1 00:00:00 1970
From: Alice <alice@example.com>
Subject: [PATCH] mm: fix null pointer in alloc
Date: Sun, 30 Aug 2026 12:00:00 +0000
Message-Id: <patch1@example.com>
Content-Type: text/plain; charset="utf-8"

Fix a critical null pointer dereference when allocating page.

Signed-off-by: Alice <alice@example.com>
Reviewed-by: Bob <bob@example.com>
---
 mm/alloc.c | 2 ++
 1 file changed, 2 insertions(+)

diff --git a/mm/alloc.c b/mm/alloc.c
index 111..222 100644
--- a/mm/alloc.c
+++ b/mm/alloc.c
@@ -10,6 +10,8 @@ void *alloc(void) {
+    if (!ptr)
+        return NULL;
     return ptr;
 }
-- 
2.43.0
""", encoding="utf-8")

    parser = MboxParser()
    parsed = parser.parse(mbox_file, patchset_id="patch1@example.com")
    
    assert parsed.id == "patch1@example.com"
    assert parsed.total_patches == 1
    assert parsed.cover_letter is None
    assert len(parsed.patches) == 1
    
    patch = parsed.patches[0]
    assert patch.index == 1
    assert patch.author == "Alice <alice@example.com>"
    assert "Fix a critical null pointer" in patch.commit_message
    assert "Signed-off-by: Alice <alice@example.com>" in patch.trailers
    assert "Reviewed-by: Bob <bob@example.com>" in patch.trailers
    assert "diff --git a/mm/alloc.c" in patch.diff

def test_parse_series_with_cover_and_nested_comments(tmp_path):
    mbox_file = tmp_path / "series.mbx"
    mbox_file.write_text(
"""From git@z Thu Jan  1 00:00:00 1970
From: Alice <alice@example.com>
Subject: [PATCH 0/2] mm: revamp page allocator
Date: Sun, 30 Aug 2026 12:00:00 +0000
Message-Id: <cover@example.com>

This series revamps page allocator to improve performance.

Alice (2):
  mm: step 1
  mm: step 2

 mm/alloc.c | 10 ++
 1 file changed, 10 insertions(+)

From git@z Thu Jan  1 00:00:00 1970
From: Alice <alice@example.com>
Subject: [PATCH 1/2] mm: step 1
Date: Sun, 30 Aug 2026 12:01:00 +0000
Message-Id: <p1@example.com>
In-Reply-To: <cover@example.com>

Step 1 description.

Signed-off-by: Alice <alice@example.com>
---
diff --git a/mm/alloc.c b/mm/alloc.c
--- a/mm/alloc.c
+++ b/mm/alloc.c
@@ -1 +1,5 @@
+step 1

From git@z Thu Jan  1 00:00:00 1970
From: Bob <bob@example.com>
Subject: Re: [PATCH 1/2] mm: step 1
Date: Sun, 30 Aug 2026 12:05:00 +0000
Message-Id: <comment1@example.com>
In-Reply-To: <p1@example.com>

Why not do this differently?

From git@z Thu Jan  1 00:00:00 1970
From: Alice <alice@example.com>
Subject: Re: [PATCH 1/2] mm: step 1
Date: Sun, 30 Aug 2026 12:10:00 +0000
Message-Id: <comment2@example.com>
In-Reply-To: <comment1@example.com>

Because of cache alignment.

From git@z Thu Jan  1 00:00:00 1970
From: Alice <alice@example.com>
Subject: [PATCH 2/2] mm: step 2
Date: Sun, 30 Aug 2026 12:02:00 +0000
Message-Id: <p2@example.com>
In-Reply-To: <cover@example.com>

Step 2 description.

Signed-off-by: Alice <alice@example.com>
---
diff --git a/mm/alloc.c b/mm/alloc.c
--- a/mm/alloc.c
+++ b/mm/alloc.c
@@ -2 +2,5 @@
+step 2
""", encoding="utf-8")

    parser = MboxParser()
    parsed = parser.parse(mbox_file, patchset_id="cover@example.com")
    
    assert parsed.cover_letter is not None
    assert "revamp page allocator" in parsed.cover_letter.subject
    assert len(parsed.patches) == 2
    
    # 验证 patch 1 的评论树
    p1 = parsed.patches[0]
    assert len(p1.comments) == 1
    c1 = p1.comments[0]
    assert c1.message_id == "comment1@example.com"
    assert "Why not do this differently?" in c1.body
    assert len(c1.replies) == 1
    assert c1.replies[0].message_id == "comment2@example.com"
    assert "Because of cache alignment." in c1.replies[0].body
```

- [ ] **Step 2: 运行测试并验证失败**

Run: `uv run pytest tests/test_parser.py -v`
Expected: FAIL (cannot import `MboxParser`)

- [ ] **Step 3: 实现 `MboxParser`**

编写 `src/kp/core/parser.py`：
- 使用 `mailbox.mbox` 遍历解析；
- 区分 Cover Letter / Patch / Comment；
- 正则提取 Commit message、Trailers 与 Unified diff；
- 构建父子关系的树形回复结构。

- [ ] **Step 4: 运行测试并验证通过**

Run: `uv run pytest tests/test_parser.py -v`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add src/kp/core/parser.py tests/test_parser.py
git commit -m "feat: implement MboxParser with nested discussion tree reconstruction"
```

---

### Task 4: 阶段三提示词生成器与存储层更新

**Files:**
- Create: `src/kp/core/stage3_prompt.py`
- Modify: `src/kp/storage/session.py`
- Create: `tests/test_stage3_prompt.py`
- Modify: `tests/test_storage.py`

**Interfaces:**
- Produces:
  - `Stage3PromptBuilder.build_prompt(run_id: str, parsed_patchsets_paths: List[Path]) -> str`
  - `SessionManager.save_reviews(run_dir: Path, reviews: List[PatchReview], filtered_patchsets: List[Patchset]) -> None`
  - `SessionManager.save_parsed_patchset(run_dir: Path, sanitized_id: str, parsed_patchset: ParsedPatchset) -> Path`
  - `SessionManager.save_stage3_prompt(run_dir: Path, prompt_content: str) -> Path`
  - `SessionManager.get_run_dir(run_id: str) -> Path`
  - `SessionManager.load_patchsets(run_dir: Path) -> List[Patchset]`

- [ ] **Step 1: 编写测试用例**

编写 `tests/test_stage3_prompt.py` 和 `tests/test_storage.py` 中的扩展方法测试。

- [ ] **Step 2: 运行测试并验证失败**

Run: `uv run pytest tests/test_stage3_prompt.py tests/test_storage.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `Stage3PromptBuilder` 与 `SessionManager` 方法**

编写 `src/kp/core/stage3_prompt.py` 生成标准阶段三深度分析提示词；
在 `src/kp/storage/session.py` 中添加 `save_reviews`、`save_parsed_patchset`、`save_stage3_prompt`、`load_patchsets`、`get_run_dir`。

- [ ] **Step 4: 运行测试并验证通过**

Run: `uv run pytest tests/test_stage3_prompt.py tests/test_storage.py -v`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add src/kp/core/stage3_prompt.py src/kp/storage/session.py tests/test_stage3_prompt.py tests/test_storage.py
git commit -m "feat: add Stage3PromptBuilder and extend SessionManager for stage 2 persistence"
```

---

### Task 5: 实现 DownloadPipeline 业务编排器

**Files:**
- Create: `src/kp/core/download_pipeline.py`
- Create: `tests/test_download_pipeline.py`

**Interfaces:**
- Produces:
  - `DownloadPipeline(config: AppConfig, b4_client: Optional[B4Client] = None, session_manager: Optional[SessionManager] = None)`
  - `DownloadPipeline.run(run_id: str, target_ids: Optional[List[str]] = None, reviews_content: Optional[str] = None, min_score: int = 70) -> DownloadResult`
  - `DownloadResult(run_id: str, run_dir: Path, downloaded_count: int, parsed_patchsets: List[ParsedPatchset], stage3_prompt_path: Optional[Path])`

- [ ] **Step 1: 编写 DownloadPipeline 单元测试 (包含直接 ID 下载与 Review 过滤下载)**

```python
# tests/test_download_pipeline.py
from pathlib import Path
from unittest.mock import MagicMock
from kp.config import AppConfig
from kp.models import Patchset, PatchReview, ParsedPatchset
from kp.core.download_pipeline import DownloadPipeline

def test_download_pipeline_by_reviews(tmp_path):
    # 构建测试环境与 Mock
    ...
```

- [ ] **Step 2: 运行测试并验证失败**

Run: `uv run pytest tests/test_download_pipeline.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `DownloadPipeline`**

编写 `src/kp/core/download_pipeline.py`：
- 处理 JSON 评审输入 / 提取目标 patchsets；
- 逐个调用 `B4Client.fetch_thread`；
- 调用 `MboxParser.parse` 并持久化 `parsed_series.json`；
- 生成 `stage3_prompt.md`；
- 组装 `DownloadResult` 返回。

- [ ] **Step 4: 运行测试并验证通过**

Run: `uv run pytest tests/test_download_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add src/kp/core/download_pipeline.py tests/test_download_pipeline.py
git commit -m "feat: implement DownloadPipeline orchestrator"
```

---

### Task 6: 扩展 CLI 接口 (`kp download`)

**Files:**
- Modify: `src/kp/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces:
  - CLI subcommand `kp download --run-id <run_id> [--id <msgid>] [--input <path|->] [--min-score <score>]`

- [ ] **Step 1: 编写 CLI download 子命令测试**

测试 Click `CliRunner` 对 `--id`、`--input file.json`、`--input -`（标准输入）以及各种错误输入（文件不存在、JSON 格式错误、缺少 run-id 等）的处理。

- [ ] **Step 2: 运行测试并验证失败**

Run: `uv run pytest tests/test_cli.py -k download -v`
Expected: FAIL (No such command 'download')

- [ ] **Step 3: 在 `src/kp/cli.py` 中实现 `download_cmd`**

注册 `@main.command(name="download")`，解析参数，调用 `DownloadPipeline` 并以丰富易读的终端格式输出下载与解析进度、汇总以及阶段三提示词指引。

- [ ] **Step 4: 运行测试并验证通过**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: 提交更改**

```bash
git add src/kp/cli.py tests/test_cli.py
git commit -m "feat: implement kp download CLI subcommand"
```

---

### Task 7: 全量回归测试与真实环境验证

**Files:**
- Test: All tests in `tests/`
- Workspace verification: 针对真实 sample data 进行端到端验证

- [ ] **Step 1: 执行全量测试套件**

Run: `uv run pytest -v`
Expected: 100% PASS

- [ ] **Step 2: 运行真实环境端到端验证**

在已有 `data/runs/20260830_123341_542a01/` 目录下进行实际下载与结构化解析测试：
1. 构造一份模拟 `review.json`；
2. 执行 `uv run kp download --run-id 20260830_123341_542a01 --input <review.json>`；
3. 检查生成的 `parsed_series.json`、`series.mbx` 与 `stage3_prompt.md` 完整性与结构正确性。

- [ ] **Step 3: 提交最终阶段二交付记录**

```bash
git add .
git commit -m "chore: complete Stage 2 implementation and verification"
```
