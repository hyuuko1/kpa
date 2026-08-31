from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Optional
from kp.models import PatchsetRecord, PatchsetStatus, QueryCursor, RunRecord


class DatabaseManager:
    """管理 SQLite 数据库连接、表结构初始化与数据实体 CRUD 操作"""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)

    def get_connection(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.row_factory = sqlite3.Row
        return conn

    def init_tables(self) -> None:
        with self.get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS query_cursors (
                    query_key TEXT PRIMARY KEY,
                    last_sync_time TEXT NOT NULL,
                    last_run_id TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    raw_count INTEGER NOT NULL DEFAULT 0,
                    patchset_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                );
                CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at DESC);

                CREATE TABLE IF NOT EXISTS patchsets (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    author TEXT,
                    date TEXT,
                    total_patches INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'fetched' CHECK(status IN ('fetched', 'downloaded', 'analyzed', 'ignored')),
                    score INTEGER CHECK(score IS NULL OR (score >= 0 AND score <= 10)),
                    recommend INTEGER CHECK(recommend IS NULL OR recommend IN (0, 1)),
                    review_reason TEXT,
                    downloaded_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_patchsets_status ON patchsets(status);
                CREATE INDEX IF NOT EXISTS idx_patchsets_date ON patchsets(date DESC);
                CREATE INDEX IF NOT EXISTS idx_patchsets_score ON patchsets(score DESC);
                """
            )
            conn.commit()

    def get_cursor(self, query_key: str) -> Optional[QueryCursor]:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT query_key, last_sync_time, last_run_id FROM query_cursors WHERE query_key = ?",
                (query_key,),
            ).fetchone()
            if row:
                return QueryCursor(
                    query_key=row["query_key"],
                    last_sync_time=row["last_sync_time"],
                    last_run_id=row["last_run_id"],
                )
            return None

    def update_cursor(
        self, query_key: str, last_sync_time: str, last_run_id: str
    ) -> None:
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO query_cursors (query_key, last_sync_time, last_run_id)
                VALUES (?, ?, ?)
                ON CONFLICT(query_key) DO UPDATE SET
                    last_sync_time = excluded.last_sync_time,
                    last_run_id = excluded.last_run_id;
                """,
                (query_key, last_sync_time, last_run_id),
            )
            conn.commit()

    def record_run(self, run: RunRecord) -> None:
        with self.get_connection() as conn:
            if run.created_at:
                conn.execute(
                    """
                    INSERT INTO runs (run_id, query, raw_count, patchset_count, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(run_id) DO UPDATE SET
                        query = excluded.query,
                        raw_count = excluded.raw_count,
                        patchset_count = excluded.patchset_count,
                        created_at = excluded.created_at;
                    """,
                    (
                        run.run_id,
                        run.query,
                        run.raw_count,
                        run.patchset_count,
                        run.created_at,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO runs (run_id, query, raw_count, patchset_count)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(run_id) DO UPDATE SET
                        query = excluded.query,
                        raw_count = excluded.raw_count,
                        patchset_count = excluded.patchset_count;
                    """,
                    (run.run_id, run.query, run.raw_count, run.patchset_count),
                )
            conn.commit()

    def upsert_patchset(self, record: PatchsetRecord) -> None:
        with self.get_connection() as conn:
            recommend_val = None
            if record.recommend is not None:
                recommend_val = 1 if record.recommend else 0

            conn.execute(
                """
                INSERT INTO patchsets (
                    id, title, author, date, total_patches, status, score, recommend, review_reason, downloaded_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    author = COALESCE(excluded.author, patchsets.author),
                    date = COALESCE(excluded.date, patchsets.date),
                    total_patches = excluded.total_patches;
                """,
                (
                    record.id,
                    record.title,
                    record.author,
                    record.date,
                    record.total_patches,
                    record.status.value
                    if isinstance(record.status, PatchsetStatus)
                    else record.status,
                    record.score,
                    recommend_val,
                    record.review_reason,
                    record.downloaded_at,
                ),
            )
            conn.commit()

    def get_patchset(self, id: str) -> Optional[PatchsetRecord]:
        with self.get_connection() as conn:
            row = conn.execute(
                """
                SELECT id, title, author, date, total_patches, status, score, recommend, review_reason, downloaded_at
                FROM patchsets
                WHERE id = ?
                """,
                (id,),
            ).fetchone()
            if not row:
                return None
            return PatchsetRecord(
                id=row["id"],
                title=row["title"],
                author=row["author"],
                date=row["date"],
                total_patches=row["total_patches"],
                status=PatchsetStatus(row["status"]),
                score=row["score"],
                recommend=bool(row["recommend"])
                if row["recommend"] is not None
                else None,
                review_reason=row["review_reason"],
                downloaded_at=row["downloaded_at"],
            )

    def list_patchsets(
        self, status: Optional[PatchsetStatus] = None
    ) -> List[PatchsetRecord]:
        with self.get_connection() as conn:
            if status is not None:
                rows = conn.execute(
                    """
                    SELECT id, title, author, date, total_patches, status, score, recommend, review_reason, downloaded_at
                    FROM patchsets
                    WHERE status = ?
                    ORDER BY date DESC
                    """,
                    (status.value,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, title, author, date, total_patches, status, score, recommend, review_reason, downloaded_at
                    FROM patchsets
                    ORDER BY date DESC
                    """
                ).fetchall()

            return [
                PatchsetRecord(
                    id=row["id"],
                    title=row["title"],
                    author=row["author"],
                    date=row["date"],
                    total_patches=row["total_patches"],
                    status=PatchsetStatus(row["status"]),
                    score=row["score"],
                    recommend=bool(row["recommend"])
                    if row["recommend"] is not None
                    else None,
                    review_reason=row["review_reason"],
                    downloaded_at=row["downloaded_at"],
                )
                for row in rows
            ]

    def update_patchset_review(
        self,
        id: str,
        score: Optional[int],
        recommend: Optional[bool],
        reason: Optional[str] = None,
    ) -> None:
        with self.get_connection() as conn:
            recommend_val = None
            if recommend is not None:
                recommend_val = 1 if recommend else 0
            conn.execute(
                """
                UPDATE patchsets
                SET score = ?, recommend = ?, review_reason = ?
                WHERE id = ?
                """,
                (score, recommend_val, reason, id),
            )
            conn.commit()

    def update_patchset_status(
        self,
        id: str,
        status: PatchsetStatus,
        downloaded_at: Optional[str] = None,
    ) -> None:
        with self.get_connection() as conn:
            if downloaded_at is not None:
                conn.execute(
                    """
                    UPDATE patchsets
                    SET status = ?, downloaded_at = ?
                    WHERE id = ?
                    """,
                    (status.value, downloaded_at, id),
                )
            else:
                conn.execute(
                    """
                    UPDATE patchsets
                    SET status = ?
                    WHERE id = ?
                    """,
                    (status.value, id),
                )
            conn.commit()
