from __future__ import annotations

from datetime import datetime, timezone

from utils import normalize_datetime


def test_normalize_datetime_returns_none_for_none_or_empty_values() -> None:
    assert normalize_datetime(None) is None
    assert normalize_datetime("") is None
    assert normalize_datetime("   ") is None


def test_normalize_datetime_handles_naive_datetime_as_utc() -> None:
    value = datetime(2024, 12, 14, 16, 10, 59)

    assert normalize_datetime(value) == "2024-12-14T16:10:59+00:00"


def test_normalize_datetime_converts_timezone_aware_datetime() -> None:
    value = datetime(2024, 12, 14, 8, 10, 59, tzinfo=timezone.utc)

    assert normalize_datetime(value) == "2024-12-14T08:10:59+00:00"


def test_normalize_datetime_parses_unix_timestamp_inputs() -> None:
    value = 1734192659

    assert normalize_datetime(value) == "2024-12-14T16:10:59+00:00"
    assert normalize_datetime(str(value)) == "2024-12-14T16:10:59+00:00"


def test_normalize_datetime_parses_common_date_string_format() -> None:
    value = "Sat, 14 Dec 2024 16:10:59 GMT"

    assert normalize_datetime(value) == "2024-12-14T16:10:59+00:00"


def test_normalize_datetime_returns_none_for_invalid_string() -> None:
    assert normalize_datetime("not-a-date") is None
