"""Journal/logging commands: logs, disk-usage, vacuum-*, list-boots."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer

from ..logs import build_log_predicate, parse_time_spec, tail_log_file
from ..models import ServiceInfo
from ..paths import dystemctl_log_dir
from ..registry import resolve_service
from ..utils import format_bytes
from .app import cli_app as app
from .app import console, err_console, service_not_found_error


class OutputFormat(str, Enum):
    short = "short"
    short_iso = "short-iso"
    short_precise = "short-precise"
    short_iso_precise = "short-iso-precise"
    short_full = "short-full"
    short_unix = "short-unix"
    verbose = "verbose"
    json = "json"
    json_pretty = "json-pretty"
    cat = "cat"


class Priority(str, Enum):
    emerg = "0"
    alert = "1"
    crit = "2"
    err = "3"
    warning = "4"
    notice = "5"
    info = "6"
    debug = "7"


@dataclass
class LogEntry:
    """Parsed log entry from macOS unified log."""

    timestamp: datetime
    process: str
    pid: int
    message: str
    subsystem: str = ""
    category: str = ""

    @classmethod
    def from_json(cls, data: dict) -> LogEntry:
        """Parse a log entry from macOS log JSON output."""
        ts_str = data.get("timestamp", "")
        try:
            ts = datetime.strptime(ts_str[:26], "%Y-%m-%d %H:%M:%S.%f")
        except (ValueError, IndexError):
            ts = datetime.now()

        proc_path = data.get("processImagePath", "")
        proc = Path(proc_path).name if proc_path else "kernel"

        return cls(
            timestamp=ts,
            process=proc,
            pid=data.get("processID", 0),
            message=data.get("eventMessage", ""),
            subsystem=data.get("subsystem", ""),
            category=data.get("category", ""),
        )

    def format_short(self, hostname: str) -> str:
        """Format as journalctl short format: Jan 23 10:12:20 hostname process[pid]: message"""
        ts = self.timestamp.strftime("%b %d %H:%M:%S")
        return f"{ts} {hostname} {self.process}[{self.pid}]: {self.message}"

    def format_short_iso(self, hostname: str) -> str:
        """Format with ISO 8601 timestamp: 2026-01-24T00:13:51-0600"""
        ts = self.timestamp.strftime("%Y-%m-%dT%H:%M:%S")
        return f"{ts} {hostname} {self.process}[{self.pid}]: {self.message}"

    def format_short_precise(self, hostname: str) -> str:
        """Format with microsecond precision: Jan 23 10:12:20.123456"""
        ts = self.timestamp.strftime("%b %d %H:%M:%S.%f")
        return f"{ts} {hostname} {self.process}[{self.pid}]: {self.message}"

    def format_short_iso_precise(self, hostname: str) -> str:
        """Format with ISO 8601 and microsecond precision."""
        ts = self.timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f")
        return f"{ts} {hostname} {self.process}[{self.pid}]: {self.message}"

    def format_short_full(self, hostname: str) -> str:
        """Format with full weekday/month name and timezone."""
        ts = self.timestamp.strftime("%a %Y-%m-%d %H:%M:%S")
        return f"{ts} {hostname} {self.process}[{self.pid}]: {self.message}"

    def format_short_unix(self, hostname: str) -> str:
        """Format with Unix timestamp."""
        ts = int(self.timestamp.timestamp())
        return f"{ts} {hostname} {self.process}[{self.pid}]: {self.message}"

    def format_verbose(self, hostname: str, unit: str = "") -> str:
        """Format as journalctl verbose format."""
        lines = [
            f"    _SOURCE_REALTIME_TIMESTAMP={self.timestamp.isoformat()}",
            f"    _HOSTNAME={hostname}",
            f"    _COMM={self.process}",
            f"    _PID={self.pid}",
        ]
        if unit:
            lines.append(f"    _SYSTEMD_UNIT={unit}")
        if self.subsystem:
            lines.append(f"    _SUBSYSTEM={self.subsystem}")
        lines.append(f"    MESSAGE={self.message}")
        lines.append("")
        return "\n".join(lines)

    def format_cat(self) -> str:
        """Format as journalctl cat format: just the message."""
        return self.message


def parse_json_log_stream(stream) -> list[LogEntry]:
    """Parse JSON log entries from macOS log command output.

    The log command outputs a JSON array, but for streaming we may get partial data.
    """
    entries = []
    buffer = ""

    for line in stream:
        buffer += line
        # Try to parse accumulated buffer as JSON array
        try:
            data = json.loads(buffer)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "eventMessage" in item:
                        entries.append(LogEntry.from_json(item))
                buffer = ""
        except json.JSONDecodeError:
            continue

    # Final attempt to parse remaining buffer
    if buffer.strip():
        try:
            data = json.loads(buffer)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "eventMessage" in item:
                        entries.append(LogEntry.from_json(item))
        except json.JSONDecodeError:
            pass

    return entries


@app.command("logs")
def logs(
    unit: Annotated[
        list[str] | None,
        typer.Option(
            "-u", "--unit", help="Service(s) to show logs for (can specify multiple)"
        ),
    ] = None,
    identifier: Annotated[
        list[str] | None,
        typer.Option("-t", "--identifier", help="Syslog identifier(s) to filter by"),
    ] = None,
    follow: Annotated[
        bool, typer.Option("-f", "--follow", help="Follow log output")
    ] = False,
    lines: Annotated[
        int, typer.Option("-n", "--lines", help="Number of lines to show")
    ] = 10,
    since: Annotated[
        str | None,
        typer.Option(
            "-S",
            "--since",
            help="Show entries since TIME (e.g., '1 hour ago', 'today', '@1234567890')",
        ),
    ] = None,
    until: Annotated[
        str | None, typer.Option("-U", "--until", help="Show entries until TIME")
    ] = None,
    boot: Annotated[
        bool, typer.Option("-b", "--boot", help="Show logs from current boot")
    ] = False,
    dmesg: Annotated[
        bool, typer.Option("-k", "--dmesg", help="Show kernel messages only")
    ] = False,
    priority: Annotated[
        Priority | None,
        typer.Option(
            "-p", "--priority", help="Filter by priority (0=emerg to 7=debug)"
        ),
    ] = None,
    output: Annotated[
        OutputFormat, typer.Option("-o", "--output", help="Output format")
    ] = OutputFormat.short,
    reverse: Annotated[
        bool, typer.Option("-r", "--reverse", help="Show newest entries first")
    ] = False,
    grep: Annotated[
        str | None, typer.Option("-g", "--grep", help="Filter by regex pattern")
    ] = None,
    # Command-like options (for journalctl compatibility)
    show_disk_usage: Annotated[
        bool, typer.Option("--disk-usage", help="Show total disk usage of log files")
    ] = False,
    show_list_boots: Annotated[
        bool, typer.Option("--list-boots", help="Show list of boot sessions")
    ] = False,
    vacuum_time_opt: Annotated[
        str | None, typer.Option("--vacuum-time", help="Remove logs older than TIME")
    ] = None,
    vacuum_size_opt: Annotated[
        str | None, typer.Option("--vacuum-size", help="Reduce log size below SIZE")
    ] = None,
    no_pager: Annotated[
        bool, typer.Option("--no-pager", help="Do not pipe output into a pager")
    ] = False,
    all_fields: Annotated[
        bool,
        typer.Option(
            "-a", "--all", help="Show all fields, including long and unprintable"
        ),
    ] = False,
    quiet_opt: Annotated[
        bool,
        typer.Option(
            "-q", "--quiet", help="Do not show info messages and privilege warning"
        ),
    ] = False,
    pager_end: Annotated[
        bool, typer.Option("-e", "--pager-end", help="Jump to end of journal in pager")
    ] = False,
    catalog: Annotated[
        bool,
        typer.Option(
            "-x", "--catalog", help="Add message explanations where available"
        ),
    ] = False,
):
    """View logs for a service (journalctl-style)."""
    # Handle command-like options first
    if show_disk_usage:
        disk_usage()
        return

    if show_list_boots:
        list_boots()
        return

    if vacuum_time_opt:
        vacuum_time(vacuum_time_opt)
        return

    if vacuum_size_opt:
        vacuum_size(vacuum_size_opt)
        return

    hostname = os.uname().nodename.split(".")[0]

    # Handle -k/--dmesg: filter for kernel messages
    if dmesg:
        identifier = identifier or []
        identifier.append("kernel")

    # Resolve units to process names
    process_names: list[str] = []
    resolved_units: list[ServiceInfo] = []

    if unit:
        for u in unit:
            info = resolve_service(u)
            if not info:
                service_not_found_error(u)
                raise typer.Exit(1)
            resolved_units.append(info)
            process_names.append(info.binary_name or info.label.split(".")[-1])

    # Add identifiers directly as process names
    if identifier:
        process_names.extend(identifier)

    # For display purposes
    unit_display = ", ".join(unit) if unit else ""

    if follow:
        # For streaming, use JSON format and parse incrementally
        cmd = ["log", "stream", "--style", "json"]
        predicate = build_log_predicate(
            process_names if process_names else None,
            priority.value if priority else None,
        )
        if predicate:
            cmd.extend(["--predicate", predicate])

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
        )

        # Buffer for accumulating JSON objects
        json_buffer = ""
        brace_count = 0
        in_object = False

        try:
            for char in iter(lambda: proc.stdout.read(1), ""):
                json_buffer += char

                if char == "{":
                    brace_count += 1
                    in_object = True
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0 and in_object:
                        # Complete JSON object
                        try:
                            data = json.loads(json_buffer.strip().lstrip("[,\n"))
                            if isinstance(data, dict) and "eventMessage" in data:
                                entry = LogEntry.from_json(data)
                                if grep and not re.search(grep, entry.message):
                                    pass
                                elif output == OutputFormat.json:
                                    print(
                                        json.dumps(
                                            {
                                                "timestamp": entry.timestamp.isoformat(),
                                                "process": entry.process,
                                                "pid": entry.pid,
                                                "message": entry.message,
                                                "unit": unit_display,
                                            }
                                        )
                                    )
                                elif output == OutputFormat.cat:
                                    print(entry.format_cat())
                                elif output == OutputFormat.verbose:
                                    print(entry.format_verbose(hostname, unit_display))
                                elif output == OutputFormat.short_iso:
                                    print(entry.format_short_iso(hostname))
                                elif output == OutputFormat.short_precise:
                                    print(entry.format_short_precise(hostname))
                                elif output == OutputFormat.short_iso_precise:
                                    print(entry.format_short_iso_precise(hostname))
                                elif output == OutputFormat.short_full:
                                    print(entry.format_short_full(hostname))
                                elif output == OutputFormat.short_unix:
                                    print(entry.format_short_unix(hostname))
                                else:
                                    print(entry.format_short(hostname))
                        except json.JSONDecodeError:
                            pass
                        json_buffer = ""
                        in_object = False
        except KeyboardInterrupt:
            proc.terminate()
        return

    entries: list[LogEntry] = []

    # Collect log lines from file-based logs for each resolved unit
    file_log_lines = []
    if resolved_units and not boot:
        for info in resolved_units:
            if info.standard_out_path:
                file_log_lines.extend(tail_log_file(info.standard_out_path, lines * 2))
            if (
                info.standard_error_path
                and info.standard_error_path != info.standard_out_path
            ):
                file_log_lines.extend(
                    tail_log_file(info.standard_error_path, lines * 2)
                )

    # Query unified log using JSON format
    if not file_log_lines or boot or since or until:
        cmd = ["log", "show", "--style", "json"]

        if boot:
            result = subprocess.run(
                ["sysctl", "-n", "kern.boottime"], capture_output=True, text=True
            )
            if result.returncode == 0:
                match = re.search(r"sec = (\d+)", result.stdout)
                if match:
                    boot_time = datetime.fromtimestamp(int(match.group(1)))
                    cmd.extend(["--start", boot_time.strftime("%Y-%m-%d %H:%M:%S")])
        elif since:
            start_time = parse_time_spec(since)
            if start_time:
                cmd.extend(["--start", start_time.strftime("%Y-%m-%d %H:%M:%S")])
        else:
            cmd.extend(["--last", "1h"])

        if until:
            end_time = parse_time_spec(until)
            if end_time:
                cmd.extend(["--end", end_time.strftime("%Y-%m-%d %H:%M:%S")])

        predicate = build_log_predicate(
            process_names if process_names else None,
            priority.value if priority else None,
        )
        if predicate:
            cmd.extend(["--predicate", predicate])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.stdout:
            try:
                data = json.loads(result.stdout)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "eventMessage" in item:
                            entries.append(LogEntry.from_json(item))
            except json.JSONDecodeError:
                pass

    # Convert file log lines to entries (simple format, just message)
    for line in file_log_lines:
        if line.strip():
            entries.append(
                LogEntry(
                    timestamp=datetime.now(),
                    process="file",
                    pid=0,
                    message=line.strip(),
                )
            )

    # Apply grep filter
    if grep:
        entries = [e for e in entries if re.search(grep, e.message)]

    # Apply reverse
    if reverse:
        entries = list(reversed(entries))

    # Limit entries
    display_entries = entries[-lines:] if not reverse else entries[:lines]

    # Output formatting
    if output == OutputFormat.json:
        json_entries = [
            {
                "timestamp": e.timestamp.isoformat(),
                "process": e.process,
                "pid": e.pid,
                "message": e.message,
                "unit": unit_display,
            }
            for e in display_entries
        ]
        print(json.dumps(json_entries))
    elif output == OutputFormat.json_pretty:
        json_entries = [
            {
                "timestamp": e.timestamp.isoformat(),
                "process": e.process,
                "pid": e.pid,
                "message": e.message,
                "subsystem": e.subsystem,
                "category": e.category,
                "unit": unit_display,
            }
            for e in display_entries
        ]
        print(json.dumps(json_entries, indent=2))
    elif output == OutputFormat.cat:
        for entry in display_entries:
            print(entry.format_cat())
    elif output == OutputFormat.verbose:
        for entry in display_entries:
            print(entry.format_verbose(hostname, unit_display))
    elif output == OutputFormat.short_iso:
        for entry in display_entries:
            print(entry.format_short_iso(hostname))
    elif output == OutputFormat.short_precise:
        for entry in display_entries:
            print(entry.format_short_precise(hostname))
    elif output == OutputFormat.short_iso_precise:
        for entry in display_entries:
            print(entry.format_short_iso_precise(hostname))
    elif output == OutputFormat.short_full:
        for entry in display_entries:
            print(entry.format_short_full(hostname))
    elif output == OutputFormat.short_unix:
        for entry in display_entries:
            print(entry.format_short_unix(hostname))
    else:
        for entry in display_entries:
            print(entry.format_short(hostname))


def _get_dir_size(path: Path) -> str | None:
    """Get human-readable size of a directory using du."""
    try:
        result = subprocess.run(
            ["du", "-sh", str(path)],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout:
            parts = result.stdout.split()
            if parts:
                return parts[0]
    except OSError:
        pass
    return None


@app.command("disk-usage")
def disk_usage():
    """Show disk usage of logs (journalctl --disk-usage equivalent)."""
    log_locations = []

    paths_to_check = [
        ("Unified log database", Path("/var/db/diagnostics")),
        ("System logs", Path("/var/log")),
        ("User logs", Path.home() / "Library" / "Logs"),
        ("dystemctl logs", dystemctl_log_dir()),
    ]

    for name, path in paths_to_check:
        if path.exists():
            if size := _get_dir_size(path):
                log_locations.append((name, path, size))

    if log_locations:
        console.print("[bold]Log storage usage:[/bold]")
        for name, path, size in log_locations:
            console.print(f"  {name}: {size} ({path})")
    else:
        console.print("[dim]No log locations found[/dim]")


@app.command("vacuum-time")
def vacuum_time(
    time_spec: Annotated[
        str, typer.Argument(help="Delete logs older than this (e.g., '7d', '2w', '1m')")
    ],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", "-n", help="Show what would be deleted")
    ] = False,
):
    """Delete old log files (like journalctl --vacuum-time).

    Time specifications: 30s, 5m, 2h, 7d, 2w, 1m (month), 1y
    """

    unit_map = {
        "s": 1,
        "sec": 1,
        "second": 1,
        "seconds": 1,
        "m": 60,
        "min": 60,
        "minute": 60,
        "minutes": 60,
        "h": 3600,
        "hour": 3600,
        "hours": 3600,
        "d": 86400,
        "day": 86400,
        "days": 86400,
        "w": 604800,
        "week": 604800,
        "weeks": 604800,
        "M": 2592000,
        "month": 2592000,
        "months": 2592000,
        "y": 31536000,
        "year": 31536000,
        "years": 31536000,
    }

    match = re.match(r"(\d+)\s*([a-zA-Z]+)", time_spec)
    if not match:
        err_console.print(f"[red]Invalid time spec:[/red] {time_spec}")
        raise typer.Exit(1)

    amount = int(match.group(1))
    unit = match.group(2)
    if unit not in unit_map:
        err_console.print(f"[red]Unknown time unit:[/red] {unit}")
        raise typer.Exit(1)

    max_age_seconds = amount * unit_map[unit]
    cutoff_time = datetime.now().timestamp() - max_age_seconds

    log_dirs = [
        dystemctl_log_dir(),
        Path.home() / "Library" / "Logs",
    ]

    total_freed = 0
    files_deleted = 0

    for log_dir in log_dirs:
        if not log_dir.exists():
            continue

        for log_file in log_dir.glob("*.log"):
            if log_file.stat().st_mtime < cutoff_time:
                size = log_file.stat().st_size
                if dry_run:
                    console.print(
                        f"[dim]Would delete:[/dim] {log_file} ({format_bytes(size)})"
                    )
                else:
                    log_file.unlink()
                    files_deleted += 1
                total_freed += size

    if dry_run:
        console.print(
            f"\n[dim]Would free {format_bytes(total_freed)} in {files_deleted} file(s)[/dim]"
        )
    else:
        console.print(
            f"[green]Deleted {files_deleted} file(s), freed {format_bytes(total_freed)}[/green]"
        )


@app.command("vacuum-size")
def vacuum_size(
    max_size: Annotated[
        str, typer.Argument(help="Maximum total log size (e.g., '100M', '1G')")
    ],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", "-n", help="Show what would be deleted")
    ] = False,
):
    """Delete log files to stay under size limit (like journalctl --vacuum-size).

    Size specifications: 100K, 50M, 1G
    """
    size_map = {
        "K": 1024,
        "KB": 1024,
        "M": 1024**2,
        "MB": 1024**2,
        "G": 1024**3,
        "GB": 1024**3,
        "T": 1024**4,
        "TB": 1024**4,
    }

    match = re.match(r"(\d+(?:\.\d+)?)\s*([KMGT]B?)", max_size, re.I)
    if not match:
        err_console.print(f"[red]Invalid size spec:[/red] {max_size}")
        raise typer.Exit(1)

    amount = float(match.group(1))
    unit = match.group(2).upper()
    if unit not in size_map:
        err_console.print(f"[red]Unknown size unit:[/red] {unit}")
        raise typer.Exit(1)

    max_bytes = int(amount * size_map[unit])

    log_dirs = [
        dystemctl_log_dir(),
        Path.home() / "Library" / "Logs",
    ]

    all_logs = []
    for log_dir in log_dirs:
        if log_dir.exists():
            for log_file in log_dir.glob("*.log"):
                stat = log_file.stat()
                all_logs.append((log_file, stat.st_size, stat.st_mtime))

    all_logs.sort(key=lambda x: x[2])

    current_size = sum(size for _, size, _ in all_logs)

    if current_size <= max_bytes:
        console.print(
            f"[green]Current size ({format_bytes(current_size)}) is within limit ({format_bytes(max_bytes)})[/green]"
        )
        return

    total_freed = 0
    files_deleted = 0

    for log_file, size, _ in all_logs:
        if current_size - total_freed <= max_bytes:
            break

        if dry_run:
            console.print(f"[dim]Would delete:[/dim] {log_file} ({format_bytes(size)})")
        else:
            log_file.unlink()
            files_deleted += 1
        total_freed += size

    if dry_run:
        console.print(
            f"\n[dim]Would free {format_bytes(total_freed)} in {files_deleted} file(s)[/dim]"
        )
    else:
        console.print(
            f"[green]Deleted {files_deleted} file(s), freed {format_bytes(total_freed)}[/green]"
        )


@app.command("list-boots")
def list_boots():
    """List boot sessions (limited support on macOS)."""
    # Get current boot time
    result = subprocess.run(
        ["sysctl", "-n", "kern.boottime"], capture_output=True, text=True
    )
    if result.returncode == 0:
        match = re.search(r"sec = (\d+)", result.stdout)
        if match:
            boot_time = datetime.fromtimestamp(int(match.group(1)))
            console.print("[bold]Boot sessions:[/bold]")
            console.print(
                f"   0 [green]current[/green]  {boot_time.strftime('%a %Y-%m-%d %H:%M:%S')}"
            )
            console.print()
            console.print(
                "[dim]Note: macOS does not retain boot history like systemd.[/dim]"
            )
            console.print("[dim]Only the current boot is available.[/dim]")
            return

    err_console.print("[red]Could not determine boot time[/red]")
    raise typer.Exit(1)


# --- Unit File Import/Export ---
