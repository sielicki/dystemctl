"""Shared test fixtures."""

from __future__ import annotations

import plistlib
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from dystemctl.models import ServiceInfo, SocketInfo


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_plist_content() -> dict:
    """Return sample plist content."""
    return {
        "Label": "com.example.testservice",
        "ProgramArguments": ["/usr/bin/testprogram", "--arg1", "value1"],
        "RunAtLoad": True,
        "KeepAlive": False,
        "StandardOutPath": "/var/log/test.log",
        "StandardErrorPath": "/var/log/test.err",
    }


@pytest.fixture
def sample_plist_file(temp_dir: Path, sample_plist_content: dict) -> Path:
    """Create a sample plist file."""
    plist_path = temp_dir / "com.example.testservice.plist"
    with open(plist_path, "wb") as f:
        plistlib.dump(sample_plist_content, f)
    return plist_path


@pytest.fixture
def sample_service_info(sample_plist_file: Path) -> ServiceInfo:
    """Create a sample ServiceInfo."""
    return ServiceInfo(
        label="com.example.testservice",
        plist_path=sample_plist_file,
        program_arguments=["/usr/bin/testprogram", "--arg1", "value1"],
        run_at_load=True,
        keep_alive=False,
        standard_out_path=Path("/var/log/test.log"),
        standard_error_path=Path("/var/log/test.err"),
    )


@pytest.fixture
def homebrew_service_info(temp_dir: Path) -> ServiceInfo:
    """Create a homebrew-style ServiceInfo."""
    plist_path = temp_dir / "homebrew.mxcl.redis.plist"
    plist_content = {
        "Label": "homebrew.mxcl.redis",
        "ProgramArguments": ["/opt/homebrew/bin/redis-server"],
        "RunAtLoad": True,
        "KeepAlive": True,
    }
    with open(plist_path, "wb") as f:
        plistlib.dump(plist_content, f)

    return ServiceInfo(
        label="homebrew.mxcl.redis",
        plist_path=plist_path,
        program_arguments=["/opt/homebrew/bin/redis-server"],
        run_at_load=True,
        keep_alive=True,
    )


@pytest.fixture
def timer_service_info(temp_dir: Path) -> ServiceInfo:
    """Create a timer/scheduled ServiceInfo."""
    plist_path = temp_dir / "com.example.scheduled.plist"
    return ServiceInfo(
        label="com.example.scheduled",
        plist_path=plist_path,
        program_arguments=["/usr/bin/scheduled-task"],
        start_interval=3600,  # Every hour
    )


@pytest.fixture
def calendar_service_info(temp_dir: Path) -> ServiceInfo:
    """Create a calendar-scheduled ServiceInfo."""
    plist_path = temp_dir / "com.example.daily.plist"
    return ServiceInfo(
        label="com.example.daily",
        plist_path=plist_path,
        program_arguments=["/usr/bin/daily-task"],
        start_calendar_interval=[
            {"Hour": 9, "Minute": 0},  # 9:00 AM daily
        ],
    )


@pytest.fixture
def socket_service_info(temp_dir: Path) -> ServiceInfo:
    """Create a socket-activated ServiceInfo."""
    plist_path = temp_dir / "com.example.socket.plist"
    return ServiceInfo(
        label="com.example.socket",
        plist_path=plist_path,
        program_arguments=["/usr/bin/socket-server"],
        sockets=[
            SocketInfo(
                name="main",
                sock_type="stream",
                family="IPv4",
                address="*:8080",
            ),
        ],
    )


@pytest.fixture
def sample_systemd_unit(temp_dir: Path) -> Path:
    """Create a sample systemd unit file."""
    unit_content = """[Unit]
Description=Test Service
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/testservice --config /etc/test.conf
WorkingDirectory=/var/lib/test
User=testuser
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    unit_path = temp_dir / "testservice.service"
    unit_path.write_text(unit_content)
    return unit_path


@pytest.fixture
def complex_systemd_unit(temp_dir: Path) -> Path:
    """Create a more complex systemd unit file."""
    unit_content = """[Unit]
Description=Complex Test Service
Documentation=https://example.com/docs
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
ExecStart=/usr/bin/complex-service \\
    --config /etc/complex.conf \\
    --port 8080
ExecReload=/bin/kill -HUP $MAINPID
WorkingDirectory=/var/lib/complex
User=complex
Group=complex
Environment="FOO=bar" "BAZ=qux"
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
"""
    unit_path = temp_dir / "complex.service"
    unit_path.write_text(unit_content)
    return unit_path
