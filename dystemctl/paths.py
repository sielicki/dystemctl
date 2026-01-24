"""Common paths used throughout dystemctl."""

from __future__ import annotations

from pathlib import Path


def dystemctl_log_dir() -> Path:
    return Path.home() / "Library" / "Logs" / "dystemctl"


def dystemctl_config_dir() -> Path:
    return Path.home() / ".config" / "dystemctl"


def user_launch_agents() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


SYSTEM_LAUNCH_DAEMONS = Path("/Library/LaunchDaemons")
