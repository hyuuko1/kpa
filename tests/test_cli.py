from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
from click.testing import CliRunner

from kp.cli import main
from kp.models import RawMessage, AnalyzeRunResult, PatchsetAnalysis
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
        result = runner.invoke(
            main, ["fetch", "--query", "l:linux-mm AND dt:2.hours.ago.."]
        )
        assert result.exit_code == 0
        assert "抓取完成" in result.output
        assert "kernel-patch-analyzer" in result.output
        assert "运行 ID:" in result.output
        assert "原始邮件数: 1" in result.output
        assert "聚合 Patchset 数: 1" in result.output


def test_cli_fetch_safety_violation():
    runner = CliRunner()
    # Big granularity prohibited
    result = runner.invoke(main, ["fetch", "--query", "l:linux-mm AND dt:1.week.ago.."])
    assert result.exit_code != 0
    assert "安全限制" in result.output

    # Missing dt: filter prohibited
    result2 = runner.invoke(main, ["fetch", "--query", "l:linux-mm.kvack.org"])
    assert result2.exit_code != 0
    assert "安全限制" in result2.output


def test_cli_fetch_lore_error():
    runner = CliRunner()
    with patch(
        "kp.adapters.lore.LoreClient.query",
        side_effect=LoreExecutionError("lei execution failed"),
    ):
        result = runner.invoke(
            main, ["fetch", "--query", "l:linux-mm AND dt:1.hours.ago.."]
        )
        assert result.exit_code == 1
        assert "lei execution failed" in result.output


def test_cli_fetch_unexpected_error():
    runner = CliRunner()
    with patch(
        "kp.core.pipeline.FetchPipeline.run",
        side_effect=RuntimeError("unexpected disk error"),
    ):
        result = runner.invoke(
            main, ["fetch", "--query", "l:linux-mm AND dt:1.hours.ago.."]
        )
        assert result.exit_code == 1
        assert "未知错误: unexpected disk error" in result.output


def test_cli_custom_config(tmp_path: Path):
    config_file = tmp_path / "custom_config.toml"
    custom_data_dir = tmp_path / "custom_runs"
    config_file.write_text(
        f"""
[safety]
max_time_span_hours = 2
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
            [
                "-c",
                str(config_file),
                "fetch",
                "-q",
                "l:linux-mm AND dt:30.minutes.ago..",
            ],
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
    assert "analyze" in result.output


def test_cli_download_missing_targets_and_input():
    runner = CliRunner()
    result = runner.invoke(main, ["download"])
    assert result.exit_code == 1
    assert "请至少指定 --id 或 --input 参数" in result.output


def test_cli_download_by_id_success(tmp_path: Path):
    from kp.core.download_pipeline import DownloadResult

    runner = CliRunner()
    fake_result = DownloadResult(
        downloaded_count=2,
    )
    with patch(
        "kp.core.download_pipeline.DownloadPipeline.run", return_value=fake_result
    ) as mock_run:
        result = runner.invoke(
            main,
            [
                "download",
                "--id",
                "id1@test",
                "--id",
                "id2@test",
                "--min-score",
                "8",
            ],
        )
        assert result.exit_code == 0
        assert "下载与结构化解析完成" in result.output
        assert "成功下载并解析 Patchset 数: 2" in result.output
        assert (
            "kp analyze -i <reviews.json> 或 kp analyze --id <target_id>"
            in result.output
        )
        mock_run.assert_called_once_with(
            target_ids=["id1@test", "id2@test"],
            reviews_content=None,
            min_score=8,
            force=False,
        )


def test_cli_download_by_input_file_success(tmp_path: Path):
    from kp.core.download_pipeline import DownloadResult

    reviews_file = tmp_path / "reviews.json"
    reviews_content = (
        '[{"id": "msg1@test", "score": 90, "recommend": true, "summary": "good"}]'
    )
    reviews_file.write_text(reviews_content, encoding="utf-8")

    runner = CliRunner()
    fake_result = DownloadResult(
        downloaded_count=1,
    )
    with patch(
        "kp.core.download_pipeline.DownloadPipeline.run", return_value=fake_result
    ) as mock_run:
        result = runner.invoke(
            main,
            [
                "download",
                "--input",
                str(reviews_file),
            ],
        )
        assert result.exit_code == 0
        assert "下载与结构化解析完成" in result.output
        assert "kp analyze" in result.output
        mock_run.assert_called_once_with(
            target_ids=None,
            reviews_content=reviews_content,
            min_score=7,
            force=False,
        )


def test_cli_download_by_input_stdin_success(tmp_path: Path):
    from kp.core.download_pipeline import DownloadResult

    stdin_data = (
        '[{"id": "msg1@test", "score": 9, "recommend": true, "reason": "excellent"}]'
    )

    runner = CliRunner()
    fake_result = DownloadResult(
        downloaded_count=1,
    )
    with patch(
        "kp.core.download_pipeline.DownloadPipeline.run", return_value=fake_result
    ) as mock_run:
        result = runner.invoke(
            main,
            [
                "download",
                "--input",
                "-",
            ],
            input=stdin_data,
        )
        assert result.exit_code == 0
        assert "下载与结构化解析完成" in result.output
        assert "kp analyze" in result.output
        mock_run.assert_called_once_with(
            target_ids=None,
            reviews_content=stdin_data,
            min_score=7,
            force=False,
        )


def test_cli_download_input_file_not_found(tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "download",
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
            ["download", "--id", "id1@test"],
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
            ["download", "--id", "id1@test"],
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
            ["download", "--id", "id1@test"],
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
            ["download", "--id", "id1@test"],
        )
        assert result.exit_code == 1
        assert "未知错误: unexpected storage crash" in result.output


def test_cli_download_help():
    runner = CliRunner()
    result = runner.invoke(main, ["download", "--help"])
    assert result.exit_code == 0
    assert "--run-id" not in result.output
    assert "--id" in result.output
    assert "--input" in result.output
    assert "--min-score" in result.output


def test_cli_analyze_help():
    runner = CliRunner()
    result = runner.invoke(main, ["analyze", "--help"])
    assert result.exit_code == 0
    assert "--run-id" not in result.output
    assert "--id" in result.output
    assert "--input" in result.output
    assert "--min-score" in result.output
    assert "--agent" in result.output
    assert "--concurrency" in result.output
    assert "--dry-run" in result.output


def test_cli_analyze_missing_targets_and_input():
    runner = CliRunner()
    result = runner.invoke(main, ["analyze"])
    assert result.exit_code == 1
    assert "请至少指定 --id 或 --input 参数" in result.output


def test_cli_analyze_by_input_file_success(tmp_path: Path):
    from kp.models import AnalyzeRunResult, PatchsetAnalysis

    reviews_file = tmp_path / "reviews.json"
    reviews_content = (
        '[{"id": "p1@test", "score": 9, "recommend": true, "reason": "good"}]'
    )
    reviews_file.write_text(reviews_content, encoding="utf-8")

    runner = CliRunner()
    fake_res = AnalyzeRunResult(
        analyses=[
            PatchsetAnalysis(
                msgid="<p1@test>",
                sanitized_id="p1_test",
                status="success",
                report_path=tmp_path / "reports" / "p1_test.md",
                duration_seconds=3.2,
            )
        ],
        total_count=1,
        success_count=1,
        failed_count=0,
    )
    with patch(
        "kp.core.analyze_pipeline.AnalyzePipeline.run", return_value=fake_res
    ) as mock_run:
        result = runner.invoke(
            main,
            [
                "analyze",
                "-i",
                str(reviews_file),
                "--min-score",
                "8",
            ],
        )
        assert result.exit_code == 0
        assert "深度技术分析完成" in result.output
        assert "成功分析数: 1" in result.output
        mock_run.assert_called_once_with(
            target_ids=None,
            reviews_content=reviews_content,
            min_score=8,
            agent_type=None,
            concurrency=None,
            dry_run=False,
            force=False,
            custom_prompt=None,
        )


def test_cli_analyze_dry_run_success(tmp_path: Path):
    from kp.models import AnalyzeRunResult, PatchsetAnalysis

    runner = CliRunner()
    fake_res = AnalyzeRunResult(
        analyses=[
            PatchsetAnalysis(
                msgid="<p1@test>",
                sanitized_id="p1_test",
                status="skipped",
                report_path=tmp_path / "reports" / "p1_test.md",
                duration_seconds=0.0,
            )
        ],
        total_count=1,
        success_count=0,
        failed_count=0,
    )
    with patch(
        "kp.core.analyze_pipeline.AnalyzePipeline.run", return_value=fake_res
    ) as mock_run:
        result = runner.invoke(
            main,
            ["analyze", "--id", "p1@test", "--dry-run"],
        )
        assert result.exit_code == 0
        assert "完整性检查完成" in result.output
        assert "p1_test" in result.output
        mock_run.assert_called_once_with(
            target_ids=["p1@test"],
            reviews_content=None,
            min_score=7,
            agent_type=None,
            concurrency=None,
            dry_run=True,
            force=False,
            custom_prompt=None,
        )


def test_cli_analyze_success(tmp_path: Path):
    from kp.models import AnalyzeRunResult, PatchsetAnalysis

    runner = CliRunner()
    fake_res = AnalyzeRunResult(
        analyses=[
            PatchsetAnalysis(
                msgid="<p1@test>",
                sanitized_id="p1_test",
                status="success",
                report_path=tmp_path / "reports" / "p1_test.md",
                duration_seconds=3.2,
            )
        ],
        total_count=1,
        success_count=1,
        failed_count=0,
    )
    with patch(
        "kp.core.analyze_pipeline.AnalyzePipeline.run", return_value=fake_res
    ) as mock_run:
        result = runner.invoke(
            main,
            [
                "analyze",
                "--id",
                "p1@test",
                "--agent",
                "opencode",
                "--concurrency",
                "2",
            ],
        )
        assert result.exit_code == 0
        assert "深度技术分析完成" in result.output
        assert "成功分析数: 1" in result.output
        assert "p1_test.md" in result.output
        mock_run.assert_called_once_with(
            target_ids=["p1@test"],
            reviews_content=None,
            min_score=7,
            agent_type="opencode",
            concurrency=2,
            dry_run=False,
            force=False,
            custom_prompt=None,
        )


def test_cli_analyze_partial_failure(tmp_path: Path):
    from kp.models import AnalyzeRunResult, PatchsetAnalysis

    runner = CliRunner()
    fake_res = AnalyzeRunResult(
        analyses=[
            PatchsetAnalysis(
                msgid="<p1@test>",
                sanitized_id="p1_test",
                status="success",
                report_path=tmp_path / "reports" / "p1_test.md",
                duration_seconds=3.2,
            ),
            PatchsetAnalysis(
                msgid="<p2@test>",
                sanitized_id="p2_test",
                status="failed",
                error_message="Agent execution timeout",
                duration_seconds=10.0,
            ),
        ],
        total_count=2,
        success_count=1,
        failed_count=1,
    )
    with patch("kp.core.analyze_pipeline.AnalyzePipeline.run", return_value=fake_res):
        result = runner.invoke(
            main,
            ["analyze", "--id", "p1@test", "--id", "p2@test"],
        )
        assert result.exit_code == 0
        assert "深度技术分析完成" in result.output
        assert "成功分析数: 1" in result.output
        assert "失败分析数: 1" in result.output
        assert "Agent execution timeout" in result.output


def test_cli_analyze_file_not_found_error():
    runner = CliRunner()
    with patch(
        "kp.core.analyze_pipeline.AnalyzePipeline.run",
        side_effect=FileNotFoundError("Session 'nonexistent' not found"),
    ):
        result = runner.invoke(main, ["analyze", "--id", "p1@test"])
        assert result.exit_code == 1
        assert "会话或文件不存在" in result.output


def test_cli_analyze_value_error():
    runner = CliRunner()
    with patch(
        "kp.core.analyze_pipeline.AnalyzePipeline.run",
        side_effect=ValueError("Invalid agent type"),
    ):
        result = runner.invoke(main, ["analyze", "--id", "p1@test"])
        assert result.exit_code == 1
        assert "Invalid agent type" in result.output


def test_cli_analyze_agent_error():
    from kp.adapters.agent import AgentExecutionError

    runner = CliRunner()
    with patch(
        "kp.core.analyze_pipeline.AnalyzePipeline.run",
        side_effect=AgentExecutionError("Agent binary crashed"),
    ):
        result = runner.invoke(main, ["analyze", "--id", "p1@test"])
        assert result.exit_code == 1
        assert "Agent binary crashed" in result.output


def test_cli_analyze_unexpected_error():
    runner = CliRunner()
    with patch(
        "kp.core.analyze_pipeline.AnalyzePipeline.run",
        side_effect=RuntimeError("something unexpected"),
    ):
        result = runner.invoke(main, ["analyze", "--id", "p1@test"])
        assert result.exit_code == 1
        assert "未知错误: something unexpected" in result.output


def test_cli_analyze_with_skipped_and_force(tmp_path: Path):
    runner = CliRunner()
    fake_res = AnalyzeRunResult(
        analyses=[
            PatchsetAnalysis(
                msgid="<p1@test>",
                sanitized_id="p1_test",
                status="skipped",
                report_path=tmp_path / "reports" / "p1_test.md",
                error_message="Already analyzed",
                duration_seconds=0.0,
            ),
            PatchsetAnalysis(
                msgid="<p2@test>",
                sanitized_id="p2_test",
                status="success",
                report_path=tmp_path / "reports" / "p2_test.md",
                duration_seconds=2.5,
            ),
        ],
        total_count=2,
        success_count=1,
        failed_count=0,
        skipped_count=1,
    )
    with patch(
        "kp.core.analyze_pipeline.AnalyzePipeline.run", return_value=fake_res
    ) as mock_run:
        result = runner.invoke(
            main,
            ["analyze", "--id", "p1@test", "--id", "p2@test", "--force"],
        )
        assert result.exit_code == 0
        mock_run.assert_called_once()
        assert mock_run.call_args[1].get("force") is True
        assert "已跳过" in result.output or "跳过" in result.output
        assert "成功分析数: 1" in result.output
        assert "跳过分析数: 1" in result.output


def test_cli_analyze_missing_kernel_path_error(tmp_path: Path):
    data_dir = tmp_path
    session_dir = data_dir / "runs" / "20260830_120000" / "patchsets" / "p1"
    session_dir.mkdir(parents=True)
    (session_dir / "meta.json").write_text('{"msgid": "<p1>"}', encoding="utf-8")

    config_file = tmp_path / "no_kernel.toml"
    config_file.write_text(
        f"""
[storage]
data_dir = "{data_dir}"

[kernel]
path = ""
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    with patch("kp.core.analyze_pipeline.get_agent_runner") as mock_get_runner:
        result = runner.invoke(
            main,
            [
                "-c",
                str(config_file),
                "analyze",
                "--id",
                "p1@test",
            ],
        )
        assert result.exit_code == 1
        assert "未配置 Linux 内核代码路径" in result.output
        mock_get_runner.assert_not_called()


def test_cli_fetch_since_last_success(tmp_path: Path):
    from kp.core.pipeline import PipelineResult

    runner = CliRunner()
    fake_res = PipelineResult(
        run_id="20260830_120000",
        raw_count=1,
        patchset_count=1,
        run_dir=tmp_path,
    )
    with patch("kp.core.pipeline.FetchPipeline.run", return_value=fake_res) as mock_run:
        result = runner.invoke(main, ["fetch", "--query", "l:linux-mm", "--since-last"])
        assert result.exit_code == 0
        assert "增量巡检查询" in result.output
        assert "抓取完成" in result.output
        mock_run.assert_called_once_with("l:linux-mm", since_last=True)


def test_cli_download_force(tmp_path: Path):
    from kp.core.download_pipeline import DownloadResult

    runner = CliRunner()
    fake_result = DownloadResult(
        downloaded_count=1,
    )
    with patch(
        "kp.core.download_pipeline.DownloadPipeline.run", return_value=fake_result
    ) as mock_run:
        result = runner.invoke(
            main,
            ["download", "--id", "id1@test", "--force"],
        )
        assert result.exit_code == 0
        mock_run.assert_called_once_with(
            target_ids=["id1@test"],
            reviews_content=None,
            min_score=7,
            force=True,
        )


def test_cli_analyze_custom_prompt(tmp_path: Path):
    from kp.models import AnalyzeRunResult

    runner = CliRunner()
    fake_res = AnalyzeRunResult(
        analyses=[],
        total_count=0,
        success_count=0,
        failed_count=0,
    )
    with patch(
        "kp.core.analyze_pipeline.AnalyzePipeline.run", return_value=fake_res
    ) as mock_run:
        result = runner.invoke(
            main,
            ["analyze", "--id", "p1@test", "-p", "Check race conditions"],
        )
        assert result.exit_code == 0
        mock_run.assert_called_once()
        assert mock_run.call_args[1].get("custom_prompt") == "Check race conditions"


def test_cli_analyze_prompt_file(tmp_path: Path):
    from kp.models import AnalyzeRunResult

    pfile = tmp_path / "prompt.txt"
    pfile.write_text("Focus on lock correctness", encoding="utf-8")
    runner = CliRunner()
    fake_res = AnalyzeRunResult(
        analyses=[],
        total_count=0,
        success_count=0,
        failed_count=0,
    )
    with patch(
        "kp.core.analyze_pipeline.AnalyzePipeline.run", return_value=fake_res
    ) as mock_run:
        result = runner.invoke(
            main,
            ["analyze", "--id", "p1@test", "--prompt-file", str(pfile)],
        )
        assert result.exit_code == 0
        mock_run.assert_called_once()
        assert mock_run.call_args[1].get("custom_prompt") == "Focus on lock correctness"


def test_cli_verbose_logging(tmp_path: Path):
    from kp.core.pipeline import PipelineResult

    runner = CliRunner()
    fake_res = PipelineResult(
        run_id="20260830_120000",
        raw_count=1,
        patchset_count=1,
        run_dir=tmp_path,
    )
    with patch("kp.core.pipeline.FetchPipeline.run", return_value=fake_res):
        result = runner.invoke(
            main, ["-v", "fetch", "--query", "l:linux-mm AND dt:2.hours.ago.."]
        )
        assert result.exit_code == 0
        assert "抓取完成" in result.output
