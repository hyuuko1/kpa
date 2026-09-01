import pytest
from datetime import datetime, timezone, timedelta
from kp.config import SafetyConfig
from kp.adapters.lore import SafetyValidator, SafetyValidationError


def test_missing_time_filter_raises_error():
    config = SafetyConfig(max_time_span_hours=48, require_time_filter=True)
    validator = SafetyValidator(config)
    with pytest.raises(SafetyValidationError, match="必须包含.*dt:"):
        validator.validate_query("l:linux-mm.kvack.org AND NOT s:Re")


def test_missing_time_filter_allowed_when_not_required():
    config = SafetyConfig(max_time_span_hours=48, require_time_filter=False)
    validator = SafetyValidator(config)
    # Should not raise
    validator.validate_query("l:linux-mm.kvack.org AND NOT s:Re")


def test_valid_relative_time_filter():
    config = SafetyConfig(max_time_span_hours=48, require_time_filter=True)
    validator = SafetyValidator(config)
    # 2 hours <= 48 hours -> ok
    validator.validate_query("l:linux-mm.kvack.org AND NOT s:Re AND dt:2.hours.ago..")
    # 90 minutes <= 48h -> ok
    validator.validate_query("l:linux-mm.kvack.org AND dt:90.minutes.ago..")
    # 1 day (24 hours) <= 48h -> ok
    validator.validate_query("l:linux-mm.kvack.org AND dt:1.day.ago..")
    # 2 days (48 hours) <= 48h -> ok
    validator.validate_query("l:linux-mm.kvack.org AND dt:2.days.ago..")


def test_exceeded_relative_time_filter():
    config = SafetyConfig(max_time_span_hours=48, require_time_filter=True)
    validator = SafetyValidator(config)
    with pytest.raises(SafetyValidationError, match="超过.*限制"):
        validator.validate_query("l:linux-mm.kvack.org AND dt:50.hours.ago..")
    with pytest.raises(SafetyValidationError, match="超过.*限制"):
        validator.validate_query("l:linux-mm.kvack.org AND dt:3000.minutes.ago..")
    with pytest.raises(SafetyValidationError, match="超过.*限制"):
        validator.validate_query("l:linux-mm.kvack.org AND dt:3.days.ago..")
    with pytest.raises(SafetyValidationError, match="禁止使用大粒度"):
        validator.validate_query("l:linux-mm.kvack.org AND dt:1.week.ago..")


def test_absolute_time_filter():
    config = SafetyConfig(max_time_span_hours=48, require_time_filter=True)
    validator = SafetyValidator(config)
    # 1 hour ago UTC -> valid
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    validator.validate_query(f"l:linux-mm.kvack.org AND dt:{recent}..")

    # 24 hours ago UTC -> valid
    day_ago = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    validator.validate_query(f"l:linux-mm.kvack.org AND dt:{day_ago}..")

    # 60 hours ago UTC -> invalid
    old = (datetime.now(timezone.utc) - timedelta(hours=60)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    with pytest.raises(SafetyValidationError, match="超过.*限制"):
        validator.validate_query(f"l:linux-mm.kvack.org AND dt:{old}..")

    # START..END range within 48h -> valid
    t_start = (datetime.now(timezone.utc) - timedelta(hours=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    t_end = (datetime.now(timezone.utc) - timedelta(hours=10)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    validator.validate_query(f"l:linux-mm.kvack.org AND dt:{t_start}..{t_end}")

    # START..END range over 48h (e.g. 50h span) -> invalid
    t_start_over = (datetime.now(timezone.utc) - timedelta(hours=60)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    t_end_over = (datetime.now(timezone.utc) - timedelta(hours=10)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    with pytest.raises(SafetyValidationError, match="超过.*限制"):
        validator.validate_query(
            f"l:linux-mm.kvack.org AND dt:{t_start_over}..{t_end_over}"
        )


def test_invalid_date_format():
    config = SafetyConfig(max_time_span_hours=48, require_time_filter=True)
    validator = SafetyValidator(config)
    with pytest.raises(SafetyValidationError, match="无法识别的时间格式"):
        validator.validate_query("l:linux-mm.kvack.org AND dt:invalid_time..")
