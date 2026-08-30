from pathlib import Path
from unittest.mock import patch
import json

from kp.config import AppConfig
from kp.models import RawMessage
from kp.core.pipeline import FetchPipeline, PipelineResult


def test_fetch_pipeline_run(tmp_path: Path):
    config = AppConfig()
    config.storage.data_dir = str(tmp_path)
    pipeline = FetchPipeline(config)

    fake_raw = [
        RawMessage(
            m="m1@test",
            s="[PATCH] mm: sample",
            f=[["Author", "a@b.com"]],
            dt="2026-08-30T10:00:00Z",
        )
    ]

    with patch.object(pipeline.lore_client, "query", return_value=fake_raw):
        result = pipeline.run("l:linux-mm AND d:1.hours.ago..")
        assert isinstance(result, PipelineResult)
        assert result.raw_count == 1
        assert result.patchset_count == 1
        assert result.run_dir.exists()
        assert (result.run_dir / "patchsets.json").exists()
        assert (result.run_dir / "raw_metadata.json").exists()
        assert (result.run_dir / "manifest.json").exists()
        assert (result.run_dir / "prompt.md").exists()
        assert result.prompt_path == result.run_dir / "prompt.md"

        # Verify manifest content
        manifest_data = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest_data["run_id"] == result.run_id
        assert manifest_data["query"] == "l:linux-mm AND d:1.hours.ago.."
        assert manifest_data["total_raw_messages"] == 1
        assert manifest_data["total_patchsets"] == 1


def test_fetch_pipeline_empty_query(tmp_path: Path):
    config = AppConfig()
    config.storage.data_dir = str(tmp_path)
    pipeline = FetchPipeline(config)

    with patch.object(pipeline.lore_client, "query", return_value=[]):
        result = pipeline.run("l:linux-mm AND d:1.hours.ago..")
        assert result.raw_count == 0
        assert result.patchset_count == 0
        assert (result.run_dir / "manifest.json").exists()
        assert (result.run_dir / "patchsets.json").exists()
        assert (result.run_dir / "prompt.md").exists()


def test_fetch_pipeline_multi_patchset(tmp_path: Path):
    config = AppConfig()
    config.storage.data_dir = str(tmp_path)
    pipeline = FetchPipeline(config)

    fake_raw = [
        RawMessage(
            m="cov@test",
            s="[PATCH 0/2] mm: series intro",
            f=[["Author", "a@b.com"]],
            dt="2026-08-30T10:00:00Z",
        ),
        RawMessage(
            m="p1@test",
            s="[PATCH 1/2] mm: patch 1",
            f=[["Author", "a@b.com"]],
            dt="2026-08-30T10:01:00Z",
            refs=["cov@test"],
        ),
        RawMessage(
            m="p2@test",
            s="[PATCH 2/2] mm: patch 2",
            f=[["Author", "a@b.com"]],
            dt="2026-08-30T10:02:00Z",
            refs=["cov@test"],
        ),
        RawMessage(
            m="standalone@test",
            s="[PATCH] sched: fix bug",
            f=[["Other", "b@c.com"]],
            dt="2026-08-30T10:05:00Z",
        ),
    ]

    with patch.object(pipeline.lore_client, "query", return_value=fake_raw):
        result = pipeline.run("l:linux-mm AND d:1.hours.ago..")
        assert result.raw_count == 4
        assert result.patchset_count == 2
