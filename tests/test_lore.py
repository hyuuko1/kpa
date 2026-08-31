import pytest
from unittest.mock import patch, MagicMock
import subprocess
from kp.config import LoreConfig, SafetyConfig
from kp.adapters.lore import LoreClient, LoreExecutionError


def test_lore_client_success():
    fake_json = '[{"m":"m1@test","s":"[PATCH] test","f":[["A","a@b.com"]],"dt":"2026-08-30T10:00:00Z"}]'
    lore_config = LoreConfig(
        inbox_url="https://lore.kernel.org/all/", timeout_seconds=10
    )
    safety_config = SafetyConfig(max_time_span_minutes=180, require_time_filter=True)
    client = LoreClient(lore_config, safety_config)

    with (
        patch("shutil.which", return_value="/usr/bin/lei"),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_json, stderr="")
        results = client.query("l:linux-mm.kvack.org AND d:2.hours.ago..")
        assert len(results) == 1
        assert results[0].m == "m1@test"
        assert results[0].s == "[PATCH] test"
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        assert args[0] == [
            "lei",
            "q",
            "-t",
            "-I",
            "https://lore.kernel.org/all/",
            "l:linux-mm.kvack.org AND d:2.hours.ago..",
            "-f",
            "json",
        ]


def test_lore_client_lei_not_found():
    lore_config = LoreConfig()
    safety_config = SafetyConfig()
    client = LoreClient(lore_config, safety_config)

    with patch("shutil.which", return_value=None):
        with pytest.raises(LoreExecutionError, match="未找到 lei 工具"):
            client.query("l:linux-mm.kvack.org AND d:2.hours.ago..")


def test_lore_client_timeout():
    lore_config = LoreConfig(timeout_seconds=5)
    safety_config = SafetyConfig()
    client = LoreClient(lore_config, safety_config)

    with (
        patch("shutil.which", return_value="/usr/bin/lei"),
        patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="lei", timeout=5),
        ),
    ):
        with pytest.raises(LoreExecutionError, match="lei 查询超时"):
            client.query("l:linux-mm.kvack.org AND d:2.hours.ago..")


def test_lore_client_nonzero_exit():
    lore_config = LoreConfig()
    safety_config = SafetyConfig()
    client = LoreClient(lore_config, safety_config)

    with (
        patch("shutil.which", return_value="/usr/bin/lei"),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="network error"
        )
        with pytest.raises(
            LoreExecutionError, match="lei 查询失败 \\(code 1\\): network error"
        ):
            client.query("l:linux-mm.kvack.org AND d:2.hours.ago..")


def test_lore_client_empty_output():
    lore_config = LoreConfig()
    safety_config = SafetyConfig()
    client = LoreClient(lore_config, safety_config)

    with (
        patch("shutil.which", return_value="/usr/bin/lei"),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="  \n", stderr="")
        results = client.query("l:linux-mm.kvack.org AND d:2.hours.ago..")
        assert results == []


def test_lore_client_invalid_json():
    lore_config = LoreConfig()
    safety_config = SafetyConfig()
    client = LoreClient(lore_config, safety_config)

    with (
        patch("shutil.which", return_value="/usr/bin/lei"),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="not valid json", stderr=""
        )
        with pytest.raises(LoreExecutionError, match="解析 lei 返回的 JSON 失败"):
            client.query("l:linux-mm.kvack.org AND d:2.hours.ago..")
