"""Log tailing and os_log integration."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path


def tail_log_file(path: Path, lines: int = 10) -> list[str]:
    if not path.exists():
        return []

    result = subprocess.run(
        ["tail", "-n", str(lines), str(path)],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return []

    return result.stdout.strip().split("\n")


def stream_os_log(process: str) -> subprocess.Popen:
    return subprocess.Popen(
        [
            "log",
            "stream",
            "--predicate",
            f'process == "{process}"',
            "--style",
            "compact",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def query_os_log(process: str, last_minutes: int = 5) -> list[dict]:
    """Query macOS unified log and return structured log entries."""
    result = subprocess.run(
        [
            "log",
            "show",
            "--predicate",
            f'process == "{process}"',
            "--last",
            f"{last_minutes}m",
            "--style",
            "json",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return []

    try:
        data = json.loads(result.stdout)
        if isinstance(data, list):
            return [
                item
                for item in data
                if isinstance(item, dict) and "eventMessage" in item
            ]
    except json.JSONDecodeError:
        pass

    return []


def parse_time_spec(spec: str) -> datetime | None:
    if not spec:
        return None

    now = datetime.now()

    # Unix epoch timestamp: @1234567890 or @1234567890.123
    if spec.startswith("@"):
        try:
            timestamp = float(spec[1:])
            return datetime.fromtimestamp(timestamp)
        except (ValueError, OSError):
            return None

    if spec == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if spec == "yesterday":
        return (now - timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    if spec == "tomorrow":
        return (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    if spec == "now":
        return now

    # Relative times: "2 hours ago", "5 minutes", "1 day"
    rel_match = re.match(
        r"(\d+)\s*(seconds?|minutes?|hours?|days?|weeks?|months?)(?:\s*ago)?",
        spec,
        re.I,
    )
    if rel_match:
        amount = int(rel_match.group(1))
        unit = rel_match.group(2).lower().rstrip("s")
        delta_map = {
            "second": 1,
            "minute": 60,
            "hour": 3600,
            "day": 86400,
            "week": 604800,
            "month": 2592000,  # 30 days
        }
        return now - timedelta(seconds=amount * delta_map.get(unit, 1))

    # Negative relative: "-5min", "-2h", "-1d"
    neg_rel_match = re.match(r"-(\d+)(s|m|min|h|d|w)", spec, re.I)
    if neg_rel_match:
        amount = int(neg_rel_match.group(1))
        unit = neg_rel_match.group(2).lower()
        unit_map = {
            "s": 1,
            "m": 60,
            "min": 60,
            "h": 3600,
            "d": 86400,
            "w": 604800,
        }
        return now - timedelta(seconds=amount * unit_map.get(unit, 1))

    for fmt in [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%H:%M:%S",
        "%H:%M",
    ]:
        try:
            parsed = datetime.strptime(spec, fmt)
            if fmt in ("%H:%M:%S", "%H:%M"):
                parsed = parsed.replace(year=now.year, month=now.month, day=now.day)
            return parsed
        except ValueError:
            continue

    return None


def build_log_predicate(processes: list[str] | str | None, priority: str | None) -> str:
    """Build a macOS log predicate string.

    Args:
        processes: Single process name or list of process names to filter by
        priority: Syslog priority level (0-7)

    Returns:
        Predicate string for use with `log show/stream --predicate`
    """
    predicates = []

    # Handle both single string and list of strings for backwards compatibility
    if processes:
        if isinstance(processes, str):
            processes = [processes]

        if len(processes) == 1:
            predicates.append(f'process == "{processes[0]}"')
        elif len(processes) > 1:
            # OR multiple processes together
            process_preds = [f'process == "{p}"' for p in processes]
            predicates.append(f"({' OR '.join(process_preds)})")

    if priority:
        level_map = {
            "0": "Fault",
            "1": "Fault",
            "2": "Fault",
            "3": "Error",
            "4": "Default",
            "5": "Default",
            "6": "Info",
            "7": "Debug",
        }
        level = level_map.get(priority, "Default")
        predicates.append(f"messageType >= {level}")

    return " AND ".join(predicates) if predicates else ""
