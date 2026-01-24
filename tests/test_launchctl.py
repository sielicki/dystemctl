"""Tests for dystemctl.launchctl module."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dystemctl.launchctl import (
    clear_caches,
    detect_domain,
    get_all_loaded_services,
    get_process_info,
    get_service_status,
    launchctl_disable,
    launchctl_enable,
    launchctl_start,
    launchctl_stop,
)
from dystemctl.models import Domain


@pytest.fixture(autouse=True)
def clear_launchctl_caches():
    """Clear launchctl caches before each test."""
    clear_caches()
    yield
    clear_caches()


class TestDetectDomain:
    def test_detect_gui_domain(self):
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("dystemctl.launchctl.subprocess.run", return_value=mock_result):
            result = detect_domain("com.example.test")
            assert result == Domain.GUI

    def test_detect_user_domain(self):
        def mock_run(args, **kwargs):
            result = MagicMock()
            if "gui" in args[2]:
                result.returncode = 1
            elif "user" in args[2]:
                result.returncode = 0
            else:
                result.returncode = 1
            return result

        with patch("dystemctl.launchctl.subprocess.run", side_effect=mock_run):
            result = detect_domain("com.example.test")
            assert result == Domain.USER

    def test_detect_system_domain(self):
        def mock_run(args, **kwargs):
            result = MagicMock()
            if "system" in args[2]:
                result.returncode = 0
            else:
                result.returncode = 1
            return result

        with patch("dystemctl.launchctl.subprocess.run", side_effect=mock_run):
            result = detect_domain("com.example.test")
            assert result == Domain.SYSTEM

    def test_detect_no_domain(self):
        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("dystemctl.launchctl.subprocess.run", return_value=mock_result):
            result = detect_domain("com.example.test")
            assert result is None


class TestGetAllLoadedServices:
    def test_parse_launchctl_list(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = """PID\tStatus\tLabel
1234\t0\tcom.example.running
-\t0\tcom.example.stopped
-\t1\tcom.example.failed
5678\t-\tcom.example.nodeps"""

        # Clear cache before test
        get_all_loaded_services.cache_clear()

        with patch("dystemctl.launchctl.subprocess.run", return_value=mock_result):
            result = get_all_loaded_services()

            assert "com.example.running" in result
            assert result["com.example.running"] == (1234, 0)

            assert "com.example.stopped" in result
            assert result["com.example.stopped"] == (None, 0)

            assert "com.example.failed" in result
            assert result["com.example.failed"] == (None, 1)

            assert "com.example.nodeps" in result
            assert result["com.example.nodeps"] == (5678, None)

    def test_parse_launchctl_list_failure(self):
        mock_result = MagicMock()
        mock_result.returncode = 1

        get_all_loaded_services.cache_clear()

        with patch("dystemctl.launchctl.subprocess.run", return_value=mock_result):
            result = get_all_loaded_services()
            assert result == {}


class TestGetServiceStatus:
    def test_status_from_cache(self):
        get_all_loaded_services.cache_clear()

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = """PID\tStatus\tLabel
1234\t0\tcom.example.test"""

        with patch("dystemctl.launchctl.subprocess.run", return_value=mock_result):
            status = get_service_status("com.example.test", use_cache=True)
            assert status is not None
            assert status.pid == 1234
            assert status.loaded is True

    def test_status_not_in_cache(self):
        get_all_loaded_services.cache_clear()

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = """PID\tStatus\tLabel
1234\t0\tcom.other.service"""

        with patch("dystemctl.launchctl.subprocess.run", return_value=mock_result):
            status = get_service_status("com.example.test", use_cache=True)
            assert status is not None
            assert status.loaded is False

    def test_status_direct_query(self):
        mock_list = MagicMock()
        mock_list.returncode = 0
        mock_list.stdout = """{
    "PID" = 1234;
    "LastExitStatus" = 0;
}"""

        mock_print = MagicMock()
        mock_print.returncode = 0

        def mock_run(args, **kwargs):
            if args[1] == "list":
                return mock_list
            elif args[1] == "print":
                return mock_print
            return MagicMock(returncode=1)

        with patch("dystemctl.launchctl.subprocess.run", side_effect=mock_run):
            status = get_service_status("com.example.test", use_cache=False)
            assert status is not None
            assert status.loaded is True

    def test_status_not_loaded(self):
        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("dystemctl.launchctl.subprocess.run", return_value=mock_result):
            status = get_service_status("com.example.test", use_cache=False)
            assert status is not None
            assert status.loaded is False
            assert status.pid is None


class TestLaunchctlStart:
    def test_start_with_domain(self):
        mock_print = MagicMock(returncode=0)
        mock_kickstart = MagicMock(returncode=0)

        def mock_run(args, **kwargs):
            if args[1] == "print":
                return mock_print
            elif args[1] == "kickstart":
                return mock_kickstart
            return MagicMock(returncode=1)

        with patch("dystemctl.launchctl.subprocess.run", side_effect=mock_run):
            result = launchctl_start("com.example.test")
            assert result is True

    def test_start_legacy(self):
        mock_print = MagicMock(returncode=1)
        mock_start = MagicMock(returncode=0)

        def mock_run(args, **kwargs):
            if args[1] == "print":
                return mock_print
            elif args[1] == "start":
                return mock_start
            return MagicMock(returncode=1)

        with patch("dystemctl.launchctl.subprocess.run", side_effect=mock_run):
            result = launchctl_start("com.example.test")
            assert result is True

    def test_start_failure(self):
        mock_result = MagicMock(returncode=1)

        with patch("dystemctl.launchctl.subprocess.run", return_value=mock_result):
            result = launchctl_start("com.example.test")
            assert result is False


class TestLaunchctlStop:
    def test_stop_with_domain(self):
        mock_print = MagicMock(returncode=0)
        mock_kill = MagicMock(returncode=0)

        def mock_run(args, **kwargs):
            if args[1] == "print":
                return mock_print
            elif args[1] == "kill":
                return mock_kill
            return MagicMock(returncode=1)

        with patch("dystemctl.launchctl.subprocess.run", side_effect=mock_run):
            result = launchctl_stop("com.example.test")
            assert result is True

    def test_stop_legacy(self):
        mock_print = MagicMock(returncode=1)
        mock_stop = MagicMock(returncode=0)

        def mock_run(args, **kwargs):
            if args[1] == "print":
                return mock_print
            elif args[1] == "stop":
                return mock_stop
            return MagicMock(returncode=1)

        with patch("dystemctl.launchctl.subprocess.run", side_effect=mock_run):
            result = launchctl_stop("com.example.test")
            assert result is True


class TestLaunchctlEnable:
    def test_enable_user_agent(self, temp_dir: Path):
        plist_path = temp_dir / "Library" / "LaunchAgents" / "test.plist"
        plist_path.parent.mkdir(parents=True)
        plist_path.touch()

        mock_result = MagicMock(returncode=0)

        with patch("dystemctl.launchctl.subprocess.run", return_value=mock_result):
            result = launchctl_enable(plist_path)
            assert result is True

    def test_enable_system_daemon(self, temp_dir: Path):
        plist_path = temp_dir / "LaunchDaemons" / "test.plist"
        plist_path.parent.mkdir(parents=True)
        plist_path.touch()

        mock_result = MagicMock(returncode=0)

        with patch("dystemctl.launchctl.subprocess.run", return_value=mock_result):
            result = launchctl_enable(plist_path)
            assert result is True

    def test_enable_fallback_legacy(self, temp_dir: Path):
        plist_path = temp_dir / "test.plist"
        plist_path.touch()

        mock_bootstrap = MagicMock(returncode=1)
        mock_load = MagicMock(returncode=0)

        def mock_run(args, **kwargs):
            if args[1] == "bootstrap":
                return mock_bootstrap
            elif args[1] == "load":
                return mock_load
            return MagicMock(returncode=1)

        with patch("dystemctl.launchctl.subprocess.run", side_effect=mock_run):
            result = launchctl_enable(plist_path)
            assert result is True


class TestLaunchctlDisable:
    def test_disable_with_domain(self):
        mock_print = MagicMock(returncode=0)
        mock_bootout = MagicMock(returncode=0)

        def mock_run(args, **kwargs):
            if args[1] == "print":
                return mock_print
            elif args[1] == "bootout":
                return mock_bootout
            return MagicMock(returncode=1)

        with patch("dystemctl.launchctl.subprocess.run", side_effect=mock_run):
            result = launchctl_disable("com.example.test")
            assert result is True

    def test_disable_legacy(self, temp_dir: Path):
        plist_path = temp_dir / "test.plist"
        plist_path.touch()

        mock_print = MagicMock(returncode=1)
        mock_unload = MagicMock(returncode=0)

        def mock_run(args, **kwargs):
            if args[1] == "print":
                return mock_print
            elif args[1] == "bootout":
                return MagicMock(returncode=1)
            elif args[1] == "unload":
                return mock_unload
            return MagicMock(returncode=1)

        with patch("dystemctl.launchctl.subprocess.run", side_effect=mock_run):
            result = launchctl_disable("com.example.test", plist_path)
            assert result is True


class TestGetProcessInfo:
    def test_get_process_info_success(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "102400  2.5 01:30:00 /usr/bin/test --arg value"

        with patch("dystemctl.launchctl.subprocess.run", return_value=mock_result):
            info = get_process_info(1234)
            assert info is not None
            assert info.pid == 1234
            assert info.rss_bytes == 102400 * 1024
            assert info.cpu_percent == 2.5
            assert info.elapsed == timedelta(hours=1, minutes=30, seconds=0)
            assert info.command == "/usr/bin/test --arg value"

    def test_get_process_info_with_days(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "51200  0.0 2-05:30:00 /usr/bin/daemon"

        with patch("dystemctl.launchctl.subprocess.run", return_value=mock_result):
            info = get_process_info(1234)
            assert info is not None
            expected = timedelta(days=2, hours=5, minutes=30, seconds=0)
            assert info.elapsed == expected

    def test_get_process_info_minutes_only(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "25600  1.0 05:30 /usr/bin/short"

        with patch("dystemctl.launchctl.subprocess.run", return_value=mock_result):
            info = get_process_info(1234)
            assert info is not None
            assert info.elapsed == timedelta(minutes=5, seconds=30)

    def test_get_process_info_not_found(self):
        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("dystemctl.launchctl.subprocess.run", return_value=mock_result):
            info = get_process_info(99999)
            assert info is None

    def test_get_process_info_empty_output(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with patch("dystemctl.launchctl.subprocess.run", return_value=mock_result):
            info = get_process_info(1234)
            assert info is None

    def test_get_process_info_invalid_output(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "invalid output"

        with patch("dystemctl.launchctl.subprocess.run", return_value=mock_result):
            info = get_process_info(1234)
            assert info is None
