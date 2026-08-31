from __future__ import annotations

import re
from pathlib import Path


def get_clean_id(msgid: str) -> str:
    """去除首尾尖括号，将 / 转义为 %2F"""
    cleaned = msgid.strip().lstrip("<").rstrip(">")
    return cleaned.replace("/", "%2F")


def get_month_bucket(date_str: str | None) -> str:
    """从 ISO 时间字符串中提取 YYYY-MM 年月分层，回退至 'unknown'"""
    if not date_str:
        return "unknown"
    date_str = date_str.strip()
    if len(date_str) >= 7 and re.match(r"^\d{4}-\d{2}", date_str):
        return date_str[:7]
    if len(date_str) >= 6 and re.match(r"^\d{6}", date_str):
        return f"{date_str[:4]}-{date_str[4:6]}"
    return "unknown"


def get_patchset_dir(data_dir: Path, msgid: str, date_str: str | None = None) -> Path:
    """返回补丁集在全局资产库中的根目录：data/patchsets/YYYY-MM/<clean_id>/"""
    return data_dir / "patchsets" / get_month_bucket(date_str) / get_clean_id(msgid)


def get_report_path(data_dir: Path, msgid: str, date_str: str | None = None) -> Path:
    """返回深度分析报告在全局知识库中的文件路径：data/reports/YYYY-MM/<clean_id>.md"""
    return (
        data_dir / "reports" / get_month_bucket(date_str) / f"{get_clean_id(msgid)}.md"
    )
