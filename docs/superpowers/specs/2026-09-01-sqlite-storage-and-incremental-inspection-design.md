# 技术设计规范：Linux 内核补丁抓取与 AI 分析工具 (kp) — SQLite 存储与增量巡检

本文档定义 Linux 内核补丁分析工具 `kp` 的 **SQLite 存储架构重构与增量巡检机制**（包括 `kp fetch --since-last` 自动分批次、`kp download` 增量感知与跳过、`kp analyze` 防重与自定义提示词）。

---

## 1. 概述与核心目标

### 1.1 背景与痛点
1. **时间漂移与巡检断档**：原本基于固定相对时间窗口（如 `d:24.hours.ago..`）的巡检方式，在触发间隔 > 24h（如周末放假、定时任务延时）时会出现时间空洞（Gap，遗漏补丁），在触发间隔 < 24h 时会出现重复重叠窗口（造成重复初筛与深度分析，浪费 LLM 算力）。
2. **多 Run 补丁数据孤岛**：原架构下补丁文件与报告分散在各个 `data/runs/<run_id>/` 目录下，缺乏全局统一的生命周期追踪、状态管理与跨会话去重机制。
3. **评分体系粒度过细**：阶段二 AI 初筛评分采用 `0-100` 分制，实际在初筛打分场景下更容易产生边界模糊，需统一收敛至更清晰明确的 `0-10` 整数制。

### 1.2 核心目标
1. **SQLite (WAL 模式) + 年月分层文件系统 混合存储**：
   - 引入 `data/kp.db` 全局数据库，追踪 `query_cursors`（游标）、`runs`（执行会话）与 `patchsets`（补丁集生命周期实体）；
   - 全局资产库升级：补丁集直读文件统一归档至 `data/patchsets/YYYY-MM/<clean_id>/`，深度分析报告统一归档至 `data/reports/YYYY-MM/<clean_id>.md`；
   - `data/runs/<run_id>/` 仅保存单次执行的轻量日志（`manifest.json`、`raw_metadata.json`、`patchsets.json`、`reviews.json`）。
2. **增量巡检与自适应分批 (`kp fetch --since-last`)**：
   - 支持根据 `query_key` 自动检索上一次成功同步的时间戳 `last_sync_time`；
   - 引入 `overlap_grace_minutes`（默认 10 分钟）容差消除邮件投递延迟漏网；
   - 当距离上次同步时间跨度超过 `chunk_hours`（默认 24h）时，在单次命令内部自动拆分为多个时间批次串行抓取，且每批次成功即时推进游标；
   - 引入 `max_catchup_hours`（默认 72h）防失控追溯上限。
3. **智能增量下载 (`kp download`)**：
   - 对比本次抓取的最新邮件时间 `latest_msg_date` 与数据库中的 `downloaded_at`；若 `latest_msg_date <= downloaded_at` 且未指定 `--force`，跳过下载；
   - 若检测到新回复（`latest_msg_date > downloaded_at`），重新下载解包更新 `discussions.md`；
   - 若补丁集已处于 `analyzed` 状态且已有有效报告，更新下载内容但**保持 `status = 'analyzed'` 不降级**，终端明确提示用户已有新讨论，避免 AI 自动化重复消耗算力。
4. **分析防重与自定义提示词 (`kp analyze`)**：
   - 当补丁集已是 `analyzed` 状态且报告文件存在非空时，自动跳过分析（除非 `--force`）；
   - CLI 支持 `-p / --prompt "<text>"` 与 `--prompt-file <path>`，作为附加重点关注指示追加到 Agent 指令末尾。
5. **0-10 分制统一与规范化 ID**：
   - 废除 `sanitized_id`（MD5/截断），统一使用 `clean_id = msgid.replace('/', '%2F')`；
   - 评分标准统一为 `0-10` 整数分制（`models.py`、`references/screening.md`、`--min-score 7`）。

---

## 2. 存储全景结构与 SQLite DDL

### 2.1 目录结构

```text
data/
├── kp.db                      # SQLite 数据库（WAL 模式，ACID & 并发安全）
├── kp.db-wal / kp.db-shm      # WAL 预写日志与共享内存
│
├── patchsets/                 # 【全局补丁集资产库】按 YYYY-MM 归档
│   └── 2026-08/
│       └── 20260830120000.1234-1-user@kernel.org/
│           ├── 00-cover-letter.md  # 直读 Cover Letter
│           ├── discussions.md      # 直读 社区讨论树 (Markdown 引用排版)
│           ├── patches/            # 直读 独立 .patch 文件
│           │   ├── 0001-xxx.patch
│           │   └── 0002-xxx.patch
│           ├── meta.json           # 轻量元数据
│           ├── parsed_series.json  # 结构化数据
│           └── series.mbx          # b4 原始 mbox 缓存
│
├── reports/                   # 【全局分析报告知识库】按 YYYY-MM 归档
│   └── 2026-08/
│       └── 20260830120000.1234-1-user@kernel.org.md
│
└── runs/                      # 【单次执行轻量日志】
    └── <run_id>/
        ├── manifest.json      # 执行摘要
        ├── raw_metadata.json  # 原始查询响应
        ├── patchsets.json     # 本次捕获的补丁列表
        └── reviews.json       # 本次 AI 评审打分结果
```

### 2.2 SQLite 表定义与连接参数

数据库使用 Python 标准库 `sqlite3`，连接时设置：
```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;
```

#### DDL 架构
```sql
-- 1. 增量同步游标表 (追踪每个 query 同步截止时间)
CREATE TABLE IF NOT EXISTS query_cursors (
    query_key TEXT PRIMARY KEY,
    last_sync_time TEXT NOT NULL,      -- ISO8601 UTC 时间字符串 (例如 2026-09-01T02:00:00Z)
    last_run_id TEXT NOT NULL          -- 最近一次同步的 run_id
);

-- 2. 运行会话表 (轻量执行历史)
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    raw_count INTEGER NOT NULL DEFAULT 0,
    patchset_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at DESC);

-- 3. 全局补丁集生命周期表 (核心实体索引)
CREATE TABLE IF NOT EXISTS patchsets (
    id TEXT PRIMARY KEY,                       -- clean MsgID (剔除尖括号且 / 转为 %2F)
    title TEXT NOT NULL,
    author TEXT,                               -- 标准 "Name <email>" 格式
    date TEXT,                                 -- LKML 邮件发送时间 (ISO8601 UTC)
    total_patches INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'fetched' CHECK(status IN ('fetched', 'downloaded', 'analyzed', 'ignored')),
    score INTEGER CHECK(score IS NULL OR (score >= 0 AND score <= 10)),   -- 0-10 整数分制
    recommend INTEGER CHECK(recommend IS NULL OR recommend IN (0, 1)),
    review_reason TEXT,
    downloaded_at TEXT                         -- 最近一次 b4 下载/解包时间 (ISO8601 UTC)
);
CREATE INDEX IF NOT EXISTS idx_patchsets_status ON patchsets(status);
CREATE INDEX IF NOT EXISTS idx_patchsets_date ON patchsets(date DESC);
CREATE INDEX IF NOT EXISTS idx_patchsets_score ON patchsets(score DESC);
```

---

## 3. 路径计算纯函数规范

数据库内不存储硬编码相对/绝对路径，统一由纯函数基于 `data_dir` 动态计算：

```python
from pathlib import Path


def get_clean_id(msgid: str) -> str:
    """去除首尾尖括号，将 / 转义为 %2F"""
    cleaned = msgid.strip().lstrip("<").rstrip(">")
    return cleaned.replace("/", "%2F")


def get_month_bucket(date_str: str | None) -> str:
    """从 ISO 时间字符串中提取 YYYY-MM 年月分层，回退至 'unknown'"""
    if date_str and len(date_str) >= 7:
        # 支持 2026-08-30... 或 20260830...
        if date_str[4] == "-":
            return date_str[:7]
        elif len(date_str) >= 6:
            return f"{date_str[:4]}-{date_str[4:6]}"
    return "unknown"


def get_patchset_dir(
    data_dir: Path, msgid: str, date_str: str | None = None
) -> Path:
    """返回补丁集在全局资产库中的根目录：data/patchsets/YYYY-MM/<clean_id>/"""
    return data_dir / "patchsets" / get_month_bucket(date_str) / get_clean_id(msgid)


def get_report_path(
    data_dir: Path, msgid: str, date_str: str | None = None
) -> Path:
    """返回深度分析报告在全局知识库中的文件路径：data/reports/YYYY-MM/<clean_id>.md"""
    return (
        data_dir
        / "reports"
        / get_month_bucket(date_str)
        / f"{get_clean_id(msgid)}.md"
    )
```

---

## 4. 核心流程与功能设计

### 4.1 `kp fetch --since-last` 与分批抓取 (Auto-chunking)

#### 4.1.1 `query_key` 规范化提取
用户输入查询语句 `query` 时：
1. 剥离可能存在的 `d:` 时间过滤：`pure_query = re.sub(r'\bd:[^\s\"]+', '', query)`；
2. 规范化空白字符：`query_key = re.sub(r'\s+', ' ', pure_query).strip()`。

#### 4.1.2 时间窗口计算与分批切片
1. **起始点确定**：
   - 尝试从 `query_cursors` 查询 `last_sync_time`；
   - 若存在记录：起始时间 $T_{start} = last\_sync\_time - overlap\_grace\_minutes$（默认容差 10 分钟）；
   - 若不存在记录（冷启动）：
     - 若原始 `query` 中显式指定了 `d:START..`，从该 `START` 解析起始时间；
     - 否则回退为 $T_{start} = T_{now} - chunk\_hours$（默认过去 24 小时）。
   - **追溯上限保护**：若 $T_{now} - T_{start} > max\_catchup\_hours$（默认 72 小时），强制将 $T_{start}$ 截断为 $T_{now} - max\_catchup\_hours$，并向用户输出警告提示。
2. **切片计算 (Chunking)**：
   - 若 $T_{now} - T_{start} \le chunk\_hours$，切分为单批次 $[T_{start}, T_{now}]$；
   - 若 $T_{now} - T_{start} > chunk\_hours$，按每步长 $chunk\_hours$ 切分为多个有序批次：
     $[T_0, T_1], [T_1, T_2], \dots, [T_{k-1}, T_{now}]$。
3. **批次执行与游标原子推进**：
   - 串行执行各批次 `lei q` 查询；
   - 每一批次成功抓取并解析后，立即更新 `query_cursors` 表中该 `query_key` 的 `last_sync_time = T_{batch_end}` 与 `last_run_id = current_run_id`，保证单批容灾；
   - 将所有批次拉取到的 `RawMessage` 合并去重，进行并查集聚合，生成本 Run 完整的 `Patchset` 列表。
4. **数据库同步**：
   - 将本次 Run 写入 `runs` 表；
   - 将所有聚合出的补丁集批量 `UPSERT` 到 `patchsets` 表（若已存在则更新 `title`, `author`, `date`, `total_patches`，保持原有的 `status`, `score`, `recommend`, `downloaded_at` 不变）。

---

### 4.2 `kp download` 增量感知与跳过逻辑

1. **评审结果过滤**：
   - 读取 `reviews.json`（评分基于 0-10 分制，过滤条件 `score >= min_score or recommend is True`，`--min-score` 默认值为 `7`）。
2. **针对每个待下载补丁集的增量判定**：
   - 查询 `patchsets` 表获取当前数据库状态（`downloaded_at`, `status`, `date`）；
   - 从本次抓取到的邮件元数据中提取该补丁集下的最大邮件时间戳 `latest_msg_date`；
   - **判定条件**：
     - 若 `downloaded_at` 存在，且 `latest_msg_date <= downloaded_at` 且未指定 `--force`：
       - **跳过下载**，终端输出：`[SKIP] Patchset <clean_id> is up-to-date (downloaded at <downloaded_at>)`。
     - 若 `downloaded_at` 不存在，或 `latest_msg_date > downloaded_at`，或指定了 `--force`：
       - 调用 `b4 mbox` 下载完整邮件线程至全局目录 `data/patchsets/YYYY-MM/<clean_id>/series.mbx`；
       - `MboxParser` 提取拆解并生成直读文件（`00-cover-letter.md`、`discussions.md`、`patches/`、`meta.json`、`parsed_series.json`）；
       - 更新 `downloaded_at = now_utc`；
       - **状态流转规则**：
         - 若原 `status == 'analyzed'` 且 `data/reports/YYYY-MM/<clean_id>.md` 存在非空：
           - **保持 `status = 'analyzed'`**，不将状态回退为 `downloaded`（避免 AI 自动化流程重复分析该补丁）；
           - 终端输出：`[UPDATED] Downloaded new replies for analyzed patchset <clean_id>. Discussions updated at <dir>`；
         - 否则：更新 `status = 'downloaded'`。

---

### 4.3 `kp analyze` 防重与自定义提示词

1. **跳过已分析补丁集**：
   - 遍历目标补丁集时，检查 `patchsets` 表中 `status == 'analyzed'` 且 `data/reports/YYYY-MM/<clean_id>.md` 文件存在且大小 > 0；
   - 若满足且未指定 `--force`：
     - **跳过分析**，终端输出：`[SKIP] Already analyzed: <clean_id>`；
   - 若未满足或指定了 `--force`：执行分析。
2. **自定义提示词追加 (`--prompt` / `--prompt-file`)**：
   - CLI 增加选项：`-p, --prompt TEXT` 与 `--prompt-file PATH`；
   - 适配器在构建 Agent 执行 Prompt 时：
     ```python
     base_prompt = (
         f"使用 skill '{skill_name}' 分析补丁集：{patchset_dir.resolve()}，"
         f"Linux 内核代码路径：{kernel_path}，请将生成的深度分析报告写入文件：{report_output_path.resolve()}"
     )
     if custom_prompt:
         final_prompt = f"{base_prompt}\n\n【用户附加重点关注要求】：\n{custom_prompt}"
     else:
         final_prompt = base_prompt
     ```
3. **分析完成持久化**：
   - 校验生成的 `data/reports/YYYY-MM/<clean_id>.md` 非空；
   - 更新 `patchsets` 表 `status = 'analyzed'`。

---

## 5. 配置体系演进 (`config.toml` & `src/kp/config.py`)

在 `config.toml` 中新增与调整配置项：

```toml
[safety]
max_time_span_hours = 48       # 传统单次查询安全上限
require_time_filter = true     # 是否强制时间过滤
chunk_hours = 24               # --since-last 单批次最大跨度
max_catchup_hours = 72         # --since-last 最大追溯上限
overlap_grace_minutes = 10     # 邮件列表延迟容差

[storage]
data_dir = "data"              # 数据总根目录 (含 kp.db, patchsets/, reports/, runs/)
```

---

## 6. 数据模型演进 (`src/kp/models.py`)

1. **`PatchReview` 评分范围调整**：
   ```python
   class PatchReview(BaseModel):
       id: str
       score: int = Field(ge=0, le=10)  # 0-10 整数分制
       recommend: bool
       reason: str
   ```
2. **`PatchsetRecord` 实体模型（供数据库读写交互）**：
   ```python
   class PatchsetStatus(str, Enum):
       FETCHED = "fetched"
       DOWNLOADED = "downloaded"
       ANALYZED = "analyzed"
       IGNORED = "ignored"


   class PatchsetRecord(BaseModel):
       id: str
       title: str
       author: Optional[str] = None
       date: Optional[str] = None
       total_patches: int = 1
       status: PatchsetStatus = PatchsetStatus.FETCHED
       score: Optional[int] = None
       recommend: Optional[bool] = None
       review_reason: Optional[str] = None
       downloaded_at: Optional[str] = None
   ```

---

## 7. 模块划分与重构计划

| 模块文件 | 调整与职责说明 |
|---|---|
| `src/kp/storage/db.py` (新增) | SQLite 数据库管理类 `DatabaseManager`，实现表初始化、游标读写、Run 与 Patchset UPSERT/查询 |
| `src/kp/storage/paths.py` (新增/调整) | 路径纯函数 `get_clean_id`, `get_month_bucket`, `get_patchset_dir`, `get_report_path` |
| `src/kp/storage/session.py` | 适配全局资产路径与轻量 `runs/<run_id>/` 目录管理 |
| `src/kp/core/pipeline.py` | 实现 `--since-last` 分批抓取编排、容差计算与游标即时持久化 |
| `src/kp/core/download_pipeline.py` | 实现 `downloaded_at` 增量比对、跳过判定与全局 `data/patchsets/` 拆解保存 |
| `src/kp/core/analyze_pipeline.py` | 适配全局报告路径、`analyzed` 跳过判定与 `custom_prompt` 传递 |
| `src/kp/adapters/agent.py` | 适配器支持附加 `custom_prompt` 合成 |
| `src/kp/cli.py` | CLI 命令新增 `--since-last`、`--prompt` / `--prompt-file`、`--force`，`--min-score` 默认改为 7 |
| `.agents/skills/kernel-patch-analyzer/references/screening.md` | 打分表更新为 0-10 分制 |

---

## 8. 测试与质量保证

1. **测试隔离**：统一在 `tests/conftest.py` 中重定向测试用 `data_dir` 到临时目录（如 `/tmp/kp_pytest_data_<uuid>`），严禁污染生产 `data/` 目录；
2. **测试用例覆盖**：
   - `test_db.py`：验证 SQLite 初始化、WAL 模式、游标原子更新、Patchset UPSERT；
   - `test_paths.py`：验证 `clean_id`（`/` 转 `%2F`）、年月分层、路径计算；
   - `test_fetch_since_last.py`：测试游标冷启动、多批次切分、单批容灾推进、72h 上限截断；
   - `test_download_incremental.py`：测试无新邮件跳过、有新邮件重新下载、已分析补丁更新不降级状态；
   - `test_analyze_incremental.py`：测试已分析跳过、`--force` 覆盖分析、`--prompt` 附加提示词正确传递。
