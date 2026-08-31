from pathlib import Path
from kp.storage.paths import (
    get_clean_id,
    get_month_bucket,
    get_patchset_dir,
    get_report_path,
)


def test_get_clean_id():
    assert (
        get_clean_id("20260830120000.1234-1-user@kernel.org")
        == "20260830120000.1234-1-user@kernel.org"
    )
    assert (
        get_clean_id("<20260830120000.1234-1-user@kernel.org>")
        == "20260830120000.1234-1-user@kernel.org"
    )
    assert get_clean_id("path/to/msg/id@domain") == "path%2Fto%2Fmsg%2Fid@domain"
    assert get_clean_id(" <nested/msgid@domain> ") == "nested%2Fmsgid@domain"


def test_get_month_bucket():
    assert get_month_bucket("2026-08-30T12:00:00Z") == "2026-08"
    assert get_month_bucket("20260830T12:00:00Z") == "2026-08"
    assert get_month_bucket("2026-01-01") == "2026-01"
    assert get_month_bucket(None) == "unknown"
    assert get_month_bucket("") == "unknown"
    assert get_month_bucket("invalid") == "unknown"


def test_get_patchset_dir():
    data_dir = Path("/data/test")
    msgid = "<20260830120000.1234-1-user@kernel.org>"
    date_str = "2026-08-30T12:00:00Z"
    p_dir = get_patchset_dir(data_dir, msgid, date_str)
    assert p_dir == Path(
        "/data/test/patchsets/2026-08/20260830120000.1234-1-user@kernel.org"
    )


def test_get_report_path():
    data_dir = Path("/data/test")
    msgid = "sub/id@kernel.org"
    date_str = "2026-09-01T08:00:00Z"
    r_path = get_report_path(data_dir, msgid, date_str)
    assert r_path == Path("/data/test/reports/2026-09/sub%2Fid@kernel.org.md")
