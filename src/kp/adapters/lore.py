from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from typing import List
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
        rel_match = re.match(
            r"^(\d+)\.(minutes?|hours?|days?|weeks?|months?|years?)\.ago$",
            expr,
            re.IGNORECASE,
        )
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
            if delta_minutes > (self.config.max_time_span_minutes + 5):  # 容差 5 分钟
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
            raise LoreExecutionError(
                "系统环境中未找到 lei 工具，请确保已正确安装 public-inbox/lei"
            )

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
            raise LoreExecutionError(
                f"lei 查询超时 ({self.lore_config.timeout_seconds}s)"
            ) from e
        except Exception as e:
            raise LoreExecutionError(f"执行 lei 命令失败: {e}") from e

        if res.returncode != 0:
            raise LoreExecutionError(
                f"lei 查询失败 (code {res.returncode}): {res.stderr.strip()}"
            )

        stdout = res.stdout.strip()
        if not stdout:
            return []

        try:
            data = json.loads(stdout)
            if not isinstance(data, list):
                return []
            # 过滤掉尾部可能的 null 项
            valid_items = [
                item
                for item in data
                if isinstance(item, dict) and "m" in item and "s" in item
            ]
            return [RawMessage.model_validate(item) for item in valid_items]
        except Exception as e:
            raise LoreExecutionError(f"解析 lei 返回的 JSON 失败: {e}") from e
