import subprocess
from unittest.mock import MagicMock, patch
import pytest

from kp.adapters.agent import (
    AgentError,
    AgentExecutionError,
    AgentNotFoundError,
    AgentTimeoutError,
    AgyAgentRunner,
    BaseAgentRunner,
    OpenCodeAgentRunner,
    get_agent_runner,
)
from kp.config import AgentConfig


def test_exception_hierarchy():
    assert issubclass(AgentError, Exception)
    assert issubclass(AgentNotFoundError, AgentError)
    assert issubclass(AgentExecutionError, AgentError)
    assert issubclass(AgentTimeoutError, AgentError)
    assert issubclass(AgyAgentRunner, BaseAgentRunner)
    assert issubclass(OpenCodeAgentRunner, BaseAgentRunner)


def test_get_agent_runner():
    cfg = AgentConfig(
        default="agy", agy_cmd="agy", opencode_cmd="opencode", timeout_seconds=300
    )
    runner = get_agent_runner("agy", cfg)
    assert isinstance(runner, AgyAgentRunner)
    assert runner.cmd == "agy"
    assert runner.timeout_seconds == 300

    runner_oc = get_agent_runner("opencode", cfg)
    assert isinstance(runner_oc, OpenCodeAgentRunner)
    assert runner_oc.cmd == "opencode"
    assert runner_oc.timeout_seconds == 300

    # Case insensitivity
    runner_case = get_agent_runner("AGY", cfg)
    assert isinstance(runner_case, AgyAgentRunner)

    runner_oc_case = get_agent_runner("OpenCode", cfg)
    assert isinstance(runner_oc_case, OpenCodeAgentRunner)

    with pytest.raises(ValueError, match="Unsupported agent type"):
        get_agent_runner("unknown", cfg)


def test_agy_runner_check_available():
    with patch("shutil.which", return_value="/usr/bin/agy"):
        runner = AgyAgentRunner(cmd="agy")
        assert runner.check_available() is True

    with patch("shutil.which", return_value=None):
        runner = AgyAgentRunner(cmd="agy")
        assert runner.check_available() is False


def test_agy_runner_executable_not_found(tmp_path):
    with patch("shutil.which", return_value=None):
        runner = AgyAgentRunner(cmd="nonexistent_agy_cmd")
        with pytest.raises(
            AgentNotFoundError,
            match="Agent executable 'nonexistent_agy_cmd' not found in PATH",
        ):
            runner.run_analysis(tmp_path / "patchset", tmp_path / "report.md")


@patch("shutil.which", return_value="/usr/bin/agy")
@patch("subprocess.run")
def test_agy_runner_successful_execution(mock_run, mock_which, tmp_path):
    patchset_dir = tmp_path / "patchset"
    patchset_dir.mkdir()
    report_file = tmp_path / "report.md"

    def side_effect(cmd, **kwargs):
        report_file.write_text("# Successful Report", encoding="utf-8")
        return MagicMock(returncode=0, stdout="OK", stderr="")

    mock_run.side_effect = side_effect

    runner = AgyAgentRunner(cmd="agy", timeout_seconds=120)
    runner.run_analysis(patchset_dir, report_file)

    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0][0] == "agy"
    assert args[0][1] == "-p"
    assert "kernel-patch-analyzer" in args[0][2]
    assert str(patchset_dir.resolve()) in args[0][2]
    assert kwargs.get("timeout") == 120
    assert kwargs.get("capture_output") is True
    assert kwargs.get("text") is True


@patch("shutil.which", return_value="/usr/bin/agy")
@patch("subprocess.run")
def test_agy_runner_custom_skill(mock_run, mock_which, tmp_path):
    patchset_dir = tmp_path / "patchset"
    patchset_dir.mkdir()
    report_file = tmp_path / "report.md"

    def side_effect(cmd, **kwargs):
        report_file.write_text("# Report", encoding="utf-8")
        return MagicMock(returncode=0, stdout="OK", stderr="")

    mock_run.side_effect = side_effect

    runner = AgyAgentRunner(cmd="agy")
    runner.run_analysis(patchset_dir, report_file, skill_name="custom-skill")

    args, _ = mock_run.call_args
    assert "custom-skill" in args[0][2]


@patch("shutil.which", return_value="/usr/bin/agy")
@patch("subprocess.run")
def test_agy_runner_execution_failure(mock_run, mock_which, tmp_path):
    patchset_dir = tmp_path / "patchset"
    patchset_dir.mkdir()
    report_file = tmp_path / "report.md"
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="Something went wrong"
    )

    runner = AgyAgentRunner(cmd="agy")
    with pytest.raises(
        AgentExecutionError, match="Agent failed with exit code 1: Something went wrong"
    ):
        runner.run_analysis(patchset_dir, report_file)


@patch("shutil.which", return_value="/usr/bin/agy")
@patch("subprocess.run")
def test_agy_runner_report_not_generated(mock_run, mock_which, tmp_path):
    patchset_dir = tmp_path / "patchset"
    patchset_dir.mkdir()
    report_file = tmp_path / "report.md"
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    runner = AgyAgentRunner(cmd="agy")
    with pytest.raises(AgentExecutionError, match="report file.*was not generated"):
        runner.run_analysis(patchset_dir, report_file)


@patch("shutil.which", return_value="/usr/bin/agy")
@patch("subprocess.run")
def test_agy_runner_report_empty(mock_run, mock_which, tmp_path):
    patchset_dir = tmp_path / "patchset"
    patchset_dir.mkdir()
    report_file = tmp_path / "report.md"
    report_file.write_text("", encoding="utf-8")
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    runner = AgyAgentRunner(cmd="agy")
    with pytest.raises(AgentExecutionError, match="report file.*was not generated"):
        runner.run_analysis(patchset_dir, report_file)


@patch("shutil.which", return_value="/usr/bin/agy")
@patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="agy", timeout=10))
def test_agy_runner_timeout(mock_run, mock_which, tmp_path):
    patchset_dir = tmp_path / "patchset"
    patchset_dir.mkdir()
    report_file = tmp_path / "report.md"

    runner = AgyAgentRunner(cmd="agy", timeout_seconds=10)
    with pytest.raises(AgentTimeoutError, match="Agent analysis timed out after 10s"):
        runner.run_analysis(patchset_dir, report_file)


def test_opencode_runner_check_available():
    with patch("shutil.which", return_value="/usr/bin/opencode"):
        runner = OpenCodeAgentRunner(cmd="opencode")
        assert runner.check_available() is True

    with patch("shutil.which", return_value=None):
        runner = OpenCodeAgentRunner(cmd="opencode")
        assert runner.check_available() is False


def test_opencode_runner_executable_not_found(tmp_path):
    with patch("shutil.which", return_value=None):
        runner = OpenCodeAgentRunner(cmd="nonexistent_opencode_cmd")
        with pytest.raises(
            AgentNotFoundError,
            match="Agent executable 'nonexistent_opencode_cmd' not found in PATH",
        ):
            runner.run_analysis(tmp_path / "patchset", tmp_path / "report.md")


@patch("shutil.which", return_value="/usr/bin/opencode")
@patch("subprocess.run")
def test_opencode_runner_successful_execution(mock_run, mock_which, tmp_path):
    patchset_dir = tmp_path / "patchset"
    patchset_dir.mkdir()
    report_file = tmp_path / "report.md"

    def side_effect(cmd, **kwargs):
        report_file.write_text("# OpenCode Report", encoding="utf-8")
        return MagicMock(returncode=0, stdout="OK", stderr="")

    mock_run.side_effect = side_effect

    runner = OpenCodeAgentRunner(cmd="opencode", timeout_seconds=180)
    runner.run_analysis(patchset_dir, report_file)

    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0][0] == "opencode"
    assert args[0][1] == "run"
    assert "kernel-patch-analyzer" in args[0][2]
    assert str(patchset_dir.resolve()) in args[0][2]
    assert kwargs.get("timeout") == 180


@patch("shutil.which", return_value="/usr/bin/opencode")
@patch("subprocess.run")
def test_opencode_runner_execution_failure(mock_run, mock_which, tmp_path):
    patchset_dir = tmp_path / "patchset"
    patchset_dir.mkdir()
    report_file = tmp_path / "report.md"
    mock_run.return_value = MagicMock(returncode=2, stdout="", stderr="Crash")

    runner = OpenCodeAgentRunner(cmd="opencode")
    with pytest.raises(
        AgentExecutionError, match="Agent failed with exit code 2: Crash"
    ):
        runner.run_analysis(patchset_dir, report_file)


@patch("shutil.which", return_value="/usr/bin/opencode")
@patch("subprocess.run")
def test_opencode_runner_report_not_generated(mock_run, mock_which, tmp_path):
    patchset_dir = tmp_path / "patchset"
    patchset_dir.mkdir()
    report_file = tmp_path / "report.md"
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    runner = OpenCodeAgentRunner(cmd="opencode")
    with pytest.raises(AgentExecutionError, match="report file.*was not generated"):
        runner.run_analysis(patchset_dir, report_file)


@patch("shutil.which", return_value="/usr/bin/opencode")
@patch(
    "subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="opencode", timeout=15)
)
def test_opencode_runner_timeout(mock_run, mock_which, tmp_path):
    patchset_dir = tmp_path / "patchset"
    patchset_dir.mkdir()
    report_file = tmp_path / "report.md"

    runner = OpenCodeAgentRunner(cmd="opencode", timeout_seconds=15)
    with pytest.raises(AgentTimeoutError, match="Agent analysis timed out after 15s"):
        runner.run_analysis(patchset_dir, report_file)
