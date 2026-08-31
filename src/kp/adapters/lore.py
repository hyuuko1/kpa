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
        # 匹配形如 d:2.hours.ago.. 或 d:2026-08-30T10:00:00Z.. 或 d:2026-08-30T10:00:00Z..2026-08-30T18:00:00Z
        match = re.search(r"\bd:([^\s\"]+)", query)
        if not match:
            if self.config.require_time_filter:
                raise SafetyValidationError(
                    "安全限制：Query 中必须包含 d: 时间范围过滤（例如 d:2.hours.ago..）"
                )
            return

        raw_expr = match.group(1)
        self._validate_date_expr(raw_expr)

    def _validate_date_expr(self, raw_expr: str) -> None:
        # 检查是否为显式 START..END 区间
        if ".." in raw_expr:
            parts = raw_expr.split("..", 1)
            start_part = parts[0].strip()
            end_part = parts[1].strip()
            if start_part and end_part:
                # START..END 两个绝对时间或相对时间
                try:
                    start_dt = datetime.fromisoformat(start_part.replace("Z", "+00:00"))
                    end_dt = datetime.fromisoformat(end_part.replace("Z", "+00:00"))
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=timezone.utc)
                    if end_dt.tzinfo is None:
                        end_dt = end_dt.replace(tzinfo=timezone.utc)
                    span_hours = (end_dt - start_dt).total_seconds() / 3600.0
                    if span_hours > (self.config.max_time_span_hours + 0.1):
                        raise SafetyValidationError(
                            f"安全限制：查询时间跨度 {span_hours:.1f} 小时超过最大允许限制 {self.config.max_time_span_hours} 小时"
                        )
                    return
                except ValueError:
                    pass

        expr = raw_expr.rstrip(".")

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
                span_hours = val / 60.0
            elif unit.startswith("hour"):
                span_hours = float(val)
            elif unit.startswith("day"):
                span_hours = float(val * 24)
            else:
                raise SafetyValidationError(
                    f"安全限制：禁止使用大粒度时间单位 '{unit}'，最多允许 {self.config.max_time_span_hours} 小时 (如 d:48.hours.ago..)"
                )

            if span_hours > self.config.max_time_span_hours:
                raise SafetyValidationError(
                    f"安全限制：查询时间跨度 {span_hours:g} 小时超过最大允许限制 {self.config.max_time_span_hours} 小时"
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
            delta_hours = delta_seconds / 3600.0
            if delta_hours > (self.config.max_time_span_hours + 0.1):  # 容差约 6 分钟
                raise SafetyValidationError(
                    f"安全限制：绝对时间 {expr} 距离当前约 {delta_hours:.1f} 小时，超过最大允许限制 {self.config.max_time_span_hours} 小时"
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
