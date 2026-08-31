from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional, Tuple
from pydantic import BaseModel
from kp.config import AppConfig
from kp.adapters.lore import LoreClient
from kp.core.aggregator import PatchsetAggregator
from kp.storage.session import SessionManager
from kp.storage.paths import get_clean_id
from kp.models import RunManifest, RawMessage, RunRecord, PatchsetRecord, PatchsetStatus


class PipelineResult(BaseModel):
    run_id: str
    run_dir: Path
    raw_count: int
    patchset_count: int


FetchRunResult = PipelineResult


class FetchPipeline:
    """阶段一核心业务流水线：Query -> Lore -> Aggregator -> SessionStorage + SQLite"""

    def __init__(self, config: AppConfig):
        self.config = config
        self.lore_client = LoreClient(config.lore, config.safety)
        self.aggregator = PatchsetAggregator()
        self.session_manager = SessionManager(config.storage)

    def clean_query_key(self, query: str) -> str:
        """剥离 d: 时间过滤及多余逻辑操作符并规范化空白字符作为稳定的 query_key"""
        pure = re.sub(r"\bAND\s+d:[^\s\"]+", "", query, flags=re.IGNORECASE)
        pure = re.sub(r"\bd:[^\s\"]+\s+AND\b", "", pure, flags=re.IGNORECASE)
        pure = re.sub(r"\bd:[^\s\"]+", "", pure)
        pure = re.sub(r"\b(AND|OR)\s+(AND|OR)\b", r"\1", pure, flags=re.IGNORECASE)
        pure = re.sub(r"^\s*(AND|OR)\b", "", pure, flags=re.IGNORECASE)
        pure = re.sub(r"\b(AND|OR)\s*$", "", pure, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", pure).strip()

    def _parse_start_date_from_query(
        self, query: str, now_dt: datetime
    ) -> Optional[datetime]:
        """从 query 中的 d: 表达式解析起始时间"""
        match = re.search(r"\bd:([^\s\"]+)", query)
        if not match:
            return None
        expr = match.group(1).rstrip(".")

        # 1. 相对时间表达解析 (e.g. 2.hours.ago, 1.day.ago)
        rel_match = re.match(
            r"^(\d+)\.(minutes?|hours?|days?|weeks?|months?|years?)\.ago$",
            expr,
            re.IGNORECASE,
        )
        if rel_match:
            val = int(rel_match.group(1))
            unit = rel_match.group(2).lower()
            if unit.startswith("minute"):
                return now_dt - timedelta(minutes=val)
            elif unit.startswith("hour"):
                return now_dt - timedelta(hours=val)
            elif unit.startswith("day"):
                return now_dt - timedelta(days=val)
            elif unit.startswith("week"):
                return now_dt - timedelta(weeks=val)

        # 2. 绝对时间解析
        if ".." in expr:
            expr = expr.split("..")[0]
        try:
            dt = datetime.fromisoformat(expr.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None

    def run(self, query: str, since_last: bool = False) -> FetchRunResult:
        run_id, run_dir = self.session_manager.create_session_dir()
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        if since_last:
            query_key = self.clean_query_key(query)
            cursor = self.session_manager.db.get_cursor(query_key)

            if cursor:
                last_sync_dt = datetime.fromisoformat(
                    cursor.last_sync_time.replace("Z", "+00:00")
                )
                if last_sync_dt.tzinfo is None:
                    last_sync_dt = last_sync_dt.replace(tzinfo=timezone.utc)
                start_dt = last_sync_dt - timedelta(
                    minutes=self.config.safety.overlap_grace_minutes
                )
            else:
                start_from_q = self._parse_start_date_from_query(query, now_dt)
                if start_from_q:
                    start_dt = start_from_q
                else:
                    start_dt = now_dt - timedelta(hours=self.config.safety.chunk_hours)

            # 最大追溯上限截断保护
            max_catchup_delta = timedelta(hours=self.config.safety.max_catchup_hours)
            if (now_dt - start_dt) > max_catchup_delta:
                start_dt = now_dt - max_catchup_delta

            # 切片为多个 chunk
            chunk_delta = timedelta(hours=self.config.safety.chunk_hours)
            chunks: List[Tuple[datetime, datetime]] = []
            curr = start_dt
            while curr < now_dt:
                nxt = min(curr + chunk_delta, now_dt)
                chunks.append((curr, nxt))
                curr = nxt
            if not chunks:
                chunks.append((start_dt, now_dt))

            all_raw_msgs: List[RawMessage] = []
            for chunk_start, chunk_end in chunks:
                start_str = chunk_start.strftime("%Y-%m-%dT%H:%M:%SZ")
                end_str = chunk_end.strftime("%Y-%m-%dT%H:%M:%SZ")
                if query_key:
                    sub_query = f"{query_key} d:{start_str}..{end_str}"
                else:
                    sub_query = f"d:{start_str}..{end_str}"

                batch_msgs = self.lore_client.query(sub_query)
                all_raw_msgs.extend(batch_msgs)
                # 即时推进游标
                self.session_manager.db.update_cursor(query_key, end_str, run_id)

            # 按 Message-ID 去重
            seen_ids = set()
            dedup_msgs: List[RawMessage] = []
            for m in all_raw_msgs:
                if m.m not in seen_ids:
                    seen_ids.add(m.m)
                    dedup_msgs.append(m)
            raw_msgs = dedup_msgs
        else:
            raw_msgs = self.lore_client.query(query)
            query_key = self.clean_query_key(query)
            if query_key:
                self.session_manager.db.update_cursor(query_key, now_iso, run_id)

        # 3. 清洗与聚合为 Patchset 列表
        patchsets = self.aggregator.aggregate(raw_msgs)

        # 4. 同步至 SQLite 数据库
        self.session_manager.db.record_run(
            RunRecord(
                run_id=run_id,
                query=query,
                raw_count=len(raw_msgs),
                patchset_count=len(patchsets),
                created_at=now_iso,
            )
        )
        for ps in patchsets:
            clean_id = get_clean_id(ps.id)
            author_str = f"{ps.author_name} <{ps.author_email}>"
            self.session_manager.db.upsert_patchset(
                PatchsetRecord(
                    id=clean_id,
                    title=ps.title,
                    author=author_str,
                    date=ps.date,
                    total_patches=len(ps.patches) if ps.patches else 1,
                    status=PatchsetStatus.FETCHED,
                )
            )

        # 5. 持久化所有文件成果物
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
        )

        return FetchRunResult(
            run_id=run_id,
            run_dir=run_dir,
            raw_count=len(raw_msgs),
            patchset_count=len(patchsets),
        )
