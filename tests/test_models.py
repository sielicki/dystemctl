"""Tests for dystemctl.models module."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from dystemctl.models import (
    Domain,
    ProcessInfo,
    ServiceInfo,
    ServiceMatch,
    ServiceStatus,
    SocketInfo,
)


class TestSocketInfo:
    def test_str_representation(self):
        sock = SocketInfo(
            name="http",
            sock_type="stream",
            family="IPv4",
            address="*:8080",
        )
        assert str(sock) == "IPv4:*:8080 (stream)"

    def test_unix_socket(self):
        sock = SocketInfo(
            name="unix",
            sock_type="stream",
            family="Unix",
            address="/var/run/test.sock",
        )
        assert str(sock) == "Unix:/var/run/test.sock (stream)"

    def test_dgram_socket(self):
        sock = SocketInfo(
            name="udp",
            sock_type="dgram",
            family="IPv4",
            address="*:5353",
        )
        assert str(sock) == "IPv4:*:5353 (dgram)"


class TestServiceInfo:
    def test_binary_name_from_program(self, temp_dir: Path):
        info = ServiceInfo(
            label="test",
            plist_path=temp_dir / "test.plist",
            program="/usr/bin/myprogram",
        )
        assert info.binary_name == "myprogram"

    def test_binary_name_from_program_arguments(self, temp_dir: Path):
        info = ServiceInfo(
            label="test",
            plist_path=temp_dir / "test.plist",
            program_arguments=[
                "/opt/homebrew/bin/redis-server",
                "--config",
                "/etc/redis.conf",
            ],
        )
        assert info.binary_name == "redis-server"

    def test_binary_name_none(self, temp_dir: Path):
        info = ServiceInfo(
            label="test",
            plist_path=temp_dir / "test.plist",
        )
        assert info.binary_name is None

    def test_display_name_with_com_prefix(self, temp_dir: Path):
        info = ServiceInfo(
            label="com.apple.Finder",
            plist_path=temp_dir / "test.plist",
        )
        assert info.display_name == "Finder"

    def test_display_name_with_org_prefix(self, temp_dir: Path):
        info = ServiceInfo(
            label="org.mozilla.firefox",
            plist_path=temp_dir / "test.plist",
        )
        assert info.display_name == "firefox"

    def test_display_name_with_homebrew_prefix(self, temp_dir: Path):
        info = ServiceInfo(
            label="homebrew.mxcl.postgresql@14",
            plist_path=temp_dir / "test.plist",
        )
        assert info.display_name == "postgresql@14"

    def test_display_name_without_prefix(self, temp_dir: Path):
        info = ServiceInfo(
            label="simple-service",
            plist_path=temp_dir / "test.plist",
        )
        assert info.display_name == "simple-service"

    def test_display_name_short_label(self, temp_dir: Path):
        info = ServiceInfo(
            label="svc",
            plist_path=temp_dir / "test.plist",
        )
        assert info.display_name == "svc"

    def test_is_timer_with_interval(self, timer_service_info: ServiceInfo):
        assert timer_service_info.is_timer is True

    def test_is_timer_with_calendar(self, calendar_service_info: ServiceInfo):
        assert calendar_service_info.is_timer is True

    def test_is_timer_false(self, sample_service_info: ServiceInfo):
        assert sample_service_info.is_timer is False

    def test_is_socket_activated(self, socket_service_info: ServiceInfo):
        assert socket_service_info.is_socket_activated is True

    def test_is_socket_activated_false(self, sample_service_info: ServiceInfo):
        assert sample_service_info.is_socket_activated is False

    def test_schedule_description_seconds(self, temp_dir: Path):
        info = ServiceInfo(
            label="test",
            plist_path=temp_dir / "test.plist",
            start_interval=30,
        )
        assert info.schedule_description == "every 30s"

    def test_schedule_description_minutes(self, temp_dir: Path):
        info = ServiceInfo(
            label="test",
            plist_path=temp_dir / "test.plist",
            start_interval=300,
        )
        assert info.schedule_description == "every 5m"

    def test_schedule_description_hours(self, temp_dir: Path):
        info = ServiceInfo(
            label="test",
            plist_path=temp_dir / "test.plist",
            start_interval=7200,
        )
        assert info.schedule_description == "every 2h"

    def test_schedule_description_days(self, temp_dir: Path):
        info = ServiceInfo(
            label="test",
            plist_path=temp_dir / "test.plist",
            start_interval=172800,
        )
        assert info.schedule_description == "every 2d"

    def test_schedule_description_calendar(self, temp_dir: Path):
        info = ServiceInfo(
            label="test",
            plist_path=temp_dir / "test.plist",
            start_calendar_interval=[
                {"Hour": 9, "Minute": 30},
            ],
        )
        assert info.schedule_description == "9:30"

    def test_schedule_description_calendar_weekday(self, temp_dir: Path):
        info = ServiceInfo(
            label="test",
            plist_path=temp_dir / "test.plist",
            start_calendar_interval=[
                {"Weekday": 1, "Hour": 9, "Minute": 0},  # Monday 9:00
            ],
        )
        assert "Mon" in info.schedule_description
        assert "9:00" in info.schedule_description

    def test_schedule_description_multiple_calendars(self, temp_dir: Path):
        info = ServiceInfo(
            label="test",
            plist_path=temp_dir / "test.plist",
            start_calendar_interval=[
                {"Hour": 9, "Minute": 0},
                {"Hour": 17, "Minute": 0},
                {"Hour": 12, "Minute": 0},
            ],
        )
        desc = info.schedule_description
        assert "9:00" in desc
        assert "17:00" in desc
        assert "..." in desc  # Should truncate after 2

    def test_schedule_description_empty(self, sample_service_info: ServiceInfo):
        assert sample_service_info.schedule_description == ""


class TestDomain:
    def test_system_domain_path(self):
        assert Domain.SYSTEM.path() == "system"

    def test_gui_domain_path(self):
        import os

        uid = os.getuid()
        assert Domain.GUI.path() == f"gui/{uid}"

    def test_user_domain_path(self):
        import os

        uid = os.getuid()
        assert Domain.USER.path() == f"user/{uid}"

    def test_domain_with_custom_uid(self):
        assert Domain.GUI.path(uid=1000) == "gui/1000"
        assert Domain.USER.path(uid=1000) == "user/1000"


class TestServiceStatus:
    def test_service_status_running(self):
        status = ServiceStatus(
            label="test",
            pid=1234,
            last_exit_status=None,
            loaded=True,
            domain=Domain.GUI,
        )
        assert status.pid == 1234
        assert status.loaded is True

    def test_service_status_stopped(self):
        status = ServiceStatus(
            label="test",
            pid=None,
            last_exit_status=0,
            loaded=True,
            domain=Domain.GUI,
        )
        assert status.pid is None
        assert status.loaded is True

    def test_service_status_failed(self):
        status = ServiceStatus(
            label="test",
            pid=None,
            last_exit_status=1,
            loaded=True,
            domain=Domain.GUI,
        )
        assert status.pid is None
        assert status.last_exit_status == 1


class TestProcessInfo:
    def test_process_info(self):
        info = ProcessInfo(
            pid=1234,
            rss_bytes=104857600,  # 100 MB
            cpu_percent=5.5,
            elapsed=timedelta(hours=2, minutes=30),
            command="/usr/bin/test --arg",
        )
        assert info.pid == 1234
        assert info.rss_bytes == 104857600
        assert info.cpu_percent == 5.5
        assert info.elapsed.total_seconds() == 9000


class TestServiceMatch:
    def test_service_match(self, sample_service_info: ServiceInfo):
        match = ServiceMatch(
            info=sample_service_info,
            confidence=0.95,
            match_type="exact",
        )
        assert match.confidence == 0.95
        assert match.match_type == "exact"
        assert match.info.label == "com.example.testservice"
