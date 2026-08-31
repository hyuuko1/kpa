import pytest
from datetime import datetime, timezone, timedelta
from kp.config import SafetyConfig
from kp.adapters.lore import SafetyValidator, SafetyValidationError


def test_missing_time_filter_raises_error():
    config = SafetyConfig(max_time_span_minutes=180, require_time_filter=True)
    validator = SafetyValidator(config)
    with pytest.raises(SafetyValidationError, match="必须包含.*d:"):
        validator.validate_query("l:linux-mm.kvack.org AND NOT s:Re")


def test_missing_time_filter_allowed_when_not_required():
    config = SafetyConfig(max_time_span_minutes=180, require_time_filter=False)
    validator = SafetyValidator(config)
    # Should not raise
    validator.validate_query("l:linux-mm.kvack.org AND NOT s:Re")


def test_valid_relative_time_filter():
    config = SafetyConfig(max_time_span_minutes=180, require_time_filter=True)
    validator = SafetyValidator(config)
    # 2 hours <= 3 hours (180m) -> ok
    validator.validate_query("l:linux-mm.kvack.org AND NOT s:Re AND d:2.hours.ago..")
    # 90 minutes <= 180m -> ok
    validator.validate_query("l:linux-mm.kvack.org AND d:90.minutes.ago..")


def test_exceeded_relative_time_filter():
    config = SafetyConfig(max_time_span_minutes=180, require_time_filter=True)
    validator = SafetyValidator(config)
    with pytest.raises(SafetyValidationError, match="超过.*限制"):
        validator.validate_query("l:linux-mm.kvack.org AND d:4.hours.ago..")
    with pytest.raises(SafetyValidationError, match="超过.*限制"):
        validator.validate_query("l:linux-mm.kvack.org AND d:200.minutes.ago..")
    with pytest.raises(SafetyValidationError, match="禁止使用大粒度"):
        validator.validate_query("l:linux-mm.kvack.org AND d:1.day.ago..")


def test_absolute_time_filter():
    config = SafetyConfig(max_time_span_minutes=180, require_time_filter=True)
    validator = SafetyValidator(config)
    # 1 hour ago UTC -> valid
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    validator.validate_query(f"l:linux-mm.kvack.org AND d:{recent}..")

    # 5 hours ago UTC -> invalid
    old = (datetime.now(timezone.utc) - timedelta(hours=5)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    with pytest.raises(SafetyValidationError, match="超过.*限制"):
        validator.validate_query(f"l:linux-mm.kvack.org AND d:{old}..")


def test_invalid_date_format():
    config = SafetyConfig(max_time_span_minutes=180, require_time_filter=True)
    validator = SafetyValidator(config)
    with pytest.raises(SafetyValidationError, match="无法识别的时间格式"):
        validator.validate_query("l:linux-mm.kvack.org AND d:invalid_time..")
