"""Tests for dystemctl.logs module."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from dystemctl.cli.journal import LogEntry, parse_json_log_stream
from dystemctl.logs import (
    build_log_predicate,
    parse_time_spec,
    query_os_log,
    tail_log_file,
)


class TestTailLogFile:
    def test_tail_existing_file(self, temp_dir: Path):
        log_file = temp_dir / "test.log"
        log_content = "\n".join([f"Line {i}" for i in range(20)])
        log_file.write_text(log_content)

        result = tail_log_file(log_file, lines=5)
        assert len(result) == 5
        assert result[-1] == "Line 19"

    def test_tail_small_file(self, temp_dir: Path):
        log_file = temp_dir / "small.log"
        log_file.write_text("Line 1\nLine 2\nLine 3")

        result = tail_log_file(log_file, lines=10)
        assert len(result) == 3

    def test_tail_nonexistent_file(self, temp_dir: Path):
        result = tail_log_file(temp_dir / "nonexistent.log")
        assert result == []

    def test_tail_empty_file(self, temp_dir: Path):
        log_file = temp_dir / "empty.log"
        log_file.write_text("")

        result = tail_log_file(log_file, lines=10)
        assert result == [""]

    def test_tail_default_lines(self, temp_dir: Path):
        log_file = temp_dir / "test.log"
        log_content = "\n".join([f"Line {i}" for i in range(20)])
        log_file.write_text(log_content)

        result = tail_log_file(log_file)  # default 10 lines
        assert len(result) == 10


class TestParseTimeSpec:
    def test_parse_today(self):
        result = parse_time_spec("today")
        assert result is not None
        now = datetime.now()
        assert result.year == now.year
        assert result.month == now.month
        assert result.day == now.day
        assert result.hour == 0
        assert result.minute == 0
        assert result.second == 0

    def test_parse_yesterday(self):
        result = parse_time_spec("yesterday")
        assert result is not None
        yesterday = datetime.now() - timedelta(days=1)
        assert result.year == yesterday.year
        assert result.month == yesterday.month
        assert result.day == yesterday.day
        assert result.hour == 0

    def test_parse_relative_seconds(self):
        result = parse_time_spec("30 seconds ago")
        assert result is not None
        expected = datetime.now() - timedelta(seconds=30)
        # Allow 2 second tolerance for test execution time
        assert abs((result - expected).total_seconds()) < 2

    def test_parse_relative_minutes(self):
        result = parse_time_spec("5 minutes ago")
        assert result is not None
        expected = datetime.now() - timedelta(minutes=5)
        assert abs((result - expected).total_seconds()) < 2

    def test_parse_relative_hours(self):
        result = parse_time_spec("2 hours ago")
        assert result is not None
        expected = datetime.now() - timedelta(hours=2)
        assert abs((result - expected).total_seconds()) < 2

    def test_parse_relative_days(self):
        result = parse_time_spec("3 days ago")
        assert result is not None
        expected = datetime.now() - timedelta(days=3)
        assert abs((result - expected).total_seconds()) < 2

    def test_parse_relative_weeks(self):
        result = parse_time_spec("1 week ago")
        assert result is not None
        expected = datetime.now() - timedelta(weeks=1)
        assert abs((result - expected).total_seconds()) < 2

    def test_parse_relative_singular(self):
        result = parse_time_spec("1 hour ago")
        assert result is not None

    def test_parse_relative_case_insensitive(self):
        result = parse_time_spec("1 HOUR AGO")
        assert result is not None

    def test_parse_full_datetime(self):
        result = parse_time_spec("2024-01-15 10:30:00")
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 10
        assert result.minute == 30
        assert result.second == 0

    def test_parse_datetime_without_seconds(self):
        result = parse_time_spec("2024-01-15 10:30")
        assert result is not None
        assert result.hour == 10
        assert result.minute == 30

    def test_parse_date_only(self):
        result = parse_time_spec("2024-01-15")
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_parse_time_only(self):
        result = parse_time_spec("14:30:00")
        assert result is not None
        now = datetime.now()
        assert result.year == now.year
        assert result.month == now.month
        assert result.day == now.day
        assert result.hour == 14
        assert result.minute == 30

    def test_parse_time_only_short(self):
        result = parse_time_spec("14:30")
        assert result is not None
        assert result.hour == 14
        assert result.minute == 30

    def test_parse_empty(self):
        result = parse_time_spec("")
        assert result is None

    def test_parse_invalid(self):
        result = parse_time_spec("invalid time spec")
        assert result is None

    def test_parse_unix_epoch(self):
        import time

        now_ts = time.time()
        result = parse_time_spec(f"@{int(now_ts)}")
        assert result is not None
        assert abs((result - datetime.now()).total_seconds()) < 2

    def test_parse_unix_epoch_with_fraction(self):
        import time

        now_ts = time.time()
        result = parse_time_spec(f"@{now_ts}")
        assert result is not None
        assert abs((result - datetime.now()).total_seconds()) < 2

    def test_parse_unix_epoch_invalid(self):
        result = parse_time_spec("@invalid")
        assert result is None

    def test_parse_now(self):
        result = parse_time_spec("now")
        assert result is not None
        assert abs((result - datetime.now()).total_seconds()) < 2

    def test_parse_tomorrow(self):
        result = parse_time_spec("tomorrow")
        assert result is not None
        tomorrow = datetime.now() + timedelta(days=1)
        assert result.year == tomorrow.year
        assert result.month == tomorrow.month
        assert result.day == tomorrow.day
        assert result.hour == 0

    def test_parse_relative_months(self):
        result = parse_time_spec("2 months ago")
        assert result is not None
        expected = datetime.now() - timedelta(days=60)  # approximately 2 months
        assert abs((result - expected).total_seconds()) < 86400  # 1 day tolerance

    def test_parse_short_relative_seconds(self):
        result = parse_time_spec("-30s")
        assert result is not None
        expected = datetime.now() - timedelta(seconds=30)
        assert abs((result - expected).total_seconds()) < 2

    def test_parse_short_relative_minutes(self):
        result = parse_time_spec("-5m")
        assert result is not None
        expected = datetime.now() - timedelta(minutes=5)
        assert abs((result - expected).total_seconds()) < 2

    def test_parse_short_relative_hours(self):
        result = parse_time_spec("-2h")
        assert result is not None
        expected = datetime.now() - timedelta(hours=2)
        assert abs((result - expected).total_seconds()) < 2

    def test_parse_short_relative_days(self):
        result = parse_time_spec("-1d")
        assert result is not None
        expected = datetime.now() - timedelta(days=1)
        assert abs((result - expected).total_seconds()) < 2

    def test_parse_short_relative_weeks(self):
        result = parse_time_spec("-1w")
        assert result is not None
        expected = datetime.now() - timedelta(weeks=1)
        assert abs((result - expected).total_seconds()) < 2

    def test_parse_relative_without_ago(self):
        result = parse_time_spec("5 minutes")
        assert result is not None
        expected = datetime.now() - timedelta(minutes=5)
        assert abs((result - expected).total_seconds()) < 2


class TestBuildLogPredicate:
    def test_predicate_with_process(self):
        result = build_log_predicate("myprocess", None)
        assert result == 'process == "myprocess"'

    def test_predicate_with_priority_error(self):
        result = build_log_predicate(None, "3")  # err
        assert "messageType >= Error" in result

    def test_predicate_with_priority_debug(self):
        result = build_log_predicate(None, "7")  # debug
        assert "messageType >= Debug" in result

    def test_predicate_with_priority_info(self):
        result = build_log_predicate(None, "6")  # info
        assert "messageType >= Info" in result

    def test_predicate_with_both(self):
        result = build_log_predicate("myprocess", "3")
        assert 'process == "myprocess"' in result
        assert "messageType >= Error" in result
        assert " AND " in result

    def test_predicate_empty(self):
        result = build_log_predicate(None, None)
        assert result == ""

    def test_predicate_priority_emerg(self):
        result = build_log_predicate(None, "0")
        assert "messageType >= Fault" in result

    def test_predicate_priority_warning(self):
        result = build_log_predicate(None, "4")
        assert "messageType >= Default" in result

    def test_predicate_multiple_processes(self):
        result = build_log_predicate(["proc1", "proc2"], None)
        assert 'process == "proc1"' in result
        assert 'process == "proc2"' in result
        assert " OR " in result

    def test_predicate_multiple_processes_with_priority(self):
        result = build_log_predicate(["proc1", "proc2"], "3")
        assert 'process == "proc1"' in result
        assert 'process == "proc2"' in result
        assert "messageType >= Error" in result
        assert " AND " in result

    def test_predicate_single_process_in_list(self):
        result = build_log_predicate(["singleproc"], None)
        assert result == 'process == "singleproc"'
        assert " OR " not in result

    def test_predicate_empty_list(self):
        result = build_log_predicate([], None)
        assert result == ""


class TestQueryOsLog:
    def test_query_os_log_mock(self):
        import json

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(
            [
                {
                    "timestamp": "2024-01-15 10:30:00.123456-0600",
                    "processID": 123,
                    "processImagePath": "/usr/bin/process",
                    "eventMessage": "test message",
                    "subsystem": "com.test",
                    "category": "default",
                }
            ]
        )

        with patch("dystemctl.logs.subprocess.run", return_value=mock_result):
            result = query_os_log("testprocess", last_minutes=5)
            assert len(result) == 1
            assert result[0]["eventMessage"] == "test message"

    def test_query_os_log_failure(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch("dystemctl.logs.subprocess.run", return_value=mock_result):
            result = query_os_log("testprocess")
            assert result == []

    def test_query_os_log_empty(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "[]"

        with patch("dystemctl.logs.subprocess.run", return_value=mock_result):
            result = query_os_log("testprocess")
            assert result == []


class TestLogEntry:
    def test_from_json_basic(self):
        data = {
            "timestamp": "2024-01-15 10:30:00.123456-0600",
            "processID": 123,
            "processImagePath": "/usr/bin/myprocess",
            "eventMessage": "test message",
            "subsystem": "com.test",
            "category": "default",
        }
        entry = LogEntry.from_json(data)
        assert entry.process == "myprocess"
        assert entry.pid == 123
        assert entry.message == "test message"
        assert entry.subsystem == "com.test"
        assert entry.category == "default"
        assert entry.timestamp.year == 2024
        assert entry.timestamp.month == 1
        assert entry.timestamp.day == 15

    def test_from_json_missing_process_path(self):
        data = {
            "timestamp": "2024-01-15 10:30:00.123456-0600",
            "processID": 0,
            "processImagePath": "",
            "eventMessage": "kernel message",
        }
        entry = LogEntry.from_json(data)
        assert entry.process == "kernel"

    def test_from_json_invalid_timestamp(self):
        data = {
            "timestamp": "invalid",
            "processID": 123,
            "processImagePath": "/usr/bin/test",
            "eventMessage": "test",
        }
        entry = LogEntry.from_json(data)
        assert entry.timestamp is not None
        assert entry.pid == 123

    def test_format_short(self):
        entry = LogEntry(
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            process="myproc",
            pid=123,
            message="test message",
        )
        result = entry.format_short("myhost")
        assert "Jan 15 10:30:00" in result
        assert "myhost" in result
        assert "myproc[123]" in result
        assert "test message" in result

    def test_format_short_iso(self):
        entry = LogEntry(
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            process="myproc",
            pid=123,
            message="test message",
        )
        result = entry.format_short_iso("myhost")
        assert "2024-01-15T10:30:00" in result
        assert "myhost" in result

    def test_format_short_precise(self):
        entry = LogEntry(
            timestamp=datetime(2024, 1, 15, 10, 30, 0, 123456),
            process="myproc",
            pid=123,
            message="test message",
        )
        result = entry.format_short_precise("myhost")
        assert "123456" in result

    def test_format_short_iso_precise(self):
        entry = LogEntry(
            timestamp=datetime(2024, 1, 15, 10, 30, 0, 123456),
            process="myproc",
            pid=123,
            message="test message",
        )
        result = entry.format_short_iso_precise("myhost")
        assert "2024-01-15T10:30:00.123456" in result

    def test_format_short_full(self):
        entry = LogEntry(
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            process="myproc",
            pid=123,
            message="test message",
        )
        result = entry.format_short_full("myhost")
        assert "Mon 2024-01-15 10:30:00" in result

    def test_format_short_unix(self):
        ts = datetime(2024, 1, 15, 10, 30, 0)
        entry = LogEntry(
            timestamp=ts,
            process="myproc",
            pid=123,
            message="test message",
        )
        result = entry.format_short_unix("myhost")
        assert str(int(ts.timestamp())) in result

    def test_format_verbose(self):
        entry = LogEntry(
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            process="myproc",
            pid=123,
            message="test message",
            subsystem="com.test",
        )
        result = entry.format_verbose("myhost", unit="test.service")
        assert "_HOSTNAME=myhost" in result
        assert "_COMM=myproc" in result
        assert "_PID=123" in result
        assert "_SYSTEMD_UNIT=test.service" in result
        assert "_SUBSYSTEM=com.test" in result
        assert "MESSAGE=test message" in result

    def test_format_verbose_without_unit(self):
        entry = LogEntry(
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            process="myproc",
            pid=123,
            message="test",
        )
        result = entry.format_verbose("myhost")
        assert "_SYSTEMD_UNIT" not in result

    def test_format_cat(self):
        entry = LogEntry(
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
            process="myproc",
            pid=123,
            message="just the message",
        )
        result = entry.format_cat()
        assert result == "just the message"


class TestParseJsonLogStream:
    def test_parse_single_entry(self):
        stream = [
            '[{"timestamp": "2024-01-15 10:30:00.123456-0600", '
            '"processID": 123, "processImagePath": "/usr/bin/test", '
            '"eventMessage": "test message"}]'
        ]
        entries = parse_json_log_stream(stream)
        assert len(entries) == 1
        assert entries[0].message == "test message"

    def test_parse_multiple_entries(self):
        stream = [
            '[{"timestamp": "2024-01-15 10:30:00.000000-0600", '
            '"processID": 1, "processImagePath": "/usr/bin/a", '
            '"eventMessage": "msg1"}, '
            '{"timestamp": "2024-01-15 10:30:01.000000-0600", '
            '"processID": 2, "processImagePath": "/usr/bin/b", '
            '"eventMessage": "msg2"}]'
        ]
        entries = parse_json_log_stream(stream)
        assert len(entries) == 2
        assert entries[0].message == "msg1"
        assert entries[1].message == "msg2"

    def test_parse_chunked_stream(self):
        stream = [
            '[{"timestamp": "2024-01-15 10:30:00.000000-0600", ',
            '"processID": 123, "processImagePath": "/usr/bin/test", ',
            '"eventMessage": "test"}]',
        ]
        entries = parse_json_log_stream(stream)
        assert len(entries) == 1

    def test_parse_empty_stream(self):
        entries = parse_json_log_stream([])
        assert entries == []

    def test_parse_invalid_json(self):
        stream = ["not valid json"]
        entries = parse_json_log_stream(stream)
        assert entries == []

    def test_parse_filters_non_event_entries(self):
        stream = [
            '[{"timestamp": "2024-01-15 10:30:00.000000-0600", '
            '"processID": 1, "processImagePath": "/usr/bin/a", '
            '"eventMessage": "has message"}, '
            '{"timestamp": "2024-01-15 10:30:00.000000-0600", '
            '"processID": 2, "processImagePath": "/usr/bin/b", '
            '"noEventMessage": "filtered"}]'
        ]
        entries = parse_json_log_stream(stream)
        assert len(entries) == 1
        assert entries[0].message == "has message"
