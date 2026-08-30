from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch
import pytest
from kp.config import B4Config
from kp.adapters.b4 import B4Client, B4ExecutionError, B4NotFoundError


def test_sanitize_id():
    client = B4Client(B4Config())
    raw = "<20260830-test.123@domain.org>"
    sanitized = client.sanitize_id(raw)
    assert "<" not in sanitized and ">" not in sanitized
    assert "@" not in sanitized
    assert sanitized == "20260830-test.123_domain.org"


def test_sanitize_id_special_chars():
    assert B4Client.sanitize_id("20260830/patch:123@domain.com") == "20260830_patch_123_domain.com"
    assert B4Client.sanitize_id("<foo?bar*baz@test.org>") == "foo_bar_baz_test.org"
    assert B4Client.sanitize_id("   <spaces-in-id@org>  ") == "spaces-in-id_org"


@patch("shutil.which")
def test_b4_not_found(mock_which):
    mock_which.return_value = None
    client = B4Client(B4Config())
    with pytest.raises(B4NotFoundError):
        client.fetch_thread("test@msgid", Path("/tmp"))


@patch("shutil.which", return_value="/usr/bin/b4")
@patch("subprocess.run")
def test_fetch_thread_success(mock_run, mock_which, tmp_path):
    mock_run.return_value = MagicMock(returncode=0, stdout="Downloaded", stderr="")
    target_mbox = tmp_path / "series.mbx"
    target_mbox.write_text("From xxx\nSubject: test\n", encoding="utf-8")

    client = B4Client(B4Config(timeout_seconds=30))
    result_path = client.fetch_thread("test@msgid", tmp_path, mbox_name="series.mbx")

    assert result_path == target_mbox
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[0] == "/usr/bin/b4"
    assert "mbox" in args
    assert "test@msgid" in args
    assert "-o" in args
    assert str(tmp_path) in args


@patch("shutil.which", return_value="/usr/bin/b4")
@patch("subprocess.run")
def test_fetch_thread_execution_failure(mock_run, mock_which, tmp_path):
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Error: msgid not found")
    client = B4Client(B4Config())
    with pytest.raises(B4ExecutionError) as exc_info:
        client.fetch_thread("notfound@msgid", tmp_path)
    assert "b4 mbox failed" in str(exc_info.value)


@patch("shutil.which", return_value="/usr/bin/b4")
@patch("subprocess.run")
def test_fetch_thread_timeout(mock_run, mock_which, tmp_path):
    mock_run.side_effect = subprocess.TimeoutExpired(cmd=["b4"], timeout=10)
    client = B4Client(B4Config(timeout_seconds=10))
    with pytest.raises(B4ExecutionError) as exc_info:
        client.fetch_thread("timeout@msgid", tmp_path)
    assert "超时" in str(exc_info.value) or "timeout" in str(exc_info.value).lower()


@patch("shutil.which", return_value="/usr/bin/b4")
@patch("subprocess.run")
def test_fetch_thread_file_missing(mock_run, mock_which, tmp_path):
    mock_run.return_value = MagicMock(returncode=0, stdout="Downloaded", stderr="")
    # Do not create the file
    client = B4Client(B4Config())
    with pytest.raises(B4ExecutionError) as exc_info:
        client.fetch_thread("missing@msgid", tmp_path, mbox_name="series.mbx")
    assert "b4 mbox failed" in str(exc_info.value)


def test_b4_client_default_init():
    client = B4Client()
    assert client.config.timeout_seconds == 120
