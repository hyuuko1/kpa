from pathlib import Path
from unittest.mock import MagicMock
import pytest

from kp.config import AppConfig, StorageConfig, B4Config
from kp.core.download_pipeline import DownloadPipeline
from kp.models import (
    Patchset,
    ParsedPatchset,
    ParsedPatch,
    PatchsetRecord,
    PatchsetStatus,
)


@pytest.fixture
def download_fixture(tmp_path: Path):
    config = AppConfig(
        storage=StorageConfig(data_dir=str(tmp_path)),
        b4=B4Config(timeout_seconds=120),
    )
    pipeline = DownloadPipeline(config)
    run_id, run_dir = pipeline.session_manager.create_session_dir()

    patchsets = [
        Patchset(
            id="ps1@kernel.org",
            title="[PATCH 1/1] mm: fix alloc",
            author_name="Alice",
            author_email="alice@kernel.org",
            date="2026-08-30T10:00:00Z",
            patches=["[PATCH 1/1] mm: fix alloc"],
        ),
        Patchset(
            id="ps2@kernel.org",
            title="[PATCH 1/1] net: fix sock",
            author_name="Bob",
            author_email="bob@kernel.org",
            date="2026-08-30T12:00:00Z",
            patches=["[PATCH 1/1] net: fix sock"],
        ),
    ]
    from kp.models import RunManifest

    pipeline.session_manager.save_run(
        run_dir=run_dir,
        manifest=RunManifest(
            run_id=run_id,
            timestamp="2026-08-30T12:00:00Z",
            query="q",
            total_raw_messages=2,
            total_patchsets=2,
        ),
        raw_msgs=[],
        patchsets=patchsets,
    )
    # Also record in DB
    for ps in patchsets:
        pipeline.session_manager.db.upsert_patchset(
            PatchsetRecord(
                id=ps.id,
                title=ps.title,
                date=ps.date,
                status=PatchsetStatus.FETCHED,
            )
        )

    return pipeline, run_id, run_dir


def test_download_pipeline_skip_when_up_to_date(download_fixture):
    pipeline, run_id, run_dir = download_fixture

    # Pre-set ps1 as downloaded at 2026-08-30T11:00:00Z (which is AFTER ps1.date 10:00:00Z)
    pipeline.session_manager.db.update_patchset_status(
        id="ps1@kernel.org",
        status=PatchsetStatus.DOWNLOADED,
        downloaded_at="2026-08-30T11:00:00Z",
    )

    pipeline.b4_client.fetch_thread = MagicMock()

    # Run download for ps1
    res = pipeline.run(run_id, target_ids=["ps1@kernel.org"])

    # Should be skipped, no b4 call
    assert pipeline.b4_client.fetch_thread.call_count == 0
    assert res.downloaded_count == 0


def test_download_pipeline_force_download(download_fixture, tmp_path: Path):
    pipeline, run_id, run_dir = download_fixture

    pipeline.session_manager.db.update_patchset_status(
        id="ps1@kernel.org",
        status=PatchsetStatus.DOWNLOADED,
        downloaded_at="2026-08-30T11:00:00Z",
    )

    fake_mbox = tmp_path / "test.mbx"
    fake_mbox.write_text("From ...", encoding="utf-8")
    pipeline.b4_client.fetch_thread = MagicMock(return_value=fake_mbox)
    pipeline.mbox_parser.parse = MagicMock(
        return_value=ParsedPatchset(
            id="ps1@kernel.org",
            title="[PATCH 1/1] mm: fix alloc",
            total_patches=1,
            patches=[
                ParsedPatch(
                    index=1,
                    total=1,
                    subject="[PATCH 1/1] mm: fix alloc",
                    author="Alice <alice@kernel.org>",
                    date="2026-08-30T10:00:00Z",
                    message_id="ps1@kernel.org",
                    commit_message="Fix",
                    diff="diff",
                )
            ],
        )
    )

    res = pipeline.run(run_id, target_ids=["ps1@kernel.org"], force=True)
    assert pipeline.b4_client.fetch_thread.call_count == 1
    assert res.downloaded_count == 1


def test_download_pipeline_analyzed_patchset_keeps_analyzed_status(
    download_fixture, tmp_path: Path
):
    pipeline, run_id, run_dir = download_fixture

    # Pre-set ps2 as analyzed with existing report
    pipeline.session_manager.db.update_patchset_status(
        id="ps2@kernel.org",
        status=PatchsetStatus.ANALYZED,
        downloaded_at="2026-08-30T11:00:00Z",
    )
    report_file = pipeline.session_manager.get_report_path(
        "ps2@kernel.org", "2026-08-30T12:00:00Z"
    )
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text("# Deep analysis report", encoding="utf-8")

    # ps2.date is 12:00:00Z > downloaded_at 11:00:00Z -> new reply detected!
    fake_mbox = tmp_path / "test2.mbx"
    fake_mbox.write_text("From ...", encoding="utf-8")
    pipeline.b4_client.fetch_thread = MagicMock(return_value=fake_mbox)
    pipeline.mbox_parser.parse = MagicMock(
        return_value=ParsedPatchset(
            id="ps2@kernel.org",
            title="[PATCH 1/1] net: fix sock",
            total_patches=1,
            patches=[
                ParsedPatch(
                    index=1,
                    total=1,
                    subject="[PATCH 1/1] net: fix sock",
                    author="Bob <bob@kernel.org>",
                    date="2026-08-30T12:00:00Z",
                    message_id="ps2@kernel.org",
                    commit_message="Fix sock",
                    diff="diff",
                )
            ],
        )
    )

    res = pipeline.run(run_id, target_ids=["ps2@kernel.org"])
    assert res.downloaded_count == 1

    # Check that status in DB remains ANALYZED!
    record = pipeline.session_manager.db.get_patchset("ps2@kernel.org")
    assert record.status == PatchsetStatus.ANALYZED
    assert record.downloaded_at is not None
    assert record.downloaded_at > "2026-08-30T11:00:00Z"
