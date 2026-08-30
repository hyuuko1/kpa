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
    assert "download" in result.output


def test_cli_download_missing_run_id():
    runner = CliRunner()
    result = runner.invoke(main, ["download"])
    assert result.exit_code != 0
    assert "Missing option" in result.output or "--run-id" in result.output


def test_cli_download_missing_targets_and_input():
    runner = CliRunner()
    result = runner.invoke(main, ["download", "--run-id", "20260830_120000_abc123"])
    assert result.exit_code == 1
    assert "请至少指定 --id 或 --input 参数" in result.output


def test_cli_download_by_id_success(tmp_path: Path):
    from kp.core.download_pipeline import DownloadResult

    runner = CliRunner()
    fake_result = DownloadResult(
        run_id="20260830_120000_abc123",
        run_dir=tmp_path,
        downloaded_count=2,
        stage3_prompt_path=tmp_path / "stage3_prompt.md",
    )
    with patch("kp.core.download_pipeline.DownloadPipeline.run", return_value=fake_result) as mock_run:
        result = runner.invoke(
            main,
            [
                "download",
                "--run-id",
                "20260830_120000_abc123",
                "--id",
                "id1@test",
                "--id",
                "id2@test",
                "--min-score",
                "85",
            ],
        )
        assert result.exit_code == 0
        assert "下载与结构化解析完成" in result.output
        assert "运行 ID: 20260830_120000_abc123" in result.output
        assert "成功下载并解析 Patchset 数: 2" in result.output
        assert "stage3_prompt.md" in result.output
        mock_run.assert_called_once_with(
            run_id="20260830_120000_abc123",
            target_ids=["id1@test", "id2@test"],
            reviews_content=None,
            min_score=85,
        )


def test_cli_download_by_input_file_success(tmp_path: Path):
    from kp.core.download_pipeline import DownloadResult

    reviews_file = tmp_path / "reviews.json"
    reviews_content = '[{"id": "msg1@test", "score": 90, "recommend": true, "summary": "good"}]'
    reviews_file.write_text(reviews_content, encoding="utf-8")

    runner = CliRunner()
    fake_result = DownloadResult(
        run_id="20260830_120000_abc123",
        run_dir=tmp_path,
        downloaded_count=1,
        stage3_prompt_path=tmp_path / "stage3_prompt.md",
    )
    with patch("kp.core.download_pipeline.DownloadPipeline.run", return_value=fake_result) as mock_run:
        result = runner.invoke(
            main,
            [
                "download",
                "--run-id",
                "20260830_120000_abc123",
                "--input",
                str(reviews_file),
            ],
        )
        assert result.exit_code == 0
        assert "下载与结构化解析完成" in result.output
        mock_run.assert_called_once_with(
            run_id="20260830_120000_abc123",
            target_ids=None,
            reviews_content=reviews_content,
            min_score=70,
        )


def test_cli_download_by_input_stdin_success(tmp_path: Path):
    from kp.core.download_pipeline import DownloadResult

    stdin_data = '[{"id": "msg1@test", "score": 95, "recommend": true, "summary": "excellent"}]'

    runner = CliRunner()
    fake_result = DownloadResult(
        run_id="20260830_120000_abc123",
        run_dir=tmp_path,
        downloaded_count=1,
        stage3_prompt_path=tmp_path / "stage3_prompt.md",
    )
    with patch("kp.core.download_pipeline.DownloadPipeline.run", return_value=fake_result) as mock_run:
        result = runner.invoke(
            main,
            [
                "download",
                "--run-id",
                "20260830_120000_abc123",
                "--input",
                "-",
            ],
            input=stdin_data,
        )
        assert result.exit_code == 0
        assert "下载与结构化解析完成" in result.output
        mock_run.assert_called_once_with(
            run_id="20260830_120000_abc123",
            target_ids=None,
            reviews_content=stdin_data,
            min_score=70,
        )


def test_cli_download_input_file_not_found(tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "download",
            "--run-id",
            "20260830_120000_abc123",
            "--input",
            str(tmp_path / "nonexistent.json"),
        ],
    )
    assert result.exit_code == 1
    assert "评审结果文件不存在" in result.output


def test_cli_download_value_error():
    runner = CliRunner()
    with patch(
        "kp.core.download_pipeline.DownloadPipeline.run",
        side_effect=ValueError("解析 AI 评审结果 JSON 失败: Expecting property name"),
    ):
        result = runner.invoke(
            main,
            ["download", "--run-id", "20260830_120000_abc123", "--id", "id1@test"],
        )
        assert result.exit_code == 1
        assert "解析 AI 评审结果 JSON 失败" in result.output


def test_cli_download_file_not_found_error():
    runner = CliRunner()
    with patch(
        "kp.core.download_pipeline.DownloadPipeline.run",
        side_effect=FileNotFoundError("patchsets.json not found in /some/path"),
    ):
        result = runner.invoke(
            main,
            ["download", "--run-id", "20260830_120000_abc123", "--id", "id1@test"],
        )
        assert result.exit_code == 1
        assert "会话或文件不存在" in result.output


def test_cli_download_b4_error():
    from kp.adapters.b4 import B4ExecutionError

    runner = CliRunner()
    with patch(
        "kp.core.download_pipeline.DownloadPipeline.run",
        side_effect=B4ExecutionError("b4 command timed out"),
    ):
        result = runner.invoke(
            main,
            ["download", "--run-id", "20260830_120000_abc123", "--id", "id1@test"],
        )
        assert result.exit_code == 1
        assert "b4 command timed out" in result.output


def test_cli_download_unexpected_error():
    runner = CliRunner()
    with patch(
        "kp.core.download_pipeline.DownloadPipeline.run",
        side_effect=RuntimeError("unexpected storage crash"),
    ):
        result = runner.invoke(
            main,
            ["download", "--run-id", "20260830_120000_abc123", "--id", "id1@test"],
        )
        assert result.exit_code == 1
        assert "未知错误: unexpected storage crash" in result.output


def test_cli_download_help():
    runner = CliRunner()
    result = runner.invoke(main, ["download", "--help"])
    assert result.exit_code == 0
    assert "--run-id" in result.output
    assert "--id" in result.output
    assert "--input" in result.output
    assert "--min-score" in result.output

