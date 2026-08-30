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

class Patchset(BaseModel):
    """清洗与聚合后的完整补丁集"""
    id: str                                                 # 下载全套 patchset 的代表性 Message-ID (0/N 或 1/N 或独立 patch ID)
    title: str                                              # 系列标题 (Cover Letter 标题或 Patch 1 标题)
    author_name: str                                        # 作者姓名
    author_email: str                                       # 作者邮箱
    date: Optional[str] = None                              # 发送时间
    patches: List[str] = Field(default_factory=list)        # 包含的所有 patch 标题列表 (按 index 排序)


class RunManifest(BaseModel):
    """运行会话摘要清单"""
    run_id: str                                             # 会话 ID (如 20260830_175000_3a8f1b)
    timestamp: str                                          # 执行时间戳 (ISO)
    query: str                                              # 执行的查询语句
    total_raw_messages: int                                 # 原始消息数
    total_patchsets: int                                    # 聚合后的补丁集数
