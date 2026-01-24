"""Data models for dystemctl."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from pathlib import Path


@dataclass
class SocketInfo:
    name: str
    sock_type: str  # stream, dgram
    family: str  # IPv4, IPv6, Unix
    address: str  # host:port or path

    def __str__(self) -> str:
        return f"{self.family}:{self.address} ({self.sock_type})"


@dataclass
class ServiceInfo:
    label: str
    plist_path: Path
    program: str | None = None
    program_arguments: list[str] | None = None
    run_at_load: bool = False
    keep_alive: bool = False
    standard_out_path: Path | None = None
    standard_error_path: Path | None = None
    user_name: str | None = None
    group_name: str | None = None
    working_directory: Path | None = None
    start_interval: int | None = None
    start_calendar_interval: list[dict] | None = None
    sockets: list[SocketInfo] = field(default_factory=list)
    watch_paths: list[str] = field(default_factory=list)
    queue_directories: list[str] = field(default_factory=list)
    mach_services: list[str] = field(default_factory=list)

    @property
    def binary_name(self) -> str | None:
        if self.program:
            return Path(self.program).name
        if self.program_arguments:
            return Path(self.program_arguments[0]).name
        return None

    @property
    def display_name(self) -> str:
        parts = self.label.split(".")
        if len(parts) >= 2 and parts[0] in (
            "com",
            "org",
            "io",
            "net",
            "homebrew",
            "us",
            "de",
            "uk",
            "fr",
        ):
            return parts[-1]
        return self.label

    @property
    def is_timer(self) -> bool:
        return (
            self.start_interval is not None or self.start_calendar_interval is not None
        )

    @property
    def is_socket_activated(self) -> bool:
        return bool(self.sockets)

    @property
    def schedule_description(self) -> str:
        if self.start_interval:
            if self.start_interval < 60:
                return f"every {self.start_interval}s"
            elif self.start_interval < 3600:
                return f"every {self.start_interval // 60}m"
            elif self.start_interval < 86400:
                return f"every {self.start_interval // 3600}h"
            else:
                return f"every {self.start_interval // 86400}d"

        if self.start_calendar_interval:
            schedules = []
            for cal in self.start_calendar_interval:
                parts = []
                if "Weekday" in cal:
                    days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
                    parts.append(days[cal["Weekday"] % 7])
                if "Day" in cal:
                    parts.append(f"day {cal['Day']}")
                if "Month" in cal:
                    parts.append(f"month {cal['Month']}")
                hour = cal.get("Hour", "*")
                minute = cal.get("Minute", 0)
                time_str = (
                    f"{hour}:{minute:02d}"
                    if isinstance(minute, int)
                    else f"{hour}:{minute}"
                )
                parts.append(time_str)
                schedules.append(" ".join(parts))
            return "; ".join(schedules[:2]) + ("..." if len(schedules) > 2 else "")

        return ""


class Domain(Enum):
    SYSTEM = "system"
    GUI = "gui"
    USER = "user"

    def path(self, uid: int | None = None) -> str:
        if self == Domain.SYSTEM:
            return "system"
        uid = uid or os.getuid()
        return f"{self.value}/{uid}"


@dataclass
class ServiceStatus:
    label: str
    pid: int | None
    last_exit_status: int | None
    loaded: bool
    domain: Domain | None


@dataclass
class ProcessInfo:
    pid: int
    rss_bytes: int
    cpu_percent: float
    elapsed: timedelta
    command: str


@dataclass
class ServiceMatch:
    info: ServiceInfo
    confidence: float
    match_type: str
