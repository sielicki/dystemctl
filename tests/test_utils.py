"""Tests for dystemctl.utils module."""

from __future__ import annotations

from datetime import timedelta

from dystemctl.utils import (
    format_bytes,
    format_elapsed,
    format_since,
    levenshtein_distance,
)


class TestFormatBytes:
    def test_bytes(self):
        assert format_bytes(512) == "512.0B"

    def test_kilobytes(self):
        assert format_bytes(1024) == "1.0K"
        assert format_bytes(2048) == "2.0K"
        assert format_bytes(1536) == "1.5K"

    def test_megabytes(self):
        assert format_bytes(1024 * 1024) == "1.0M"
        assert format_bytes(104857600) == "100.0M"

    def test_gigabytes(self):
        assert format_bytes(1024 * 1024 * 1024) == "1.0G"
        assert format_bytes(2 * 1024 * 1024 * 1024) == "2.0G"

    def test_terabytes(self):
        assert format_bytes(1024 * 1024 * 1024 * 1024) == "1.0T"

    def test_zero(self):
        assert format_bytes(0) == "0.0B"


class TestFormatElapsed:
    def test_seconds(self):
        assert format_elapsed(timedelta(seconds=30)) == "30s"
        assert format_elapsed(timedelta(seconds=1)) == "1s"

    def test_minutes(self):
        assert format_elapsed(timedelta(minutes=5)) == "5min 0s"
        assert format_elapsed(timedelta(minutes=5, seconds=30)) == "5min 30s"

    def test_hours(self):
        assert format_elapsed(timedelta(hours=2)) == "2h 0min"
        assert format_elapsed(timedelta(hours=2, minutes=30)) == "2h 30min"

    def test_days(self):
        assert format_elapsed(timedelta(days=3)) == "3d 0h"
        assert format_elapsed(timedelta(days=3, hours=12)) == "3d 12h"

    def test_zero(self):
        assert format_elapsed(timedelta(seconds=0)) == "0s"

    def test_complex(self):
        elapsed = timedelta(days=1, hours=5, minutes=30, seconds=45)
        assert format_elapsed(elapsed) == "1d 5h"


class TestFormatSince:
    def test_format_since(self):
        elapsed = timedelta(hours=2)
        result = format_since(elapsed)
        assert "2h 0min ago" in result
        # Should contain a date string
        assert ";" in result

    def test_format_since_days(self):
        elapsed = timedelta(days=5, hours=3)
        result = format_since(elapsed)
        assert "5d 3h ago" in result


class TestLevenshteinDistance:
    def test_identical_strings(self):
        assert levenshtein_distance("hello", "hello") == 0

    def test_empty_strings(self):
        assert levenshtein_distance("", "") == 0
        assert levenshtein_distance("hello", "") == 5
        assert levenshtein_distance("", "world") == 5

    def test_single_insertion(self):
        assert levenshtein_distance("helo", "hello") == 1

    def test_single_deletion(self):
        assert levenshtein_distance("hello", "helo") == 1

    def test_single_substitution(self):
        assert levenshtein_distance("hello", "hallo") == 1

    def test_multiple_operations(self):
        assert levenshtein_distance("kitten", "sitting") == 3

    def test_completely_different(self):
        assert levenshtein_distance("abc", "xyz") == 3

    def test_case_sensitive(self):
        assert levenshtein_distance("Hello", "hello") == 1

    def test_redis_example(self):
        # Common typo scenarios
        assert levenshtein_distance("redis", "rediis") == 1
        assert levenshtein_distance("redis", "rediss") == 1
        assert levenshtein_distance("redis", "redi") == 1

    def test_symmetry(self):
        # Distance should be the same regardless of order
        assert levenshtein_distance("abc", "def") == levenshtein_distance("def", "abc")
        assert levenshtein_distance("hello", "world") == levenshtein_distance(
            "world", "hello"
        )

    def test_common_service_typos(self):
        # emacs -> emcas (common typo)
        assert levenshtein_distance("emacs", "emcas") == 2
        # postgresql -> postgres
        assert levenshtein_distance("postgresql", "postgres") == 2
