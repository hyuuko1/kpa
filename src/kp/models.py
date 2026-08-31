from __future__ import annotations

from pathlib import Path
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class RawMessage(BaseModel):
    """直接映射 lei q 返回的单条邮件元数据"""

    blob: Optional[str] = None
    m: str  # Message-ID
    s: str  # Subject
    f: List[List[Optional[str]]] = Field(
        default_factory=list
    )  # From: [["Name", "email"]]
    t: Optional[List[List[Optional[str]]]] = None  # To: [["Name", "email"], ...]
    c: Optional[List[List[Optional[str]]]] = None  # Cc: [["Name", "email"], ...]
    dt: Optional[str] = None  # Date (ISO8601)
    rt: Optional[str] = None  # Received Time
    refs: Optional[List[str]] = Field(default_factory=list)  # Referenced Message-IDs


class Patchset(BaseModel):
    """清洗与聚合后的完整补丁集"""

    id: str  # 下载全套 patchset 的代表性 Message-ID (0/N 或 1/N 或独立 patch ID)
    title: str  # 系列标题 (Cover Letter 标题或 Patch 1 标题)
    author_name: str  # 作者姓名
    author_email: str  # 作者邮箱
    date: Optional[str] = None  # 发送时间
    patches: List[str] = Field(
        default_factory=list
    )  # 包含的所有 patch 标题列表 (按 index 排序)


class RunManifest(BaseModel):
    """运行会话摘要清单"""

    run_id: str  # 会话 ID (如 20260830_175000)
    timestamp: str  # 执行时间戳 (ISO)
    query: str  # 执行的查询语句
    total_raw_messages: int  # 原始消息数
    total_patchsets: int  # 聚合后的补丁集数


class PatchReview(BaseModel):
    """AI 打分与评审结果项"""

    id: str  # 补丁集代表性 Message-ID
    title: Optional[str] = None  # 补丁集标题
    score: int = Field(ge=0, le=100)  # 价值评分 (0-100)
    recommend: bool  # 是否推荐深度分析
    reason: str  # 推荐或打分理由


class ParsedComment(BaseModel):
    """邮件线程中的审阅与讨论回复（树形结构）"""

    author: str  # 评论者 (Name <email>)
    date: Optional[str] = None  # 评论发送时间
    message_id: str  # 评论邮件 Message-ID
    in_reply_to: Optional[str] = None  # 被回复的父邮件 Message-ID
    body: str  # 评论正文（内联讨论与反馈）
    replies: List[ParsedComment] = Field(default_factory=list)  # 嵌套的子回复列表


class ParsedCoverLetter(BaseModel):
    """Cover Letter 结构化数据 (多 Patch 系列存在)"""

    subject: str  # Cover Letter 标题
    author: str  # 作者
    date: Optional[str] = None  # 发送时间
    message_id: str  # Cover Letter Message-ID
    body: str  # 说明正文与变更说明
    diffstat: Optional[str] = None  # 系列总体 Diffstat


class ParsedPatch(BaseModel):
    """清洗与拆解后的单个 Patch"""

    index: int  # 补丁序号 (如 1, 2, ...)
    total: int  # 补丁总数 (如 3)
    subject: str  # 主题行
    author: str  # 补丁作者
    date: Optional[str] = None  # 发送时间
    message_id: str  # 补丁 Message-ID
    commit_message: str  # 清洗后的 Git Commit 描述
    trailers: List[str] = Field(default_factory=list)  # Signed-off-by / Reviewed-by 等
    diffstat: Optional[str] = None  # 变更统计
    diff: str  # 统一 Diff 内容
    comments: List[ParsedComment] = Field(default_factory=list)  # 针对该 Patch 的审阅树


class ParsedPatchset(BaseModel):
    """清洗与解析后的完整 Patchset，直接供 AI Agent 在阶段三消费"""

    id: str  # 代表性 Message-ID
    title: str  # 系列标题
    total_patches: int  # 包含补丁总数
    cover_letter: Optional[ParsedCoverLetter] = None  # Cover letter
    patches: List[ParsedPatch] = Field(default_factory=list)  # 各 Patch 结构列表
    general_comments: List[ParsedComment] = Field(
        default_factory=list
    )  # 针对整体的审阅树


class PatchsetAnalysis(BaseModel):
    """单个补丁集的 AI 深度分析结果元数据"""

    msgid: str  # 补丁集代表性 Message-ID
    sanitized_id: str  # 路径安全标识符
    status: Literal["success", "failed", "skipped"]  # 分析执行状态
    report_path: Optional[Path] = None  # 生成的 Markdown 报告文件路径
    error_message: Optional[str] = None  # 错误信息（若失败）
    duration_seconds: float = 0.0  # 分析耗时（秒）


class AnalyzeRunResult(BaseModel):
    """阶段三全量分析运行摘要"""

    run_id: str  # 会话 ID
    analyses: List[PatchsetAnalysis] = Field(
        default_factory=list
    )  # 各补丁集分析结果列表
    total_count: int = 0  # 分析总数
    success_count: int = 0  # 成功总数
    failed_count: int = 0  # 失败总数
    skipped_count: int = 0  # 跳过总数
