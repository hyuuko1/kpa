from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
from click.testing import CliRunner
import pytest

from kp.cli import main
from kp.models import RawMessage
from kp.adapters.lore import LoreExecutionError


def test_cli_fetch_success(tmp_path: Path):
    runner = CliRunner()
    fake_raw = [
        RawMessage(
            m="m1@test",
            s="[PATCH] mm: sample fix",
            f=[["Author", "a@b.com"]],
            dt="2026-08-30T10:00:00Z",
        )
    ]
    with patch("kp.adapters.lore.LoreClient.query", return_value=fake_raw):
        result = runner.invoke(main, ["fetch", "--query", "l:linux-mm AND d:2.hours.ago.."])
        assert result.exit_code == 0
        assert "抓取完成" in result.output
        assert "prompt.md" in result.output
        assert "运行 ID:" in result.output
        assert "原始邮件数: 1" in result.output
        assert "聚合 Patchset 数: 1" in result.output


def test_cli_fetch_safety_violation():
    runner = CliRunner()
    # Big granularity prohibited
    result = runner.invoke(main, ["fetch", "--query", "l:linux-mm AND d:1.day.ago.."])
    assert result.exit_code != 0
    assert "安全限制" in result.output

    # Missing d: filter prohibited
    result2 = runner.invoke(main, ["fetch", "--query", "l:linux-mm.kvack.org"])
    assert result2.exit_code != 0
    assert "安全限制" in result2.output



def test_cli_fetch_lore_error():
    runner = CliRunner()
    with patch("kp.adapters.lore.LoreClient.query", side_effect=LoreExecutionError("lei execution failed")):
        result = runner.invoke(main, ["fetch", "--query", "l:linux-mm AND d:1.hours.ago.."])
        assert result.exit_code == 1
        assert "lei execution failed" in result.output


def test_cli_fetch_unexpected_error():
    runner = CliRunner()
    with patch("kp.core.pipeline.FetchPipeline.run", side_effect=RuntimeError("unexpected disk error")):
        result = runner.invoke(main, ["fetch", "--query", "l:linux-mm AND d:1.hours.ago.."])
        assert result.exit_code == 1
        assert "未知错误: unexpected disk error" in result.output


def test_cli_custom_config(tmp_path: Path):
    config_file = tmp_path / "custom_config.toml"
    custom_data_dir = tmp_path / "custom_runs"
    config_file.write_text(
        f"""
[safety]
max_time_span_minutes = 60
require_time_filter = true

[lore]
inbox_url = "https://lore.kernel.org/all/"
timeout_seconds = 30

[storage]
data_dir = "{custom_data_dir.as_posix()}"
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    fake_raw = [
        RawMessage(
            m="m1@test",
            s="[PATCH] mm: sample fix",
            f=[["Author", "a@b.com"]],
            dt="2026-08-30T10:00:00Z",
        )
    ]
    with patch("kp.adapters.lore.LoreClient.query", return_value=fake_raw):
        result = runner.invoke(
            main,
            ["-c", str(config_file), "fetch", "-q", "l:linux-mm AND d:30.minutes.ago.."],
        )
        assert result.exit_code == 0
        assert "抓取完成" in result.output
        assert custom_data_dir.exists()


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "Linux Kernel Patch Fetcher & AI Analyzer" in result.output
    assert "fetch" in result.output
