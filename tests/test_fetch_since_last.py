from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from kp.config import AppConfig, SafetyConfig, StorageConfig, LoreConfig
from kp.core.pipeline import FetchPipeline
from kp.models import RawMessage, PatchsetStatus


@pytest.fixture
def mock_pipeline(tmp_path: Path):
    config = AppConfig(
        storage=StorageConfig(data_dir=str(tmp_path)),
        safety=SafetyConfig(
            max_time_span_hours=48,
            require_time_filter=True,
            chunk_hours=24,
            max_catchup_hours=72,
            overlap_grace_minutes=10,
        ),
        lore=LoreConfig(inbox_url="https://lore.kernel.org/all/"),
    )
    pipeline = FetchPipeline(config)
    return pipeline


def test_clean_query_key(mock_pipeline: FetchPipeline):
    q1 = "l:netdev@vger.kernel.org AND dt:2.hours.ago.. AND NOT s:Re"
    assert mock_pipeline.clean_query_key(q1) == "l:netdev@vger.kernel.org AND NOT s:Re"

    q2 = "  dt:2026-08-30T10:00:00Z..   l:linux-mm   "
    assert mock_pipeline.clean_query_key(q2) == "l:linux-mm"

    q3 = "l:linux-fsdevel"
    assert mock_pipeline.clean_query_key(q3) == "l:linux-fsdevel"


def test_fetch_since_last_cold_start(mock_pipeline: FetchPipeline):
    fake_msgs = [
        RawMessage(
            m="msg1@kernel.org",
            s="[PATCH 1/1] net: fix socket leak",
            f=[["Author", "auth@kernel.org"]],
            dt="2026-09-01T01:00:00Z",
        )
    ]
    mock_pipeline.lore_client.query = MagicMock(return_value=fake_msgs)

    query = "l:netdev@vger.kernel.org AND NOT s:Re"
    res = mock_pipeline.run(query, since_last=True)

    assert res.raw_count == 1
    assert res.patchset_count == 1

    # Check database cursor
    cursor = mock_pipeline.session_manager.db.get_cursor(
        "l:netdev@vger.kernel.org AND NOT s:Re"
    )
    assert cursor is not None
    assert cursor.last_run_id == res.run_id

    # Check patchsets table
    record = mock_pipeline.session_manager.db.get_patchset("msg1@kernel.org")
    assert record is not None
    assert record.status == PatchsetStatus.FETCHED
    assert record.title == "[PATCH 1/1] net: fix socket leak"


def test_fetch_since_last_existing_cursor(mock_pipeline: FetchPipeline):
    # Pre-populate cursor: 5 hours ago
    t_sync = (datetime.now(timezone.utc) - timedelta(hours=5)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    mock_pipeline.session_manager.db.update_cursor(
        query_key="l:netdev@vger.kernel.org AND NOT s:Re",
        last_sync_time=t_sync,
        last_run_id="old_run",
    )

    fake_msgs = [
        RawMessage(
            m="msg2@kernel.org",
            s="[PATCH] net: another fix",
            f=[["Author", "auth@kernel.org"]],
            dt="2026-09-01T02:00:00Z",
        )
    ]
    captured_queries = []

    def mock_query(q):
        captured_queries.append(q)
        return fake_msgs

    mock_pipeline.lore_client.query = mock_query

    res = mock_pipeline.run("l:netdev@vger.kernel.org AND NOT s:Re", since_last=True)
    assert res.raw_count == 1
    assert len(captured_queries) == 1
    # Query must contain AND dt:
    assert " AND dt:" in captured_queries[0]
    assert captured_queries[0].startswith(
        "l:netdev@vger.kernel.org AND NOT s:Re AND dt:"
    )

    updated_cursor = mock_pipeline.session_manager.db.get_cursor(
        "l:netdev@vger.kernel.org AND NOT s:Re"
    )
    assert updated_cursor.last_run_id == res.run_id


def test_fetch_since_last_multi_chunk(mock_pipeline: FetchPipeline):
    # Pre-populate cursor: 50 hours ago (should split into 3 chunks of 24h)
    t_sync = (datetime.now(timezone.utc) - timedelta(hours=50)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    mock_pipeline.session_manager.db.update_cursor(
        query_key="l:netdev@vger.kernel.org",
        last_sync_time=t_sync,
        last_run_id="old_run",
    )

    captured_queries = []

    def mock_query(q):
        captured_queries.append(q)
        return [
            RawMessage(
                m=f"msg_{len(captured_queries)}@kernel.org",
                s=f"[PATCH] patch {len(captured_queries)}",
                f=[["Author", "auth@kernel.org"]],
                dt="2026-09-01T00:00:00Z",
            )
        ]

    mock_pipeline.lore_client.query = mock_query

    res = mock_pipeline.run("l:netdev@vger.kernel.org", since_last=True)
    assert len(captured_queries) == 3
    assert res.raw_count == 3
    assert res.patchset_count == 3


def test_fetch_since_last_max_catchup_cap(mock_pipeline: FetchPipeline):
    # Cursor 120 hours ago -> max_catchup_hours is 72h -> should be capped at 72h -> 3 chunks
    t_sync = (datetime.now(timezone.utc) - timedelta(hours=120)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    mock_pipeline.session_manager.db.update_cursor(
        query_key="l:netdev@vger.kernel.org",
        last_sync_time=t_sync,
        last_run_id="ancient_run",
    )

    captured_queries = []

    def mock_query(q):
        captured_queries.append(q)
        return []

    mock_pipeline.lore_client.query = mock_query
    mock_pipeline.run("l:netdev@vger.kernel.org", since_last=True)

    assert len(captured_queries) == 3


def test_fetch_since_last_empty_query_key(mock_pipeline: FetchPipeline):
    # Query is only a dt filter, so query_key is empty
    captured_queries = []

    def mock_query(q):
        captured_queries.append(q)
        return []

    mock_pipeline.lore_client.query = mock_query
    mock_pipeline.run("dt:2.hours.ago..", since_last=True)

    assert len(captured_queries) == 1
    assert captured_queries[0].startswith("dt:")
    assert "AND" not in captured_queries[0]
