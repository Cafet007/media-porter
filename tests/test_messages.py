"""Tests for user-facing message helpers."""

from backend.core.messages import describe_error, format_duration, format_size


def test_describe_known_errors():
    assert "already at the destination" in describe_error(
        "DESTINATION EXISTS: '/Volumes/X/a.jpg'. Will not overwrite"
    )
    assert "full" in describe_error("NOT ENOUGH SPACE: need 10 MB")
    assert "card removed" in describe_error("[Errno 2] No such file or directory: '/Volumes/SD/a.jpg'")
    assert "failing" in describe_error("[Errno 5] Input/output error")


def test_describe_unknown_error_passes_through():
    assert describe_error("something odd") == "something odd"


def test_format_duration():
    assert format_duration(0) == "0 s"
    assert format_duration(45) == "45 s"
    assert format_duration(359) == "6 min"
    assert format_duration(3600) == "1 h"
    assert format_duration(4800) == "1 h 20 min"


def test_format_size():
    assert format_size(500 * 1_048_576) == "500 MB"
    assert format_size(38.2 * 1_073_741_824) == "38.2 GB"
