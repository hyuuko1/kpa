from pathlib import Path
from kp.models import PatchsetRecord, PatchsetStatus, RunRecord
from kp.storage.db import DatabaseManager


def test_db_init_and_wal(tmp_path: Path):
    db_path = tmp_path / "kp.db"
    db = DatabaseManager(db_path)
    db.init_tables()
    assert db_path.exists()

    # Verify journal mode
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode;")
        row = cursor.fetchone()
        assert row[0].lower() == "wal"


def test_query_cursor_lifecycle(tmp_path: Path):
    db = DatabaseManager(tmp_path / "kp.db")
    db.init_tables()

    assert db.get_cursor("l:netdev@vger.kernel.org") is None

    db.update_cursor(
        query_key="l:netdev@vger.kernel.org",
        last_sync_time="2026-08-30T10:00:00Z",
        last_run_id="run_1",
    )

    cursor = db.get_cursor("l:netdev@vger.kernel.org")
    assert cursor is not None
    assert cursor.query_key == "l:netdev@vger.kernel.org"
    assert cursor.last_sync_time == "2026-08-30T10:00:00Z"
    assert cursor.last_run_id == "run_1"

    # Update again
    db.update_cursor(
        query_key="l:netdev@vger.kernel.org",
        last_sync_time="2026-08-31T10:00:00Z",
        last_run_id="run_2",
    )
    updated = db.get_cursor("l:netdev@vger.kernel.org")
    assert updated.last_sync_time == "2026-08-31T10:00:00Z"
    assert updated.last_run_id == "run_2"


def test_run_records(tmp_path: Path):
    db = DatabaseManager(tmp_path / "kp.db")
    db.init_tables()

    run = RunRecord(
        run_id="20260901_000000",
        query="l:linux-mm.kvack.org",
        raw_count=5,
        patchset_count=2,
    )
    db.record_run(run)

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT run_id, query, raw_count, patchset_count FROM runs WHERE run_id = ?",
            ("20260901_000000",),
        )
        row = cursor.fetchone()
        assert tuple(row) == ("20260901_000000", "l:linux-mm.kvack.org", 5, 2)


def test_patchset_upsert_and_status(tmp_path: Path):
    db = DatabaseManager(tmp_path / "kp.db")
    db.init_tables()

    record = PatchsetRecord(
        id="test_id_1@kernel.org",
        title="[PATCH] first version",
        author="Dev <dev@kernel.org>",
        date="2026-08-30T12:00:00Z",
        total_patches=2,
        status=PatchsetStatus.FETCHED,
    )
    db.upsert_patchset(record)

    fetched = db.get_patchset("test_id_1@kernel.org")
    assert fetched is not None
    assert fetched.title == "[PATCH] first version"
    assert fetched.status == PatchsetStatus.FETCHED
    assert fetched.downloaded_at is None

    # Update review
    db.update_patchset_review(
        id="test_id_1@kernel.org",
        score=9,
        recommend=True,
        reason="High quality",
    )
    reviewed = db.get_patchset("test_id_1@kernel.org")
    assert reviewed.score == 9
    assert reviewed.recommend is True
    assert reviewed.review_reason == "High quality"

    import pytest

    with pytest.raises(
        ValueError,
        match="更新评审打分失败：数据库中未找到 Patchset 'nonexistent_id'，请检查 ID 是否正确",
    ):
        db.update_patchset_review(
            id="nonexistent_id",
            score=5,
            recommend=False,
            reason="not found",
        )

    # Update status to downloaded
    db.update_patchset_status(
        id="test_id_1@kernel.org",
        status=PatchsetStatus.DOWNLOADED,
        downloaded_at="2026-08-31T00:00:00Z",
    )
    downloaded = db.get_patchset("test_id_1@kernel.org")
    assert downloaded.status == PatchsetStatus.DOWNLOADED
    assert downloaded.downloaded_at == "2026-08-31T00:00:00Z"

    # Re-upserting from fetch shouldn't wipe status/score/downloaded_at
    record_re = PatchsetRecord(
        id="test_id_1@kernel.org",
        title="[PATCH] updated title",
        author="Dev <dev@kernel.org>",
        date="2026-08-30T12:00:00Z",
        total_patches=3,
    )
    db.upsert_patchset(record_re)
    re_fetched = db.get_patchset("test_id_1@kernel.org")
    assert re_fetched.title == "[PATCH] updated title"
    assert re_fetched.total_patches == 3
    assert re_fetched.status == PatchsetStatus.DOWNLOADED
    assert re_fetched.score == 9
    assert re_fetched.downloaded_at == "2026-08-31T00:00:00Z"
