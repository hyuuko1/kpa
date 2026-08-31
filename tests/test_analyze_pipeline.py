from pathlib import Path
from unittest.mock import patch
import pytest
from kp.config import load_config
from kp.storage.session import SessionManager
from kp.core.analyze_pipeline import AnalyzePipeline
from kp.adapters.agent import BaseAgentRunner, AgentExecutionError


class DummyRunner(BaseAgentRunner):
    def __init__(self, should_fail: bool = False, delay: float = 0.0):
        super().__init__(cmd="dummy")
        self.should_fail = should_fail
        self.delay = delay
        self.called_with = []

    def check_available(self) -> bool:
        return True

    def run_analysis(
        self,
        patchset_dir: Path,
        report_output_path: Path,
        kernel_path: Path | str | None = None,
        skill_name: str = "kernel-patch-analyzer",
        custom_prompt: str | None = None,
    ) -> None:
        import time

        if self.delay > 0:
            time.sleep(self.delay)
        self.called_with.append(
            (patchset_dir, report_output_path, kernel_path, custom_prompt)
        )
        if self.should_fail:
            raise AgentExecutionError("Analysis failed")
        report_output_path.parent.mkdir(parents=True, exist_ok=True)
        report_output_path.write_text("# Success Report", encoding="utf-8")


def test_analyze_pipeline_empty_targets_returns_empty(tmp_path):
    sm = SessionManager(tmp_path)
    cfg = load_config(None)
    cfg.storage.data_dir = str(tmp_path)
    pipeline = AnalyzePipeline(cfg, sm)

    res = pipeline.run(target_ids=[])
    assert res.total_count == 0
    assert res.success_count == 0
    assert res.failed_count == 0
    assert len(res.analyses) == 0


def test_analyze_pipeline_dry_run_and_integrity_check(tmp_path):
    sm = SessionManager(tmp_path)

    # Valid patchset 1
    p1 = sm.get_patchset_dir("msg_1")
    p1.mkdir(parents=True)
    (p1 / "meta.json").write_text('{"msgid": "<msg_1>"}', encoding="utf-8")
    (p1 / "00-cover-letter.md").write_text("Cover", encoding="utf-8")
    (p1 / "patches").mkdir()
    (p1 / "patches" / "0001.patch").write_text("Diff", encoding="utf-8")

    # Corrupted patchset 2 (invalid JSON)
    p2 = sm.get_patchset_dir("msg_2")
    p2.mkdir(parents=True)
    (p2 / "meta.json").write_text("invalid json content", encoding="utf-8")

    # Corrupted patchset 3 (declared cover letter missing)
    p3 = sm.get_patchset_dir("msg_3")
    p3.mkdir(parents=True)
    (p3 / "meta.json").write_text(
        '{"msgid": "<msg_3>", "has_cover_letter": true}', encoding="utf-8"
    )

    cfg = load_config(None)
    cfg.storage.data_dir = str(tmp_path)
    pipeline = AnalyzePipeline(cfg, sm)

    res = pipeline.run(target_ids=["<msg_1>", "<msg_2>", "<msg_3>"], dry_run=True)
    assert res.total_count == 3
    assert res.success_count == 0
    assert res.failed_count == 2
    assert res.analyses[0].sanitized_id == "msg_1"
    assert res.analyses[0].status == "skipped"
    assert res.analyses[1].sanitized_id == "msg_2"
    assert res.analyses[1].status == "failed"
    assert "meta.json" in (res.analyses[1].error_message or "")
    assert res.analyses[2].sanitized_id == "msg_3"
    assert res.analyses[2].status == "failed"
    assert "00-cover-letter.md" in (res.analyses[2].error_message or "")


def test_analyze_pipeline_successful_run(tmp_path):
    sm = SessionManager(tmp_path)

    p1 = sm.get_patchset_dir("msg_1")
    p1.mkdir(parents=True)
    (p1 / "meta.json").write_text('{"msgid": "<msg_1>"}', encoding="utf-8")
    (p1 / "00-cover-letter.md").write_text("Cover", encoding="utf-8")
    (p1 / "patches").mkdir()

    cfg = load_config(None)
    cfg.storage.data_dir = str(tmp_path)
    dummy_runner = DummyRunner(should_fail=False)
    pipeline = AnalyzePipeline(cfg, sm)

    res = pipeline.run(target_ids=["msg_1"], runner_override=dummy_runner)
    assert res.total_count == 1
    assert res.success_count == 1
    assert res.failed_count == 0
    assert res.analyses[0].status == "success"
    assert res.analyses[0].report_path.exists()
    assert res.analyses[0].duration_seconds >= 0.0


def test_analyze_pipeline_failed_run(tmp_path):
    sm = SessionManager(tmp_path)

    p1 = sm.get_patchset_dir("msg_1")
    p1.mkdir(parents=True)
    (p1 / "meta.json").write_text('{"msgid": "<msg_1>"}', encoding="utf-8")

    cfg = load_config(None)
    cfg.storage.data_dir = str(tmp_path)
    dummy_runner = DummyRunner(should_fail=True)
    pipeline = AnalyzePipeline(cfg, sm)

    res = pipeline.run(target_ids=["msg_1"], runner_override=dummy_runner)
    assert res.total_count == 1
    assert res.success_count == 0
    assert res.failed_count == 1
    assert res.analyses[0].status == "failed"
    assert "Analysis failed" in res.analyses[0].error_message


def test_analyze_pipeline_target_ids_filtering(tmp_path):
    sm = SessionManager(tmp_path)

    p1 = sm.get_patchset_dir("msg_1")
    p1.mkdir(parents=True)
    (p1 / "meta.json").write_text('{"msgid": "<msg_1>"}', encoding="utf-8")

    p2 = sm.get_patchset_dir("msg_2")
    p2.mkdir(parents=True)
    (p2 / "meta.json").write_text('{"msgid": "<msg_2>"}', encoding="utf-8")

    cfg = load_config(None)
    cfg.storage.data_dir = str(tmp_path)
    dummy_runner = DummyRunner(should_fail=False)
    pipeline = AnalyzePipeline(cfg, sm)

    res = pipeline.run(target_ids=["<msg_2>"], runner_override=dummy_runner)
    assert res.total_count == 1
    assert res.analyses[0].sanitized_id == "msg_2"
    assert len(dummy_runner.called_with) == 1
    assert dummy_runner.called_with[0][0] == p2


def test_analyze_pipeline_target_id_not_found(tmp_path):
    sm = SessionManager(tmp_path)

    cfg = load_config(None)
    cfg.storage.data_dir = str(tmp_path)
    dummy_runner = DummyRunner(should_fail=False)
    pipeline = AnalyzePipeline(cfg, sm)

    res = pipeline.run(target_ids=["nonexistent_id"], runner_override=dummy_runner)
    assert res.total_count == 1
    assert res.failed_count == 1
    assert res.analyses[0].status == "failed"
    assert "not found or not downloaded yet" in res.analyses[0].error_message


def test_analyze_pipeline_concurrency(tmp_path):
    sm = SessionManager(tmp_path)

    for i in range(3):
        p = sm.get_patchset_dir(f"msg_{i}")
        p.mkdir(parents=True)
        (p / "meta.json").write_text(f'{{"msgid": "<msg_{i}>"}}', encoding="utf-8")

    cfg = load_config(None)
    cfg.storage.data_dir = str(tmp_path)
    dummy_runner = DummyRunner(should_fail=False, delay=0.01)
    pipeline = AnalyzePipeline(cfg, sm)

    res = pipeline.run(
        target_ids=["msg_0", "msg_1", "msg_2"],
        concurrency=3,
        runner_override=dummy_runner,
    )
    assert res.total_count == 3
    assert res.success_count == 3
    assert [a.sanitized_id for a in res.analyses] == ["msg_0", "msg_1", "msg_2"]


@patch("kp.core.analyze_pipeline.get_agent_runner")
def test_analyze_pipeline_agent_selection(mock_get_runner, tmp_path):
    sm = SessionManager(tmp_path)

    p1 = sm.get_patchset_dir("msg_1")
    p1.mkdir(parents=True)
    (p1 / "meta.json").write_text('{"msgid": "<msg_1>"}', encoding="utf-8")

    mock_runner = DummyRunner()
    mock_get_runner.return_value = mock_runner

    cfg = load_config(None)
    cfg.storage.data_dir = str(tmp_path)
    pipeline = AnalyzePipeline(cfg, sm)

    res = pipeline.run(target_ids=["msg_1"], agent_type="opencode")
    mock_get_runner.assert_called_once_with("opencode", cfg.agent)
    assert res.success_count == 1


def test_analyze_pipeline_skip_already_analyzed(tmp_path):
    sm = SessionManager(tmp_path)

    p1 = sm.get_patchset_dir("msg_1")
    p1.mkdir(parents=True)
    (p1 / "meta.json").write_text('{"msgid": "<msg_1>"}', encoding="utf-8")

    # 预先生成报告
    report_file = sm.get_report_path("msg_1")
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text("# Existing Report", encoding="utf-8")

    cfg = load_config(None)
    cfg.storage.data_dir = str(tmp_path)
    dummy_runner = DummyRunner(should_fail=False)
    pipeline = AnalyzePipeline(cfg, sm)

    res = pipeline.run(target_ids=["msg_1"], runner_override=dummy_runner)
    assert res.total_count == 1
    assert res.skipped_count == 1
    assert res.success_count == 0
    assert res.analyses[0].status == "skipped"
    assert res.analyses[0].error_message == "Already analyzed"
    assert len(dummy_runner.called_with) == 0


def test_analyze_pipeline_force_reanalyze(tmp_path):
    sm = SessionManager(tmp_path)

    p1 = sm.get_patchset_dir("msg_1")
    p1.mkdir(parents=True)
    (p1 / "meta.json").write_text('{"msgid": "<msg_1>"}', encoding="utf-8")

    # 预先生成报告
    report_file = sm.get_report_path("msg_1")
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text("# Old Report", encoding="utf-8")

    cfg = load_config(None)
    cfg.storage.data_dir = str(tmp_path)
    dummy_runner = DummyRunner(should_fail=False)
    pipeline = AnalyzePipeline(cfg, sm)

    res = pipeline.run(target_ids=["msg_1"], force=True, runner_override=dummy_runner)
    assert res.total_count == 1
    assert res.skipped_count == 0
    assert res.success_count == 1
    assert res.analyses[0].status == "success"
    assert len(dummy_runner.called_with) == 1


def test_analyze_pipeline_missing_kernel_path_raises_error(tmp_path):
    sm = SessionManager(tmp_path)

    p1 = sm.get_patchset_dir("msg_1")
    p1.mkdir(parents=True)
    (p1 / "meta.json").write_text('{"msgid": "<msg_1>"}', encoding="utf-8")
    (p1 / "00-cover-letter.md").write_text("Cover", encoding="utf-8")
    (p1 / "patches").mkdir()

    cfg = load_config(None)
    cfg.storage.data_dir = str(tmp_path)
    cfg.kernel.path = None  # Not configured
    dummy_runner = DummyRunner(should_fail=False)
    pipeline = AnalyzePipeline(cfg, sm)

    with pytest.raises(ValueError, match="Linux 内核代码路径"):
        pipeline.run(target_ids=["msg_1"], runner_override=dummy_runner)

    assert len(dummy_runner.called_with) == 0

    # Also test empty string
    cfg.kernel.path = "   "
    with pytest.raises(ValueError, match="Linux 内核代码路径"):
        pipeline.run(target_ids=["msg_1"], runner_override=dummy_runner)

    assert len(dummy_runner.called_with) == 0


def test_analyze_pipeline_passes_kernel_path_to_runner(tmp_path):
    sm = SessionManager(tmp_path)

    p1 = sm.get_patchset_dir("msg_1")
    p1.mkdir(parents=True)
    (p1 / "meta.json").write_text('{"msgid": "<msg_1>"}', encoding="utf-8")
    (p1 / "00-cover-letter.md").write_text("Cover", encoding="utf-8")
    (p1 / "patches").mkdir()

    cfg = load_config(None)
    cfg.storage.data_dir = str(tmp_path)
    cfg.kernel.path = "/custom/linux/code"
    dummy_runner = DummyRunner(should_fail=False)
    pipeline = AnalyzePipeline(cfg, sm)

    res = pipeline.run(target_ids=["msg_1"], runner_override=dummy_runner)
    assert res.success_count == 1
    assert len(dummy_runner.called_with) == 1
    assert dummy_runner.called_with[0][2] == "/custom/linux/code"


def test_analyze_pipeline_passes_custom_prompt(tmp_path):
    sm = SessionManager(tmp_path)

    p1 = sm.get_patchset_dir("msg_1")
    p1.mkdir(parents=True)
    (p1 / "meta.json").write_text('{"msgid": "<msg_1>"}', encoding="utf-8")
    (p1 / "00-cover-letter.md").write_text("Cover", encoding="utf-8")
    (p1 / "patches").mkdir()

    cfg = load_config(None)
    cfg.storage.data_dir = str(tmp_path)
    cfg.kernel.path = "/custom/linux/code"
    dummy_runner = DummyRunner(should_fail=False)
    pipeline = AnalyzePipeline(cfg, sm)

    res = pipeline.run(
        target_ids=["msg_1"],
        custom_prompt="Please check concurrency",
        runner_override=dummy_runner,
    )
    assert res.success_count == 1
    assert len(dummy_runner.called_with) == 1
    assert dummy_runner.called_with[0][3] == "Please check concurrency"


def test_analyze_pipeline_without_run_id_by_target_id(tmp_path):
    sm = SessionManager(tmp_path)
    # Prepare global patchset
    p1 = sm.get_patchset_dir("target_ps1@kernel.org", "2026-08-30T10:00:00Z")
    p1.mkdir(parents=True)
    (p1 / "meta.json").write_text(
        '{"msgid": "<target_ps1@kernel.org>"}', encoding="utf-8"
    )
    (p1 / "00-cover-letter.md").write_text("Cover", encoding="utf-8")
    (p1 / "patches").mkdir()

    cfg = load_config(None)
    cfg.storage.data_dir = str(tmp_path)
    cfg.kernel.path = "/custom/linux/code"
    dummy_runner = DummyRunner(should_fail=False)
    pipeline = AnalyzePipeline(cfg, sm)

    res = pipeline.run(
        target_ids=["target_ps1@kernel.org"], runner_override=dummy_runner
    )
    assert res.total_count == 1
    assert res.success_count == 1
    assert res.analyses[0].sanitized_id == "target_ps1@kernel.org"


def test_analyze_pipeline_without_run_id_by_reviews(tmp_path):
    import json

    sm = SessionManager(tmp_path)
    # Prepare global patchset
    p1 = sm.get_patchset_dir("rev_ps1@kernel.org", "2026-08-30T10:00:00Z")
    p1.mkdir(parents=True)
    (p1 / "meta.json").write_text('{"msgid": "<rev_ps1@kernel.org>"}', encoding="utf-8")
    (p1 / "00-cover-letter.md").write_text("Cover", encoding="utf-8")
    (p1 / "patches").mkdir()

    cfg = load_config(None)
    cfg.storage.data_dir = str(tmp_path)
    cfg.kernel.path = "/custom/linux/code"
    dummy_runner = DummyRunner(should_fail=False)
    pipeline = AnalyzePipeline(cfg, sm)

    reviews_json = json.dumps(
        [
            {
                "id": "rev_ps1@kernel.org",
                "score": 9,
                "recommend": True,
                "reason": "urgent",
            },
            {
                "id": "rev_ps2@kernel.org",
                "score": 3,
                "recommend": False,
                "reason": "trivial",
            },
        ]
    )
    res = pipeline.run(
        reviews_content=reviews_json, min_score=7, runner_override=dummy_runner
    )
    assert res.total_count == 1
    assert res.success_count == 1
    assert res.analyses[0].sanitized_id == "rev_ps1@kernel.org"


def test_analyze_pipeline_not_downloaded_fails(tmp_path):
    sm = SessionManager(tmp_path)
    cfg = load_config(None)
    cfg.storage.data_dir = str(tmp_path)
    cfg.kernel.path = "/custom/linux/code"
    dummy_runner = DummyRunner(should_fail=False)
    pipeline = AnalyzePipeline(cfg, sm)

    res = pipeline.run(
        target_ids=["nonexistent_ps@kernel.org"], runner_override=dummy_runner
    )
    assert res.total_count == 1
    assert res.failed_count == 1
    assert "not found or not downloaded yet" in res.analyses[0].error_message
