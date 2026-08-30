# 技术设计规范：Linux 内核补丁抓取与 AI 分析工具 (kp) - 阶段二

## 1. 概述与目标

阶段二聚焦于 **AI 评审结果解析、完整 Patchset 拉取、Mbox 结构化清洗（含树形讨论保留）与阶段三上下文准备**。
系统不直接调用外部商业 AI API，而是通过结构化文件与 CLI 命令协同，支撑用户与 AI Agent 的交互工作流。

### 核心目标
1. **AI 评审结果接入与筛选**：解析标准 JSON 格式的 Patchset 评分与推荐列表，根据阈值或推荐标记筛选高价值补丁集。
2. **底层 Patchset 下载**：通过 `B4Client` 适配器调用系统 `b4` 工具（`b4 mbox`），安全稳定地拉取完整邮件线程。
3. **Mbox 结构化解析与清洗**：
   - 提取 Cover Letter、单个 Patch 的 Commit Message、Trailers、Diffstat 与 Unified Diff。
   - 提取 Maintainer / Reviewer 的审阅评论并重构为**嵌套树形回复结构**（Thread Tree）。
   - 输出结构化 `parsed_series.json`，供 AI Agent 直接消费。
4. **阶段三接口预留**：生成 `stage3_prompt.md` 提示词，引用各解析后的补丁集绝对路径。
5. **CLI 扩展**：提供 `kp download` 组合命令，支持按 ID 下载、按评审结果批量下载及标准输入管道导入。

---

## 2. 系统架构与模块划分

```
┌──────────────────────────────────────────────────────────┐
│                      CLI 表示层                          │
│               src/kp/cli.py (Click)                      │
│                Subcommand: `kp download`                 │
└────────────────────────────┬─────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────┐
│                     应用编排层                           │
│           src/kp/core/download_pipeline.py               │
│                   DownloadPipeline                       │
│    (Parse Reviews -> Fetch Mbox -> Parse -> Persist)     │
└──────┬─────────────────────┬─────────────────────┬───────┘
       │                     │                     │
┌──────▼─────┐ ┌─────────────▼─────────────┐ ┌─────▼───────┐
│ 配置管理层 │ │        领域核心层         │ │外部适配器层│
│src/kp/     │ │      src/kp/core/         │ │src/kp/     │
│config.py   │ │  - parser.py (Mbox解析器) │ │- b4.py     │
│            │ │  - stage3_prompt.py       │ │            │
└────────────┘ └─────────────┬─────────────┘ └─────────────┘
                             │
┌────────────────────────────▼─────────────────────────────┐
│                       存储持久化层                       │
│                 src/kp/storage/session.py                │
│             data/runs/<run_id>/patchsets/...             │
└──────────────────────────────────────────────────────────┘
```

---

## 3. 数据模型定义 (`src/kp/models.py`)

阶段二在阶段一模型基础上扩充以下核心数据模型：

```python
from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field

class PatchReview(BaseModel):
    """AI 打分与评审结果项"""
    id: str                                                 # 补丁集代表性 Message-ID
    title: Optional[str] = None                             # 补丁集标题
    score: int = Field(ge=0, le=100)                        # 价值评分 (0-100)
    recommend: bool                                         # 是否推荐深度分析
    reason: str                                             # 推荐或打分理由

class ParsedComment(BaseModel):
    """邮件线程中的审阅与讨论回复（树形结构）"""
    author: str                                             # 评论者 (Name <email>)
    date: Optional[str] = None                              # 评论发送时间
    message_id: str                                         # 评论邮件 Message-ID
    in_reply_to: Optional[str] = None                       # 被回复的父邮件 Message-ID
    body: str                                               # 评论正文（内联讨论与反馈）
    replies: List[ParsedComment] = Field(default_factory=list) # 嵌套的子回复列表

class ParsedPatch(BaseModel):
    """清洗与拆解后的单个 Patch"""
    index: int                                              # 补丁序号 (如 1, 2, ...)
    total: int                                              # 补丁总数 (如 3)
    subject: str                                            # 主题行
    author: str                                             # 补丁作者
    date: Optional[str] = None                              # 发送时间
    message_id: str                                         # 补丁 Message-ID
    commit_message: str                                     # 清洗后的 Git Commit 描述
    trailers: List[str] = Field(default_factory=list)       # Signed-off-by / Reviewed-by 等
    diffstat: Optional[str] = None                          # 变更统计
    diff: str                                               # 统一 Diff 内容
    comments: List[ParsedComment] = Field(default_factory=list) # 针对该 Patch 的审阅树

class ParsedCoverLetter(BaseModel):
    """Cover Letter 结构化数据 (多 Patch 系列存在)"""
    subject: str                                            # Cover Letter 标题
    author: str                                             # 作者
    date: Optional[str] = None                              # 发送时间
    message_id: str                                         # Cover Letter Message-ID
    body: str                                               # 说明正文与变更说明
    diffstat: Optional[str] = None                          # 系列总体 Diffstat

class ParsedPatchset(BaseModel):
    """清洗与解析后的完整 Patchset，直接供 AI Agent 在阶段三消费"""
    id: str                                                 # 代表性 Message-ID
    title: str                                              # 系列标题
    total_patches: int                                      # 包含补丁总数
    cover_letter: Optional[ParsedCoverLetter] = None        # Cover letter
    patches: List[ParsedPatch] = Field(default_factory=list)# 各 Patch 结构列表
    general_comments: List[ParsedComment] = Field(default_factory=list) # 针对整体的审阅树
```

---

## 4. 存储与目录结构 (`SessionManager`)

在 `data/runs/<run_id>/` 下增加阶段二文件：

```text
data/runs/<run_id>/
├── manifest.json              # 会话基础清单 (RunManifest)
├── raw_metadata.json          # [阶段一] 原始邮件元数据
├── patchsets.json             # [阶段一] 聚合后的 Patchset 列表
├── prompt.md                  # [阶段一] AI 筛选提示词
├── reviews.json               # [阶段二] 导入的 AI 打分与推荐结果
├── filtered_patchsets.json    # [阶段二] 经筛选后待拉取的 Patchset 列表
├── stage3_prompt.md           # [阶段二] 阶段三深度分析提示词
└── patchsets/                 # [阶段二] 补丁集拉取与解析目录
    └── <sanitized_msgid>/     # 路径安全的 MsgID 目录（如 20260830114731.8322-1-wujianyue000_gmail.com）
        ├── series.mbx         # b4 下载的原始线程 mbox
        └── parsed_series.json # 结构化 ParsedPatchset 数据
```

- **文件名安全化规则 (`sanitize_id`)**：
  将 Message-ID 中的 `<`、`>`、`@`、`:`、`/`、`\\` 转换为 `_` 或无害字符，避免操作系统路径非法。

---

## 5. 核心组件设计与实现细节

### 5.1 B4 适配器 (`src/kp/adapters/b4.py`)

- **类名**：`B4Client`
- **主要职责**：
  - 调用系统 `/usr/bin/b4` 命令拉取指定 Message-ID 的邮件线程。
  - 命令模板：`b4 mbox <msgid> -o <target_dir> -n series.mbx`
  - 若 `series.mbx` 成功生成则返回其 `Path`。
- **异常定义**：
  - `B4NotFoundError`：系统中未安装 `b4`。
  - `B4ExecutionError`：`b4` 执行失败（如网络不可达、Message-ID 不存在、超时等）。
- **配置支持**：
  - 在 `src/kp/config.py` 中增加 `B4Config(timeout_seconds=120)`。

### 5.2 Mbox 结构化清洗与评论树解析器 (`src/kp/core/parser.py`)

- **类名**：`MboxParser`
- **解析算法与流程**：
  1. **读取 mbox**：使用 Python `mailbox.mbox(file_path)` 读取所有 `email.message.Message` 实例。
  2. **消息提取与规范化**：
     - 解码邮件头（Subject, From, Date, Message-ID, In-Reply-To, References）。
     - 提取纯文本正文（处理 multipart/mixed, quoted-printable, utf-8 编码）。
  3. **分类判定**：
     - **Cover Letter 判定**：Subject 包含 `0/N` 或无 patch 序号的独立初始邮件，且正文无完整 patch diff。
     - **Patch 判定**：包含 `diff --git` 或 `--- a/` 与 `+++ b/` 代码补丁，且主题包含 `[PATCH ... i/N]` 或独立 `[PATCH]`。
       - 分割 **Commit Message**（正文上部直到第一个 `Signed-off-by:` 或 `---` 分割线）。
       - 分割 **Trailers**（`Signed-off-by:`, `Reviewed-by:`, `Acked-by:`, `Cc:` 等）。
       - 分割 **Diffstat** 与 **Diff**。
     - **Comment / Discussion 判定**：所有非 Patch 且非 Cover Letter 的后续回复邮件（带有 `In-Reply-To`）。
  4. **构建评论树 (Thread Tree Reconstruction)**：
     - 创建 `ParsedComment` 节点字典：`comments_by_id[msg_id]`。
     - 遍历所有评论节点，确定其父节点 ID（优先 `In-Reply-To`，其次 `References[-1]`）：
       - 若父节点也是评论节点，则加入该评论节点的 `replies` 列表。
       - 若父节点是某个 Patch 的 `message_id`，加入该 `ParsedPatch.comments` 根列表。
       - 若父节点是 Cover Letter 或缺失，加入 `ParsedPatchset.general_comments` 根列表。
  5. **排序与组装**：
     - 将 Patch 按 `index` 升序排序。
     - 组装为 `ParsedPatchset` 并返回。

### 5.3 阶段三提示词构建器 (`src/kp/core/stage3_prompt.py`)

- **类名**：`Stage3PromptBuilder`
- **职责**：
  - 读取本次运行已成功解析的各 `parsed_series.json` 的绝对路径与摘要信息。
  - 生成 `stage3_prompt.md`，引导 AI 专家针对下载的完整补丁代码与社区讨论进行深度内核分析（架构影响、锁与并发安全、内存管理、潜在回归、社区分歧点总结）。

### 5.4 流程编排器 (`src/kp/core/download_pipeline.py`)

- **类名**：`DownloadPipeline`
- **输入参数**：
  - `run_id: str`
  - `target_ids: Optional[List[str]]` (若直接指定 ID)
  - `reviews_content: Optional[str]` (若提供 review JSON 内容)
  - `min_score: int = 70`
- **执行步骤**：
  1. 定位 `data/runs/<run_id>/` 目录并加载 `patchsets.json`。
  2. 若提供了 `reviews_content`：
     - 解析并校验 `List[PatchReview]`。
     - 筛选出满足 `(score >= min_score or recommend is True)` 的补丁集。
     - 保存 `reviews.json` 与 `filtered_patchsets.json`。
     - 获取待下载列表。
  3. 若直接指定 `target_ids`：
     - 校验 ID 在本次 run 中有效（或允许直接下载）。
  4. 循环调用 `B4Client` 下载每个 Patchset 的 mbox 到 `data/runs/<run_id>/patchsets/<sanitized_id>/`。
  5. 循环调用 `MboxParser` 进行清洗，保存 `parsed_series.json`。
  6. 生成 `stage3_prompt.md` 并写入会话目录。
  7. 返回执行摘要结果 `DownloadResult`。

### 5.5 CLI 子命令 (`src/kp/cli.py`)

新增 `kp download`：
```python
@main.command(name="download")
@click.option("--run-id", required=True, help="指定阶段一的运行会话 ID")
@click.option("--id", "patchset_id", help="直接指定下载的单个 Patchset ID")
@click.option("--input", "input_file", type=click.Path(allow_dash=True), help="AI 评审结果文件路径 (支持 '-' 标准输入)")
@click.option("--min-score", default=70, show_default=True, type=int, help="最低推荐分数阈值")
```

---

## 6. 异常处理与边界情况

1. **AI 评审 JSON 格式不合法**：捕获 JSON 解码异常或 Pydantic 校验错误，向终端输出友好的格式提示并退出。
2. **`b4` 网络拉取失败 / 目标不存在**：捕获 `B4ExecutionError`，记录单个 Patchset 下载失败日志，不阻断其他 Patchset 下载。
3. **单 Patch 与多 Patch 兼容**：单 Patch 邮件没有独立 Cover Letter，解析器正确识别并在 `ParsedPatchset.cover_letter` 置为 `None`，同时正确解析其正文与内联 Diff。
4. **乱序或悬空回复处理**：若某些评论回复的父邮件 ID 未能在 mbox 中找到，安全回退挂载到 `general_comments` 顶层，保证信息不丢失。
5. **编码与多部分格式处理**：使用 Python `email.header` 与 `email.policy.default` 安全解码各种字符集与 base64/quoted-printable 内容。

---

## 7. 测试与验证方案

1. **单元测试 (Mock 隔离)**：
   - `tests/test_b4_adapter.py`：测试 B4Client 命令行构造、执行成功与失败异常抛出。
   - `tests/test_parser.py`：使用真实内核 mbox 样本测试 MboxParser：
     - 单 Patch 邮件解析。
     - 多 Patch + Cover Letter 邮件解析。
     - 嵌套评论与回复树（Reviewer -> Author -> Reviewer）结构解析与还原。
   - `tests/test_download_pipeline.py`：测试从 Reviews 筛选、下载、解析到生成 stage3 提示词的全流程。
   - `tests/test_download_cli.py`：使用 Click `CliRunner` 测试 `--id`、`--input file`、`--input -` 各分支。
2. **端到端回归与全量测试**：
   - 执行 `uv run pytest`，确保全套测试（包含阶段一与阶段二测试）100% 通过。
