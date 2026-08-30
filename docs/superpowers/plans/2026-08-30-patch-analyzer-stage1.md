# Linux 内核补丁抓取与分析工具 (kp) 阶段一实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个基于 uv 与 Python 3.10+ 的 Linux 内核补丁抓取与预处理工具 `kp`（阶段一），支持对 `lei q` 查询的安全校验（<=3小时）、元数据持久化、Patchset 结构清洗聚合以及生成指向清洗数据的 AI 筛选提示词。

**Architecture:** 采用分层管道式架构（CLI -> Pipeline -> Adapters/Core/Storage）。通过 Pydantic 定义强类型不可变模型；通过 `SafetyValidator` 校验查询时间跨度；通过 `LoreClient` 调用 `lei`；通过 `PatchsetAggregator` 关联线程聚合并提取 Patchset 代表性 Message-ID；通过 `SessionManager` 持久化到会话目录。

**Tech Stack:** Python >=3.10, `uv`, `pydantic >= 2.0`, `click >= 8.0`, `tomli` / Python built-in `tomllib`, `pytest`.

**Spec:** [`docs/superpowers/specs/2026-08-30-patch-analyzer-stage1-design.md`](file:///code/agent/kp/docs/superpowers/specs/2026-08-30-patch-analyzer-stage1-design.md)

## Global Constraints

- 测试时最多拉取最近 3 个小时的数据，禁止大跨度（解析 `d:` 限制）。
- 用 Python 语言，用 `uv` 管理项目与依赖。
- 禁止参考 `/code/agent` 中的其他项目。
- `prompt.md` 中不直接内嵌全部补丁列表内容，改为包含数据列表文件（`patchsets.json`）的绝对路径。
- 补丁标题列表保留 `[PATCH x/N]` 前缀。
- 分层、低耦合、灵活、轻量、低开销。

---

### Task 1: 项目骨架与配置管理模块 (Scaffolding & Config)

**Files:**
- Create: `pyproject.toml`
- Create: `src/kp/__init__.py`
- Create: `src/kp/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: Standard library (`tomllib` or `tomli`), `pathlib.Path`, `pydantic`.
- Produces:
  - `class SafetyConfig(BaseModel)`: `max_time_span_minutes: int = 180`, `require_time_filter: bool = True`
  - `class LoreConfig(BaseModel)`: `inbox_url: str = "https://lore.kernel.org/all/"`, `timeout_seconds: int = 60`
  - `class StorageConfig(BaseModel)`: `data_dir: str = "data/runs"`
  - `class AppConfig(BaseModel)`: `safety: SafetyConfig`, `lore: LoreConfig`, `storage: StorageConfig`
  - `def load_config(config_path: Optional[Path] = None) -> AppConfig`

- [ ] **Step 1: 初始化 pyproject.toml 并配置 uv**

```toml
[project]
name = "kp"
version = "0.1.0"
description = "Linux Kernel Patch Fetcher & AI Analyzer"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "click>=8.1.0",
    "pydantic>=2.5.0",
]

[project.scripts]
kp = "kp.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[dependency-groups]
dev = [
    "pytest>=8.0.0",
]
```

- [ ] **Step 2: 编写配置模块失败测试**

```python
# tests/test_config.py
from pathlib import Path
import pytest
from kp.config import load_config, AppConfig, SafetyConfig

def test_load_default_config():
    config = load_config(config_path=Path("non_existent_file.toml"))
    assert isinstance(config, AppConfig)
    assert config.safety.max_time_span_minutes == 180
    assert config.safety.require_time_filter is True
    assert config.lore.inbox_url == "https://lore.kernel.org/all/"
    assert config.storage.data_dir == "data/runs"

def test_load_custom_toml_config(tmp_path: Path):
    custom_toml = tmp_path / "custom.toml"
    custom_toml.write_text("""
[safety]
max_time_span_minutes = 60
require_time_filter = true

[lore]
inbox_url = "https://lore.kernel.org/linux-mm/"
timeout_seconds = 30

[storage]
data_dir = "my_custom_runs"
""", encoding="utf-8")
    config = load_config(config_path=custom_toml)
    assert config.safety.max_time_span_minutes == 60
    assert config.lore.inbox_url == "https://lore.kernel.org/linux-mm/"
    assert config.lore.timeout_seconds == 30
    assert config.storage.data_dir == "my_custom_runs"
```

- [ ] **Step 3: 运行测试验证失败**

Run: `uv run pytest tests/test_config.py`
Expected: FAIL (ModuleNotFoundError: No module named 'kp')

- [ ] **Step 4: 编写配置模块实现**

```python
# src/kp/__init__.py
__version__ = "0.1.0"
```

```python
# src/kp/config.py
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

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

def load_config(config_path: Optional[Path] = None) -> AppConfig:
    """加载配置：优先指定路径 -> ./kp.toml -> ./config.toml -> ~/.config/kp/config.toml -> 默认"""
    search_paths = []
    if config_path:
        search_paths.append(Path(config_path))
    search_paths.extend([
        Path("kp.toml"),
        Path("config.toml"),
        Path.home() / ".config" / "kp" / "config.toml",
    ])

    for p in search_paths:
        if p.is_file():
            try:
                with open(p, "rb") as f:
                    data = tomllib.load(f)
                return AppConfig.model_validate(data)
            except Exception:
                continue

    return AppConfig()
```

- [ ] **Step 5: 运行测试验证通过**

Run: `uv run pytest tests/test_config.py`
Expected: PASS

- [ ] **Step 6: Git 提交**

```bash
git add pyproject.toml src/kp/__init__.py src/kp/config.py tests/test_config.py
git commit -m "feat: add project scaffolding and configuration system"
```

---

### Task 2: 核心数据模型 (Data Models)

**Files:**
- Create: `src/kp/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: `pydantic`.
- Produces:
  - `class RawMessage(BaseModel)`
  - `class PatchItem(BaseModel)`
  - `class Patchset(BaseModel)`
  - `class RunManifest(BaseModel)`

- [ ] **Step 1: 编写数据模型失败测试**

```python
# tests/test_models.py
from kp.models import RawMessage, PatchItem, Patchset, RunManifest

def test_raw_message_parsing():
    raw_dict = {
        "m": "test@msgid.1",
        "s": "[PATCH 1/2] mm: sample fix",
        "f": [["John Doe", "john@example.com"]],
        "refs": ["root@msgid.0"],
        "dt": "2026-08-30T10:00:00Z",
    }
    msg = RawMessage.model_validate(raw_dict)
    assert msg.m == "test@msgid.1"
    assert msg.s == "[PATCH 1/2] mm: sample fix"
    assert msg.f[0][0] == "John Doe"
    assert msg.refs == ["root@msgid.0"]

def test_patchset_structure():
    patch1 = PatchItem(
        index=1,
        total=2,
        title="[PATCH 1/2] mm: sample fix 1",
        message_id="patch1@msgid",
        date="2026-08-30T10:00:00Z"
    )
    patchset = Patchset(
        id="cover@msgid",
        title="[PATCH 0/2] mm: sample series",
        author_name="John Doe",
        author_email="john@example.com",
        date="2026-08-30T10:00:00Z",
        is_cover_letter=True,
        total_patches=2,
        patches=[patch1]
    )
    assert patchset.id == "cover@msgid"
    assert patchset.total_patches == 2
    assert len(patchset.patches) == 1
    assert patchset.patches[0].index == 1
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/test_models.py`
Expected: FAIL (ModuleNotFoundError: No module named 'kp.models')

- [ ] **Step 3: 编写数据模型实现**

```python
# src/kp/models.py
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field

class RawMessage(BaseModel):
    """直接映射 lei q 返回的单条邮件元数据"""
    blob: Optional[str] = None
    m: str                                                  # Message-ID
    s: str                                                  # Subject
    f: List[List[Optional[str]]] = Field(default_factory=list) # From: [["Name", "email"]]
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
    is_cover_letter: bool = False                           # 是否含有 0/N Cover Letter
    total_patches: int = 1                                  # 系列包含的 patch 总数
    patches: List[PatchItem] = Field(default_factory=list)  # 包含的所有 patch 列表 (按 index 排序)

class RunManifest(BaseModel):
    """运行会话摘要清单"""
    run_id: str                                             # 会话 ID (如 20260830_175000_3a8f1b)
    timestamp: str                                          # 执行时间戳 (ISO)
    query: str                                              # 执行的查询语句
    total_raw_messages: int                                 # 原始消息数
    total_patchsets: int                                    # 聚合后的补丁集数
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/test_models.py`
Expected: PASS

- [ ] **Step 5: Git 提交**

```bash
git add src/kp/models.py tests/test_models.py
git commit -m "feat: add pydantic data models for raw messages and patchsets"
```

---

### Task 3: 安全校验与 Lore/lei 适配器 (Safety Validator & Lore Client)

**Files:**
- Create: `src/kp/adapters/__init__.py`
- Create: `src/kp/adapters/lore.py`
- Test: `tests/test_safety.py`
- Test: `tests/test_lore.py`

**Interfaces:**
- Consumes: `AppConfig`, `RawMessage`, `subprocess`.
- Produces:
  - `class SafetyValidationError(Exception)`
  - `class LoreExecutionError(Exception)`
  - `class SafetyValidator`: `def validate_query(query: str, config: SafetyConfig) -> None`
  - `class LoreClient`: `def query(query_str: str) -> List[RawMessage]`

- [ ] **Step 1: 编写 SafetyValidator 测试**

```python
# tests/test_safety.py
import pytest
from datetime import datetime, timezone, timedelta
from kp.config import SafetyConfig
from kp.adapters.lore import SafetyValidator, SafetyValidationError

def test_missing_time_filter_raises_error():
    config = SafetyConfig(max_time_span_minutes=180, require_time_filter=True)
    validator = SafetyValidator(config)
    with pytest.raises(SafetyValidationError, match="必须包含.*d:"):
        validator.validate_query("l:linux-mm.kvack.org AND NOT s:Re")

def test_valid_relative_time_filter():
    config = SafetyConfig(max_time_span_minutes=180, require_time_filter=True)
    validator = SafetyValidator(config)
    # 2 hours <= 3 hours (180m) -> ok
    validator.validate_query("l:linux-mm.kvack.org AND NOT s:Re AND d:2.hours.ago..")
    # 90 minutes <= 180m -> ok
    validator.validate_query("l:linux-mm.kvack.org AND d:90.minutes.ago..")

def test_exceeded_relative_time_filter():
    config = SafetyConfig(max_time_span_minutes=180, require_time_filter=True)
    validator = SafetyValidator(config)
    with pytest.raises(SafetyValidationError, match="超过.*限制"):
        validator.validate_query("l:linux-mm.kvack.org AND d:4.hours.ago..")
    with pytest.raises(SafetyValidationError, match="超过.*限制"):
        validator.validate_query("l:linux-mm.kvack.org AND d:200.minutes.ago..")
    with pytest.raises(SafetyValidationError, match="禁止使用大粒度"):
        validator.validate_query("l:linux-mm.kvack.org AND d:1.day.ago..")

def test_absolute_time_filter():
    config = SafetyConfig(max_time_span_minutes=180, require_time_filter=True)
    validator = SafetyValidator(config)
    # 1 hour ago UTC -> valid
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    validator.validate_query(f"l:linux-mm.kvack.org AND d:{recent}..")

    # 5 hours ago UTC -> invalid
    old = (datetime.now(timezone.utc) - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with pytest.raises(SafetyValidationError, match="超过.*限制"):
        validator.validate_query(f"l:linux-mm.kvack.org AND d:{old}..")
```

- [ ] **Step 2: 编写 LoreClient 测试**

```python
# tests/test_lore.py
import pytest
from unittest.mock import patch, MagicMock
import subprocess
from kp.config import LoreConfig, SafetyConfig
from kp.adapters.lore import LoreClient, LoreExecutionError

def test_lore_client_success():
    fake_json = '[{"m":"m1@test","s":"[PATCH] test","f":[["A","a@b.com"]],"dt":"2026-08-30T10:00:00Z"}]'
    lore_config = LoreConfig(inbox_url="https://lore.kernel.org/all/", timeout_seconds=10)
    safety_config = SafetyConfig(max_time_span_minutes=180, require_time_filter=True)
    client = LoreClient(lore_config, safety_config)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_json, stderr="")
        results = client.query("l:linux-mm.kvack.org AND d:2.hours.ago..")
        assert len(results) == 1
        assert results[0].m == "m1@test"
        assert results[0].s == "[PATCH] test"

def test_lore_client_lei_not_found():
    lore_config = LoreConfig()
    safety_config = SafetyConfig()
    client = LoreClient(lore_config, safety_config)

    with patch("shutil.which", return_value=None):
        with pytest.raises(LoreExecutionError, match="未找到 lei 工具"):
            client.query("l:linux-mm.kvack.org AND d:2.hours.ago..")
```

- [ ] **Step 3: 运行测试验证失败**

Run: `uv run pytest tests/test_safety.py tests/test_lore.py`
Expected: FAIL (ModuleNotFoundError: No module named 'kp.adapters')

- [ ] **Step 4: 编写 LoreClient 与 SafetyValidator 实现**

```python
# src/kp/adapters/__init__.py
from .lore import LoreClient, SafetyValidator, SafetyValidationError, LoreExecutionError

__all__ = ["LoreClient", "SafetyValidator", "SafetyValidationError", "LoreExecutionError"]
```

```python
# src/kp/adapters/lore.py
from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from typing import List, Optional
from kp.config import LoreConfig, SafetyConfig
from kp.models import RawMessage

class SafetyValidationError(Exception):
    """查询安全校验失败"""
    pass

class LoreExecutionError(Exception):
    """调用 lei 执行失败"""
    pass

class SafetyValidator:
    """校验 lei query 是否符合安全时间范围限制"""

    def __init__(self, config: SafetyConfig):
        self.config = config

    def validate_query(self, query: str) -> None:
        # 提取 d: 条件
        # 匹配形如 d:2.hours.ago.. 或 d:2026-08-30T10:00:00Z.. 或 d:90.minutes.ago..
        match = re.search(r"\bd:([^\s\"]+)", query)
        if not match:
            if self.config.require_time_filter:
                raise SafetyValidationError(
                    "安全限制：Query 中必须包含 d: 时间范围过滤（例如 d:2.hours.ago..）"
                )
            return

        date_expr = match.group(1).rstrip(".")
        self._validate_date_expr(date_expr)

    def _validate_date_expr(self, expr: str) -> None:
        # 1. 相对时间表达解析 (e.g. 2.hours.ago, 90.minutes.ago, 1.day.ago)
        rel_match = re.match(r"^(\d+)\.(minutes?|hours?|days?|weeks?|months?|years?)\.ago$", expr, re.IGNORECASE)
        if rel_match:
            val = int(rel_match.group(1))
            unit = rel_match.group(2).lower()
            if unit.startswith("minute"):
                span_minutes = val
            elif unit.startswith("hour"):
                span_minutes = val * 60
            else:
                raise SafetyValidationError(
                    f"安全限制：禁止使用大粒度时间单位 '{unit}'，测试模式下最多允许 {self.config.max_time_span_minutes} 分钟 (如 d:2.hours.ago..)"
                )

            if span_minutes > self.config.max_time_span_minutes:
                raise SafetyValidationError(
                    f"安全限制：查询时间跨度 {span_minutes} 分钟超过最大允许限制 {self.config.max_time_span_minutes} 分钟"
                )
            return

        # 2. 绝对时间解析 (ISO / RFC3339, e.g. 2026-08-30T10:00:00Z)
        try:
            # 兼容处理带 Z 或不带时区的字符串
            iso_str = expr.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            delta_seconds = (now - dt).total_seconds()
            if delta_seconds < 0:
                # 未来的时间，合法
                return
            delta_minutes = delta_seconds / 60.0
            if delta_minutes > (self.config.max_time_span_minutes + 5): # 容差 5 分钟
                raise SafetyValidationError(
                    f"安全限制：绝对时间 {expr} 距离当前约 {int(delta_minutes)} 分钟，超过最大允许限制 {self.config.max_time_span_minutes} 分钟"
                )
        except ValueError:
            # 无法解析的特殊 approxidate 格式，若不是明显合法则进行提示
            raise SafetyValidationError(
                f"安全限制：无法识别的时间格式 '{expr}'，请使用 d:X.hours.ago.. 或标准 ISO 时间"
            )

class LoreClient:
    """与 lei / lore 交互的客户端"""

    def __init__(self, lore_config: LoreConfig, safety_config: SafetyConfig):
        self.lore_config = lore_config
        self.validator = SafetyValidator(safety_config)

    def query(self, query_str: str) -> List[RawMessage]:
        self.validator.validate_query(query_str)

        if not shutil.which("lei"):
            raise LoreExecutionError("系统环境中未找到 lei 工具，请确保已正确安装 public-inbox/lei")

        cmd = [
            "lei",
            "q",
            "-t",
            "-I",
            self.lore_config.inbox_url,
            query_str,
            "-f",
            "json",
        ]

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.lore_config.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise LoreExecutionError(f"lei 查询超时 ({self.lore_config.timeout_seconds}s)") from e
        except Exception as e:
            raise LoreExecutionError(f"执行 lei 命令失败: {e}") from e

        if res.returncode != 0:
            raise LoreExecutionError(f"lei 查询失败 (code {res.returncode}): {res.stderr.strip()}")

        stdout = res.stdout.strip()
        if not stdout:
            return []

        try:
            data = json.loads(stdout)
            if not isinstance(data, list):
                return []
            # 过滤掉尾部可能的 null 项
            valid_items = [item for item in data if isinstance(item, dict) and "m" in item and "s" in item]
            return [RawMessage.model_validate(item) for item in valid_items]
        except Exception as e:
            raise LoreExecutionError(f"解析 lei 返回的 JSON 失败: {e}") from e
```

- [ ] **Step 5: 运行测试验证通过**

Run: `uv run pytest tests/test_safety.py tests/test_lore.py`
Expected: PASS

- [ ] **Step 6: Git 提交**

```bash
git add src/kp/adapters/ tests/test_safety.py tests/test_lore.py
git commit -m "feat: add safety query validator and lore lei adapter"
```

---

### Task 4: Patchset 聚合与清洗算法 (Aggregator)

**Files:**
- Create: `src/kp/core/__init__.py`
- Create: `src/kp/core/aggregator.py`
- Test: `tests/test_aggregator.py`

**Interfaces:**
- Consumes: `RawMessage`, `PatchItem`, `Patchset`.
- Produces:
  - `class PatchsetAggregator`:
    - `def aggregate(messages: List[RawMessage]) -> List[Patchset]`
    - `def parse_subject(subject: str) -> Tuple[bool, int, int, str]` (is_cover, index, total, title)

- [ ] **Step 1: 编写 Aggregator 失败测试**

```python
# tests/test_aggregator.py
import pytest
from kp.models import RawMessage
from kp.core.aggregator import PatchsetAggregator

def test_parse_subject_patterns():
    aggregator = PatchsetAggregator()
    # Cover letter
    is_cov, idx, tot = aggregator.parse_subject_meta("[PATCH 0/4] mm/damon: improve monitoring")
    assert is_cov is True
    assert idx == 0
    assert tot == 4

    # Subpatch
    is_cov, idx, tot = aggregator.parse_subject_meta("[PATCH v2 3/4] mm/damon: add tests")
    assert is_cov is False
    assert idx == 3
    assert tot == 4

    # Standalone patch
    is_cov, idx, tot = aggregator.parse_subject_meta("[PATCH] mm: fix leak")
    assert is_cov is False
    assert idx == 1
    assert tot == 1

def test_aggregate_series_with_cover_letter():
    aggregator = PatchsetAggregator()
    raw_msgs = [
        RawMessage(
            m="cover@1",
            s="[PATCH 0/2] mm/test: series cover",
            f=[["Dev", "dev@kernel.org"]],
            dt="2026-08-30T10:00:00Z",
            refs=[]
        ),
        RawMessage(
            m="patch1@1",
            s="[PATCH 1/2] mm/test: part 1",
            f=[["Dev", "dev@kernel.org"]],
            dt="2026-08-30T10:01:00Z",
            refs=["cover@1"]
        ),
        RawMessage(
            m="patch2@1",
            s="[PATCH 2/2] mm/test: part 2",
            f=[["Dev", "dev@kernel.org"]],
            dt="2026-08-30T10:02:00Z",
            refs=["cover@1"]
        ),
    ]

    patchsets = aggregator.aggregate(raw_msgs)
    assert len(patchsets) == 1
    ps = patchsets[0]
    assert ps.id == "cover@1"
    assert ps.title == "[PATCH 0/2] mm/test: series cover"
    assert ps.is_cover_letter is True
    assert ps.total_patches == 2
    assert len(ps.patches) == 2
    assert ps.patches[0].index == 1
    assert ps.patches[0].title == "[PATCH 1/2] mm/test: part 1"
    assert ps.patches[1].index == 2
    assert ps.patches[1].title == "[PATCH 2/2] mm/test: part 2"

def test_aggregate_standalone_patches():
    aggregator = PatchsetAggregator()
    raw_msgs = [
        RawMessage(
            m="standalone@1",
            s="[PATCH] mm/slab: fix typo",
            f=[["Alice", "alice@kernel.org"]],
            dt="2026-08-30T11:00:00Z",
            refs=[]
        )
    ]
    patchsets = aggregator.aggregate(raw_msgs)
    assert len(patchsets) == 1
    ps = patchsets[0]
    assert ps.id == "standalone@1"
    assert ps.title == "[PATCH] mm/slab: fix typo"
    assert ps.is_cover_letter is False
    assert ps.total_patches == 1
    assert len(ps.patches) == 1
    assert ps.patches[0].title == "[PATCH] mm/slab: fix typo"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/test_aggregator.py`
Expected: FAIL (ModuleNotFoundError: No module named 'kp.core')

- [ ] **Step 3: 编写 PatchsetAggregator 实现**

```python
# src/kp/core/__init__.py
from .aggregator import PatchsetAggregator
from .prompt import PromptBuilder
from .pipeline import FetchPipeline

__all__ = ["PatchsetAggregator", "PromptBuilder", "FetchPipeline"]
```

```python
# src/kp/core/aggregator.py
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple, Set
from kp.models import RawMessage, PatchItem, Patchset

class PatchsetAggregator:
    """将 RawMessage 列表清洗并聚合为 Patchset 列表"""

    SUBJECT_RE = re.compile(
        r"\[(?:[^\]]*\b)?PATCH(?:\s+v\d+)?(?:\s+(\d+)/(\d+))?\]\s*(.*)",
        re.IGNORECASE
    )

    def parse_subject_meta(self, subject: str) -> Tuple[bool, int, int]:
        """解析邮件主题，返回 (is_cover_letter, index, total)"""
        match = self.SUBJECT_RE.search(subject)
        if match:
            idx_str, tot_str, _ = match.groups()
            if idx_str is not None and tot_str is not None:
                idx = int(idx_str)
                tot = int(tot_str)
                is_cover = (idx == 0)
                return (is_cover, idx, tot)
            else:
                return (False, 1, 1)

        # 非标准 patch 标签（如仅有 RFC 或普通提交），默认当做独立 patch
        return (False, 1, 1)

    def aggregate(self, messages: List[RawMessage]) -> List[Patchset]:
        """按线程和引用关系聚合并生成 Patchset 列表"""
        if not messages:
            return []

        # 1. 建立 message_id -> RawMessage 索引与 root 聚类映射
        msg_map: Dict[str, RawMessage] = {m.m: m for m in messages if m.m}
        
        # cluster_root_id -> list of raw messages
        clusters: Dict[str, List[RawMessage]] = {}
        # msg_id -> cluster_root_id
        assigned_cluster: Dict[str, str] = {}

        for msg in messages:
            # 确定该消息归属的 root id
            is_cov, idx, tot = self.parse_subject_meta(msg.s)

            root_candidate: Optional[str] = None
            if is_cov:
                root_candidate = msg.m
            elif msg.refs:
                # 检查 refs 中是否有任何已被赋予 cluster 的 root 或 message
                for ref in msg.refs:
                    if ref in assigned_cluster:
                        root_candidate = assigned_cluster[ref]
                        break
                    elif ref in msg_map:
                        root_candidate = ref
                        break
                if not root_candidate and msg.refs:
                    root_candidate = msg.refs[0]

            if not root_candidate:
                root_candidate = msg.m

            if root_candidate not in clusters:
                clusters[root_candidate] = []

            clusters[root_candidate].append(msg)
            assigned_cluster[msg.m] = root_candidate
            for ref in (msg.refs or []):
                if ref not in assigned_cluster:
                    assigned_cluster[ref] = root_candidate

        # 2. 从每个 cluster 构造 Patchset 对象
        result: List[Patchset] = []
        for root_id, cluster_msgs in clusters.items():
            cover_msg: Optional[RawMessage] = None
            patches: List[PatchItem] = []
            author_name = "Unknown"
            author_email = "unknown@kernel.org"
            date = None
            max_total = 1

            for msg in cluster_msgs:
                is_cov, idx, tot = self.parse_subject_meta(msg.s)
                if tot > max_total:
                    max_total = tot

                if is_cov:
                    cover_msg = msg
                else:
                    patches.append(
                        PatchItem(
                            index=idx,
                            total=tot,
                            title=msg.s,
                            message_id=msg.m,
                            date=msg.dt
                        )
                    )

            # 确定代表性 ID 和 Title
            if cover_msg:
                rep_id = cover_msg.m
                title = cover_msg.s
                if cover_msg.f and len(cover_msg.f) > 0:
                    author_name = cover_msg.f[0][0] or author_name
                    author_email = cover_msg.f[0][1] or author_email
                date = cover_msg.dt
                is_cover = True
            else:
                # 按 index 排序
                patches.sort(key=lambda p: p.index)
                if patches:
                    rep_id = patches[0].message_id
                    title = patches[0].title
                    first_msg = msg_map.get(patches[0].message_id)
                    if first_msg and first_msg.f and len(first_msg.f) > 0:
                        author_name = first_msg.f[0][0] or author_name
                        author_email = first_msg.f[0][1] or author_email
                    date = patches[0].date
                else:
                    rep_id = root_id
                    title = "Patchset"
                is_cover = False

            patches.sort(key=lambda p: p.index)
            total_patches = max(max_total, len(patches))

            ps = Patchset(
                id=rep_id,
                title=title,
                author_name=author_name,
                author_email=author_email,
                date=date,
                is_cover_letter=is_cover,
                total_patches=total_patches,
                patches=patches
            )
            result.append(ps)

        # 3. 按提交日期降序排列
        result.sort(key=lambda ps: ps.date or "", reverse=True)
        return result
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/test_aggregator.py`
Expected: PASS

- [ ] **Step 5: Git 提交**

```bash
git add src/kp/core/aggregator.py src/kp/core/__init__.py tests/test_aggregator.py
git commit -m "feat: add patchset aggregation and subject parsing algorithms"
```

---

### Task 5: 存储持久化与提示词生成器 (Session Storage & Prompt Builder)

**Files:**
- Create: `src/kp/storage/__init__.py`
- Create: `src/kp/storage/session.py`
- Create: `src/kp/core/prompt.py`
- Test: `tests/test_storage.py`
- Test: `tests/test_prompt.py`

**Interfaces:**
- Consumes: `AppConfig`, `RawMessage`, `Patchset`, `RunManifest`, `Path`.
- Produces:
  - `class SessionManager`:
    - `def create_session_dir() -> Tuple[str, Path]`
    - `def save_run(run_dir: Path, manifest: RunManifest, raw_msgs: List[RawMessage], patchsets: List[Patchset], prompt_content: str) -> None`
  - `class PromptBuilder`:
    - `def build_prompt(patchsets_json_path: Path) -> str`

- [ ] **Step 1: 编写 Storage 与 Prompt 测试**

```python
# tests/test_prompt.py
from pathlib import Path
from kp.core.prompt import PromptBuilder

def test_prompt_builder_contains_absolute_path():
    builder = PromptBuilder()
    fake_path = Path("/code/agent/kp/data/runs/run1/patchsets.json")
    prompt = builder.build_prompt(fake_path)
    assert str(fake_path.resolve()) in prompt
    assert "Linux 内核补丁评审" in prompt
    assert "期望输出格式" in prompt
```

```python
# tests/test_storage.py
from pathlib import Path
import json
from kp.config import StorageConfig
from kp.storage.session import SessionManager
from kp.models import RunManifest, RawMessage, Patchset, PatchItem

def test_session_manager_save_and_structure(tmp_path: Path):
    config = StorageConfig(data_dir=str(tmp_path))
    mgr = SessionManager(config)
    run_id, run_dir = mgr.create_session_dir()

    manifest = RunManifest(
        run_id=run_id,
        timestamp="2026-08-30T10:00:00Z",
        query="l:linux-mm",
        total_raw_messages=1,
        total_patchsets=1
    )
    raw_msgs = [RawMessage(m="m1", s="[PATCH] test", f=[["Author", "a@b.com"]])]
    patchsets = [Patchset(id="m1", title="[PATCH] test", author_name="Author", author_email="a@b.com", total_patches=1, patches=[])]
    prompt_content = "# Test Prompt"

    mgr.save_run(run_dir, manifest, raw_msgs, patchsets, prompt_content)

    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "raw_metadata.json").exists()
    assert (run_dir / "patchsets.json").exists()
    assert (run_dir / "prompt.md").exists()

    with open(run_dir / "patchsets.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        assert len(data) == 1
        assert data[0]["id"] == "m1"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/test_prompt.py tests/test_storage.py`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: 编写 PromptBuilder 与 SessionManager 实现**

```python
# src/kp/core/prompt.py
from __future__ import annotations

from pathlib import Path

class PromptBuilder:
    """生成 AI 筛选补丁集的提示词"""

    TEMPLATE = """# Linux 内核补丁评审与筛选任务

你是一位资深的 Linux 内核专家与代码审查助手。请对本次抓取到的 Linux 内核补丁集进行价值评估与优先级打分，筛选出值得进一步深入分析的高价值 Patchset。

## 数据源
已清洗的补丁集元数据文件绝对路径为：
`{patchsets_json_abs_path}`

请读取上述文件中的 Patchset 列表（包含 ID、标题、作者、时间、子 patch 列表）。

## 评估维度与准则
1. **子系统重要性与影响面**：核心机制（如 MM、调度器、VFS、锁等）改动 > 边缘驱动的小修补；
2. **变更性质**：重要性能优化、核心架构重构、修复关键内存损坏/死锁/安全漏洞的补丁优先级更高；
3. **设计讨论价值**：重要 RFC、跨子系统大型重构系列优先关注。

## 期望输出格式
请以 JSON 格式输出打分与筛选结果（供后续阶段二直接消费）：
```json
[
  {{
    "id": "<patchset_id>",
    "title": "<patchset_title>",
    "score": 85,
    "recommend": true,
    "reason": "简要说明推荐/分析理由"
  }}
]
```
"""

    def build_prompt(self, patchsets_json_path: Path) -> str:
        abs_path = str(patchsets_json_path.resolve())
        return self.TEMPLATE.format(patchsets_json_abs_path=abs_path)
```

```python
# src/kp/storage/__init__.py
from .session import SessionManager

__all__ = ["SessionManager"]
```

```python
# src/kp/storage/session.py
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple
from kp.config import StorageConfig
from kp.models import RawMessage, Patchset, RunManifest

class SessionManager:
    """管理运行会话目录与数据持久化"""

    def __init__(self, config: StorageConfig):
        self.config = config

    def create_session_dir(self) -> Tuple[str, Path]:
        base_dir = Path(self.config.data_dir)
        base_dir.mkdir(parents=True, exist_ok=True)

        now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        rand_str = uuid.uuid4().hex[:6]
        run_id = f"{now_str}_{rand_str}"

        run_dir = base_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_id, run_dir

    def save_run(
        self,
        run_dir: Path,
        manifest: RunManifest,
        raw_msgs: List[RawMessage],
        patchsets: List[Patchset],
        prompt_content: str,
    ) -> None:
        # 1. 保存 manifest.json
        manifest_file = run_dir / "manifest.json"
        manifest_file.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

        # 2. 保存 raw_metadata.json
        raw_file = run_dir / "raw_metadata.json"
        raw_list = [m.model_dump() for m in raw_msgs]
        raw_file.write_text(json.dumps(raw_list, indent=2, ensure_ascii=False), encoding="utf-8")

        # 3. 保存 patchsets.json
        patchsets_file = run_dir / "patchsets.json"
        patchsets_list = [ps.model_dump() for ps in patchsets]
        patchsets_file.write_text(json.dumps(patchsets_list, indent=2, ensure_ascii=False), encoding="utf-8")

        # 4. 保存 prompt.md
        prompt_file = run_dir / "prompt.md"
        prompt_file.write_text(prompt_content, encoding="utf-8")
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/test_prompt.py tests/test_storage.py`
Expected: PASS

- [ ] **Step 5: Git 提交**

```bash
git add src/kp/storage/ src/kp/core/prompt.py tests/test_prompt.py tests/test_storage.py
git commit -m "feat: add session manager and prompt builder"
```

---

### Task 6: 阶段一管道编排 (FetchPipeline)

**Files:**
- Create: `src/kp/core/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `AppConfig`, `LoreClient`, `PatchsetAggregator`, `SessionManager`, `PromptBuilder`.
- Produces:
  - `class PipelineResult(BaseModel)`: `run_id: str`, `run_dir: Path`, `raw_count: int`, `patchset_count: int`, `prompt_path: Path`
  - `class FetchPipeline`:
    - `def run(query: str) -> PipelineResult`

- [ ] **Step 1: 编写 FetchPipeline 测试**

```python
# tests/test_pipeline.py
from pathlib import Path
from unittest.mock import patch, MagicMock
from kp.config import AppConfig
from kp.models import RawMessage
from kp.core.pipeline import FetchPipeline

def test_fetch_pipeline_run(tmp_path: Path):
    config = AppConfig()
    config.storage.data_dir = str(tmp_path)
    pipeline = FetchPipeline(config)

    fake_raw = [
        RawMessage(
            m="m1@test",
            s="[PATCH] mm: sample",
            f=[["Author", "a@b.com"]],
            dt="2026-08-30T10:00:00Z"
        )
    ]

    with patch.object(pipeline.lore_client, "query", return_value=fake_raw):
        result = pipeline.run("l:linux-mm AND d:1.hours.ago..")
        assert result.raw_count == 1
        assert result.patchset_count == 1
        assert result.run_dir.exists()
        assert (result.run_dir / "patchsets.json").exists()
        assert (result.run_dir / "prompt.md").exists()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/test_pipeline.py`
Expected: FAIL (ImportError)

- [ ] **Step 3: 编写 FetchPipeline 实现**

```python
# src/kp/core/pipeline.py
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel
from kp.config import AppConfig
from kp.adapters.lore import LoreClient
from kp.core.aggregator import PatchsetAggregator
from kp.core.prompt import PromptBuilder
from kp.storage.session import SessionManager
from kp.models import RunManifest

class PipelineResult(BaseModel):
    run_id: str
    run_dir: Path
    raw_count: int
    patchset_count: int
    prompt_path: Path

class FetchPipeline:
    """阶段一核心业务流水线：Query -> Lore -> Aggregator -> SessionStorage -> Prompt"""

    def __init__(self, config: AppConfig):
        self.config = config
        self.lore_client = LoreClient(config.lore, config.safety)
        self.aggregator = PatchsetAggregator()
        self.session_manager = SessionManager(config.storage)
        self.prompt_builder = PromptBuilder()

    def run(self, query: str) -> PipelineResult:
        # 1. 创建 Run 会话目录
        run_id, run_dir = self.session_manager.create_session_dir()
        now_iso = datetime.now(timezone.utc).isoformat()

        # 2. 调用 Lore 抓取原始元数据
        raw_msgs = self.lore_client.query(query)

        # 3. 清洗与聚合为 Patchset 列表
        patchsets = self.aggregator.aggregate(raw_msgs)

        # 4. 生成提示词内容（引用 patchsets.json 绝对路径）
        patchsets_file = run_dir / "patchsets.json"
        prompt_content = self.prompt_builder.build_prompt(patchsets_file)

        # 5. 持久化所有成果物
        manifest = RunManifest(
            run_id=run_id,
            timestamp=now_iso,
            query=query,
            total_raw_messages=len(raw_msgs),
            total_patchsets=len(patchsets),
        )
        self.session_manager.save_run(
            run_dir=run_dir,
            manifest=manifest,
            raw_msgs=raw_msgs,
            patchsets=patchsets,
            prompt_content=prompt_content,
        )

        return PipelineResult(
            run_id=run_id,
            run_dir=run_dir,
            raw_count=len(raw_msgs),
            patchset_count=len(patchsets),
            prompt_path=run_dir / "prompt.md",
        )
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/test_pipeline.py`
Expected: PASS

- [ ] **Step 5: Git 提交**

```bash
git add src/kp/core/pipeline.py tests/test_pipeline.py
git commit -m "feat: add fetch pipeline orchestrator"
```

---

### Task 7: CLI 命令接口与端到端集成验证 (CLI & Integration)

**Files:**
- Create: `src/kp/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `click`, `FetchPipeline`, `load_config`, `SafetyValidationError`, `LoreExecutionError`.
- Produces: CLI command entrypoint `kp` with `kp fetch --query "..."`.

- [ ] **Step 1: 编写 CLI 测试**

```python
# tests/test_cli.py
from click.testing import CliRunner
from unittest.mock import patch
from pathlib import Path
from kp.cli import main
from kp.models import RawMessage

def test_cli_fetch_success(tmp_path: Path):
    runner = CliRunner()
    fake_raw = [
        RawMessage(
            m="m1@test",
            s="[PATCH] mm: sample fix",
            f=[["Author", "a@b.com"]],
            dt="2026-08-30T10:00:00Z"
        )
    ]
    with patch("kp.adapters.lore.LoreClient.query", return_value=fake_raw):
        result = runner.invoke(main, ["fetch", "--query", "l:linux-mm AND d:2.hours.ago.."])
        assert result.exit_code == 0
        assert "抓取完成" in result.output
        assert "prompt.md" in result.output

def test_cli_fetch_safety_violation():
    runner = CliRunner()
    result = runner.invoke(main, ["fetch", "--query", "l:linux-mm AND d:10.hours.ago.."])
    assert result.exit_code != 0
    assert "安全限制" in result.output
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/test_cli.py`
Expected: FAIL (ModuleNotFoundError: No module named 'kp.cli')

- [ ] **Step 3: 编写 CLI 实现**

```python
# src/kp/cli.py
from __future__ import annotations

import sys
from pathlib import Path
import click
from kp.config import load_config
from kp.adapters.lore import SafetyValidationError, LoreExecutionError
from kp.core.pipeline import FetchPipeline

@click.group()
@click.option("-c", "--config", "config_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="指定配置文件路径")
@click.pass_context
def main(ctx: click.Context, config_path: Path | None) -> None:
    """Linux Kernel Patch Fetcher & AI Analyzer (kp)"""
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(config_path)

@main.command(name="fetch")
@click.option(
    "-q",
    "--query",
    required=True,
    help='lei 查询语句 (与 lei q 一致，如 "l:linux-mm.kvack.org AND NOT s:Re AND d:2.hours.ago..")',
)
@click.pass_context
def fetch_cmd(ctx: click.Context, query: str) -> None:
    """阶段一：抓取补丁元数据、清洗聚合并生成 AI 提示词"""
    app_config = ctx.obj["config"]
    pipeline = FetchPipeline(app_config)

    try:
        click.echo(f"[*] 执行查询: {query}")
        result = pipeline.run(query)
        click.secho(f"[✓] 抓取完成！", fg="green", bold=True)
        click.echo(f"    - 运行 ID: {result.run_id}")
        click.echo(f"    - 原始邮件数: {result.raw_count}")
        click.echo(f"    - 聚合 Patchset 数: {result.patchset_count}")
        click.echo(f"    - 会话目录: {result.run_dir.resolve()}")
        click.echo(f"    - 提示词文件: {result.prompt_path.resolve()}")
        click.secho(f"\n[提示] 可将 {result.prompt_path.name} 提交给 AI 进行第一轮补丁评审与打分。", fg="cyan")
    except SafetyValidationError as e:
        click.secho(f"[错误] {e}", fg="red", err=True)
        sys.exit(1)
    except LoreExecutionError as e:
        click.secho(f"[错误] {e}", fg="red", err=True)
        sys.exit(1)
    except Exception as e:
        click.secho(f"[异常] 未知错误: {e}", fg="red", err=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行所有单元测试**

Run: `uv run pytest`
Expected: ALL PASS

- [ ] **Step 5: 真实环境端到端验证**

Run: `uv run kp fetch --query "l:linux-mm.kvack.org AND NOT s:Re AND d:15.minutes.ago.."`
Expected: Exit code 0, session directory created with `raw_metadata.json`, `patchsets.json`, `prompt.md`.

- [ ] **Step 6: Git 提交**

```bash
git add src/kp/cli.py tests/test_cli.py
git commit -m "feat: implement CLI interface and complete stage 1 pipeline"
```
