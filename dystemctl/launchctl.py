"""launchctl backend operations."""

from __future__ import annotations

import os
import re
import subprocess
from datetime import timedelta
from functools import cache
from pathlib import Path

from .models import Domain, ProcessInfo, ServiceStatus


@cache
def detect_domain(label: str) -> Domain | None:
    """Detect which launchd domain a service is loaded in.

    Results are cached to avoid repeated subprocess calls.
    Call detect_domain.cache_clear() to invalidate cache.
    """
    uid = os.getuid()

    # Check gui domain first (most common for user services)
    result = subprocess.run(
        ["launchctl", "print", f"gui/{uid}/{label}"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return Domain.GUI

    # Check user domain
    result = subprocess.run(
        ["launchctl", "print", f"user/{uid}/{label}"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return Domain.USER

    # Check system domain (may require root)
    result = subprocess.run(
        ["launchctl", "print", f"system/{label}"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return Domain.SYSTEM

    return None


def clear_caches():
    """Clear all launchctl module caches."""
    detect_domain.cache_clear()
    get_all_loaded_services.cache_clear()


@cache
def get_all_loaded_services() -> dict[str, tuple[int | None, int | None]]:
    """Get all loaded services in one launchctl call. Returns {label: (pid, exit_status)}."""
    result = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    if result.returncode != 0:
        return {}

    services = {}
    for line in result.stdout.strip().split("\n")[1:]:  # Skip header
        parts = line.split("\t")
        if len(parts) >= 3:
            pid_str, status_str, label = parts[0], parts[1], parts[2]
            pid = int(pid_str) if pid_str != "-" else None
            exit_status = int(status_str) if status_str != "-" else None
            services[label] = (pid, exit_status)
    return services


def get_service_status(label: str, use_cache: bool = False) -> ServiceStatus | None:
    if use_cache:
        loaded = get_all_loaded_services()
        if label in loaded:
            pid, exit_status = loaded[label]
            return ServiceStatus(
                label=label,
                pid=pid,
                last_exit_status=exit_status,
                loaded=True,
                domain=None,
            )
        return ServiceStatus(
            label=label, pid=None, last_exit_status=None, loaded=False, domain=None
        )

    result = subprocess.run(
        ["launchctl", "list", label], capture_output=True, text=True
    )

    if result.returncode != 0:
        return ServiceStatus(
            label=label, pid=None, last_exit_status=None, loaded=False, domain=None
        )

    lines = result.stdout.strip().split("\n")
    pid = None
    exit_status = None

    for line in lines:
        if '"PID"' in line or "PID" in line:
            match = re.search(r"(\d+)", line)
            if match:
                pid = int(match.group(1))
        if '"LastExitStatus"' in line:
            match = re.search(r"(\d+)", line)
            if match:
                exit_status = int(match.group(1))

    if pid is None and len(lines) >= 1:
        parts = lines[0].split()
        if len(parts) >= 3:
            try:
                pid = int(parts[0]) if parts[0] != "-" else None
                exit_status = int(parts[1]) if parts[1] != "-" else None
            except ValueError:
                pass

    domain = detect_domain(label)

    return ServiceStatus(
        label=label,
        pid=pid,
        last_exit_status=exit_status,
        loaded=True,
        domain=domain,
    )


def launchctl_start(label: str) -> bool:
    domain = detect_domain(label)
    if domain:
        # Modern API
        result = subprocess.run(
            ["launchctl", "kickstart", f"{domain.path()}/{label}"],
            capture_output=True,
            text=True,
        )
    else:
        # Legacy API - try to start anyway
        result = subprocess.run(
            ["launchctl", "start", label],
            capture_output=True,
            text=True,
        )

    return result.returncode == 0


def launchctl_stop(label: str) -> bool:
    domain = detect_domain(label)
    if domain:
        result = subprocess.run(
            ["launchctl", "kill", "SIGTERM", f"{domain.path()}/{label}"],
            capture_output=True,
            text=True,
        )
    else:
        result = subprocess.run(
            ["launchctl", "stop", label],
            capture_output=True,
            text=True,
        )

    return result.returncode == 0


def launchctl_enable(plist_path: Path) -> bool:
    uid = os.getuid()
    # Determine domain from path
    path_str = str(plist_path)
    if "/LaunchDaemons" in path_str:
        domain = "system"
    else:
        domain = f"gui/{uid}"

    # Modern API
    result = subprocess.run(
        ["launchctl", "bootstrap", domain, str(plist_path)],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        # Fallback to legacy
        result = subprocess.run(
            ["launchctl", "load", "-w", str(plist_path)],
            capture_output=True,
            text=True,
        )

    return result.returncode == 0


def launchctl_disable(label: str, plist_path: Path | None = None) -> bool:
    domain = detect_domain(label)

    if domain:
        result = subprocess.run(
            ["launchctl", "bootout", f"{domain.path()}/{label}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return True

    # Fallback to legacy
    if plist_path:
        result = subprocess.run(
            ["launchctl", "unload", "-w", str(plist_path)],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    return False


def get_process_info(pid: int) -> ProcessInfo | None:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "rss=,pcpu=,etime=,command="],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return None

    line = result.stdout.strip()
    if not line:
        return None

    parts = line.split(None, 3)
    if len(parts) < 4:
        return None

    try:
        rss_kb = int(parts[0])
        cpu = float(parts[1])
        etime = parts[2]
        command = parts[3]

        # Parse elapsed time (formats: MM:SS, HH:MM:SS, D-HH:MM:SS)
        elapsed = timedelta()
        if "-" in etime:
            days, rest = etime.split("-")
            elapsed += timedelta(days=int(days))
            etime = rest

        time_parts = etime.split(":")
        if len(time_parts) == 2:
            elapsed += timedelta(minutes=int(time_parts[0]), seconds=int(time_parts[1]))
        elif len(time_parts) == 3:
            elapsed += timedelta(
                hours=int(time_parts[0]),
                minutes=int(time_parts[1]),
                seconds=int(time_parts[2]),
            )

        return ProcessInfo(
            pid=pid,
            rss_bytes=rss_kb * 1024,
            cpu_percent=cpu,
            elapsed=elapsed,
            command=command,
        )
    except (ValueError, IndexError):
        return None
