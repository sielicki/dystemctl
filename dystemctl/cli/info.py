"""Service information commands: status, show, list-*, is-*, cat, edit."""

from __future__ import annotations

import base64
import fnmatch
import json
import os
import plistlib
import shutil
import subprocess
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer
from rich.tree import Tree

from ..launchctl import (
    clear_caches,
    get_all_loaded_services,
    get_process_info,
    get_service_status,
)
from ..logs import query_os_log, tail_log_file
from ..registry import build_registry, get_all_services, resolve_service
from ..utils import format_bytes, format_elapsed
from . import app as _app_module
from .app import (
    OptionalServiceArg,
    ServiceArg,
    console,
    err_console,
    filter_by_scope,
    service_completion,
    service_not_found_error,
)
from .app import (
    cli_app as app,
)

# Forward import for LogEntry
from .journal import LogEntry


@app.command()
def clean(
    services: Annotated[list[str], typer.Argument(autocompletion=service_completion)],
    what: Annotated[
        str | None,
        typer.Option("--what", "-w", help="What to clean: logs, cache, runtime, all"),
    ] = "all",
):
    """Clean runtime data, logs, or caches for service(s)."""

    valid_whats = {"logs", "cache", "runtime", "all"}
    if what not in valid_whats:
        err_console.print(
            f"[red]Invalid --what:[/red] {what}. Must be one of: {', '.join(valid_whats)}"
        )
        raise typer.Exit(1)

    for service in services:
        info = resolve_service(service)
        if not info:
            service_not_found_error(service)
            continue

        cleaned = []

        if what in ("logs", "all"):
            if info.standard_out_path and info.standard_out_path.exists():
                info.standard_out_path.unlink()
                cleaned.append(f"stdout log ({info.standard_out_path})")
            if info.standard_error_path and info.standard_error_path.exists():
                if info.standard_error_path != info.standard_out_path:
                    info.standard_error_path.unlink()
                    cleaned.append(f"stderr log ({info.standard_error_path})")

            dystemctl_log = (
                Path.home()
                / "Library"
                / "Logs"
                / "dystemctl"
                / f"{info.label.split('.')[-1]}.log"
            )
            if dystemctl_log.exists():
                dystemctl_log.unlink()
                cleaned.append("dystemctl log")

        if what in ("cache", "all"):
            cache_dir = Path.home() / "Library" / "Caches" / info.label
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
                cleaned.append(f"cache ({cache_dir})")

        if what in ("runtime", "all"):
            tmp_pattern = Path(os.environ.get("TMPDIR", "/tmp"))
            for tmp_file in tmp_pattern.glob(f"*{info.label.split('.')[-1]}*"):
                if tmp_file.is_file():
                    tmp_file.unlink()
                    cleaned.append(f"tmp file ({tmp_file.name})")

        if cleaned:
            console.print(f"[green]Cleaned[/green] {info.label}: {', '.join(cleaned)}")
        else:
            console.print(f"[dim]Nothing to clean for[/dim] {info.label}")


@app.command()
def status(
    service: OptionalServiceArg = None,
    lines: Annotated[
        int, typer.Option("-n", "--lines", help="Number of log lines to show")
    ] = 10,
):
    """Show status of a service (or all services if none specified)."""
    if service is None:
        list_units(all_=True, state=None, type_=None, output="table")
        return

    info = resolve_service(service)
    if not info:
        service_not_found_error(service)
        raise typer.Exit(1)

    svc_status = get_service_status(info.label)
    proc_info = (
        get_process_info(svc_status.pid) if svc_status and svc_status.pid else None
    )

    # Determine status indicator and colors
    if svc_status and svc_status.pid:
        ind = "\033[32m●\033[0m"
    elif svc_status and svc_status.loaded and svc_status.last_exit_status:
        ind = "\033[31m●\033[0m"
    else:
        ind = "○"

    print(f"{ind} {info.label} - {info.display_name}")

    # Loaded line
    enabled_str = (
        "enabled"
        if info.run_at_load or (svc_status and svc_status.loaded)
        else "disabled"
    )
    print(f"     Loaded: loaded ({info.plist_path}; {enabled_str})")

    # Active line with timing info
    if svc_status and svc_status.pid:
        if proc_info and proc_info.elapsed:
            since_time = datetime.now() - proc_info.elapsed
            since_str = since_time.strftime("%a %Y-%m-%d %H:%M:%S")
            duration = format_elapsed(proc_info.elapsed)
            active_plain = (
                f"\033[32mactive (running)\033[0m since {since_str}; {duration} ago"
            )
        else:
            active_plain = "\033[32mactive (running)\033[0m"
    elif svc_status and svc_status.loaded:
        if svc_status.last_exit_status and svc_status.last_exit_status != 0:
            active_plain = f"\033[31mfailed\033[0m (Result: exit-code, code={svc_status.last_exit_status})"
        else:
            active_plain = "inactive (dead)"
    else:
        active_plain = "inactive (dead)"
    print(f"     Active: {active_plain}")

    # Main PID
    if svc_status and svc_status.pid:
        proc_name = info.binary_name or info.label.split(".")[-1]
        print(f"   Main PID: {svc_status.pid} ({proc_name})")

    # Memory and CPU
    if proc_info:
        print(f"     Memory: {format_bytes(proc_info.rss_bytes)}")
        if proc_info.cpu_percent is not None:
            print(f"        CPU: {proc_info.cpu_percent:.1f}%")

    # Triggers (launchd-specific)
    triggers = []
    if info.keep_alive:
        triggers.append("KeepAlive")
    if info.is_timer:
        triggers.append(f"Timer: {info.schedule_description}")
    if info.sockets:
        triggers.append(f"Socket: {info.sockets[0].address}")
    if info.watch_paths:
        triggers.append(f"Path: {info.watch_paths[0]}")

    if triggers:
        print(f"    Trigger: {'; '.join(triggers)}")

    if lines > 0:
        print()
        hostname = os.uname().nodename.split(".")[0]
        proc_name = info.binary_name or info.label.split(".")[-1]
        entries: list[LogEntry] = []

        # Try file-based logs first
        file_log_lines = []
        if info.standard_out_path:
            file_log_lines.extend(tail_log_file(info.standard_out_path, lines))
        if (
            info.standard_error_path
            and info.standard_error_path != info.standard_out_path
        ):
            file_log_lines.extend(tail_log_file(info.standard_error_path, lines))

        for line in file_log_lines:
            if line.strip():
                entries.append(
                    LogEntry(
                        timestamp=datetime.now(),
                        process=proc_name,
                        pid=svc_status.pid if svc_status else 0,
                        message=line.strip(),
                    )
                )

        # Try unified log if no file logs
        if not entries and info.binary_name:
            log_data = query_os_log(info.binary_name, 10)
            for item in log_data:
                entries.append(LogEntry.from_json(item))

        for entry in entries[-lines:]:
            print(entry.format_short(hostname))


@app.command()
def show(
    service: ServiceArg,
    property_: Annotated[
        str | None,
        typer.Option("-p", "--property", help="Show only specific property"),
    ] = None,
    all_: Annotated[
        bool,
        typer.Option("--all", "-a", help="Show all properties including empty ones"),
    ] = False,
):
    """Show properties of a service (machine-readable)."""
    info = resolve_service(service)
    if not info:
        service_not_found_error(service)
        raise typer.Exit(1)

    svc_status = get_service_status(info.label)
    proc_info = (
        get_process_info(svc_status.pid) if svc_status and svc_status.pid else None
    )

    props = {
        "Id": info.label,
        "Names": info.label,
        "LoadState": "loaded" if svc_status and svc_status.loaded else "not-found",
        "ActiveState": "active" if svc_status and svc_status.pid else "inactive",
        "SubState": "running" if svc_status and svc_status.pid else "dead",
        "FragmentPath": str(info.plist_path),
        "MainPID": svc_status.pid if svc_status else 0,
        "ExecMainPID": svc_status.pid if svc_status else 0,
        "ExecMainStatus": svc_status.last_exit_status if svc_status else 0,
        "MemoryCurrent": proc_info.rss_bytes if proc_info else 0,
        "CPUUsageNSec": int(proc_info.cpu_percent * 1e9 / 100) if proc_info else 0,
    }

    if info.program:
        props["ExecStart"] = info.program
    elif info.program_arguments:
        props["ExecStart"] = " ".join(info.program_arguments)

    if info.working_directory:
        props["WorkingDirectory"] = str(info.working_directory)
    if info.user_name:
        props["User"] = info.user_name

    if all_:
        props.update(
            {
                "Description": info.display_name,
                "Type": "simple",
                "Restart": "always" if info.keep_alive else "no",
                "RestartUSec": "100ms",
                "TimeoutStartUSec": "1min 30s",
                "TimeoutStopUSec": "1min 30s",
                "RuntimeMaxUSec": "infinity",
                "WatchdogUSec": "0",
                "WatchdogTimestampMonotonic": "0",
                "RootDirectoryStartOnly": "no",
                "RemainAfterExit": "no",
                "GuessMainPID": "yes",
                "SuccessExitStatus": "",
                "RestartPreventExitStatus": "",
                "RestartForceExitStatus": "",
                "RootDirectory": "",
                "RootImage": "",
                "StandardInput": "null",
                "StandardOutput": str(info.standard_out_path)
                if info.standard_out_path
                else "journal",
                "StandardError": str(info.standard_error_path)
                if info.standard_error_path
                else "inherit",
                "TTYPath": "",
                "SyslogIdentifier": info.binary_name or info.label.split(".")[-1],
                "SyslogFacility": "daemon",
                "SyslogLevel": "info",
                "SyslogLevelPrefix": "yes",
                "Capabilities": "",
                "SecureBits": "0",
                "CapabilityBoundingSet": "cap_chown cap_dac_override",
                "AmbientCapabilities": "",
                "DynamicUser": "no",
                "PrivateTmp": "no",
                "PrivateDevices": "no",
                "ProtectHome": "no",
                "ProtectSystem": "no",
                "SameProcessGroup": "no",
                "IgnoreSIGPIPE": "yes",
                "NoNewPrivileges": "no",
                "KillMode": "control-group",
                "KillSignal": "15",
                "SendSIGKILL": "yes",
                "SendSIGHUP": "no",
                "Group": info.group_name or "",
                "EnvironmentFiles": "",
                "Nice": "0",
                "OOMScoreAdjust": "0",
                "CPUSchedulingPolicy": "0",
                "CPUSchedulingPriority": "0",
                "CPUSchedulingResetOnFork": "no",
                "ControlGroup": f"/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service",
                "MemoryHigh": "infinity",
                "MemoryMax": "infinity",
                "MemorySwapMax": "infinity",
                "CPUWeight": "100",
                "StartupCPUWeight": "100",
                "CPUQuota": "infinity",
                "IOWeight": "100",
                "StartupIOWeight": "100",
                "TasksMax": "infinity",
                "Result": "success"
                if not (svc_status and svc_status.last_exit_status)
                else "exit-code",
                "ConditionResult": "yes",
                "ConditionTimestamp": "",
                "AssertResult": "yes",
                "NFileDescriptorStore": "0",
                "StatusText": "",
            }
        )

    if property_:
        # Support comma-separated property names like systemctl
        requested_props = [p.strip() for p in property_.split(",")]
        for prop_name in requested_props:
            if prop_name in props:
                print(f"{prop_name}={props[prop_name]}")
            else:
                print(f"{prop_name}=")
    else:
        for key, value in props.items():
            print(f"{key}={value}")


class UnitState(str, Enum):
    running = "running"
    exited = "exited"
    failed = "failed"
    inactive = "inactive"


class UnitType(str, Enum):
    service = "service"
    timer = "timer"
    socket = "socket"


def get_unit_type(info) -> str:
    if info.is_socket_activated:
        return "socket"
    if info.is_timer:
        return "timer"
    return "service"


@app.command("list-units")
def list_units(
    pattern: Annotated[
        str | None, typer.Argument(help="Pattern to filter units (supports * and ?)")
    ] = None,
    all_: Annotated[
        bool, typer.Option("--all", "-a", help="Show all units including inactive")
    ] = False,
    state: Annotated[
        UnitState | None, typer.Option("--state", help="Filter by state")
    ] = None,
    type_: Annotated[
        UnitType | None,
        typer.Option("-t", "--type", help="Filter by type (service, timer, socket)"),
    ] = None,
    failed: Annotated[
        bool, typer.Option("--failed", help="Show only failed units")
    ] = False,
    output: Annotated[
        str | None,
        typer.Option("-o", "--output", help="Output format: table, json"),
    ] = "table",
    no_legend: Annotated[
        bool, typer.Option("--no-legend", help="Suppress column headers and footer")
    ] = False,
):
    """List services."""
    # Combine local and global no-legend setting
    suppress_legend = no_legend or _app_module.NO_LEGEND

    # --failed is shorthand for --state=failed
    if failed:
        state = UnitState.failed
        all_ = True  # Need to include all to find failed ones

    get_all_loaded_services.cache_clear()
    services = filter_by_scope(get_all_services())

    # Filter by pattern if provided
    if pattern:
        services = [
            s for s in services if fnmatch.fnmatch(s.label.lower(), pattern.lower())
        ]

    if type_:
        services = [s for s in services if get_unit_type(s) == type_.value]

    rows = []
    for info in sorted(services, key=lambda s: s.label):
        svc_status = get_service_status(info.label, use_cache=True)

        if svc_status and svc_status.pid:
            load = "loaded"
            active_state = "active"
            sub = "running"
            current_state = UnitState.running
        elif svc_status and svc_status.loaded:
            load = "loaded"
            if svc_status.last_exit_status == 0:
                active_state = "inactive"
                sub = "exited"
                current_state = UnitState.exited
            else:
                active_state = "failed"
                sub = "failed"
                current_state = UnitState.failed
        else:
            load = "not-found"
            active_state = "inactive"
            sub = "dead"
            current_state = UnitState.inactive
            if not all_:
                continue

        if state and current_state != state:
            continue

        rows.append(
            {
                "unit": info.label,
                "load": load,
                "active": active_state,
                "sub": sub,
                "description": info.display_name,
                "pid": svc_status.pid if svc_status else None,
            }
        )

    if output == "json":
        console.print(json.dumps(rows, indent=2))
        return

    if not rows:
        if not suppress_legend:
            print("  UNIT LOAD ACTIVE SUB DESCRIPTION")
            print()
            print("0 loaded units listed.")
        return

    # Calculate column widths based on content (like real systemctl)
    unit_width = max(len(r["unit"]) for r in rows)
    unit_width = max(unit_width, 4) + 2  # At least "UNIT" + padding

    # Print header (2-space indent like real systemctl)
    if not suppress_legend:
        header = (
            f"{'UNIT':<{unit_width}} {'LOAD':<6} {'ACTIVE':<6} {'SUB':<7} DESCRIPTION"
        )
        print(f"  {header}")

    for row in rows:
        unit = row["unit"]
        load = row["load"]
        active = row["active"]
        sub = row["sub"]
        desc = row["description"]

        print(f"  {unit:<{unit_width}} {load:<6} {active:<6} {sub:<7} {desc}")

    if not suppress_legend:
        print()
        print(f"{len(rows)} loaded units listed.")


class UnitFileState(str, Enum):
    enabled = "enabled"
    disabled = "disabled"
    masked = "masked"
    static = "static"


@app.command("list-unit-files")
def list_unit_files(
    pattern: Annotated[
        str | None, typer.Argument(help="Pattern to filter units (supports * and ?)")
    ] = None,
    state: Annotated[
        UnitFileState | None, typer.Option("--state", help="Filter by state")
    ] = None,
):
    """List installed service files."""
    services = filter_by_scope(get_all_services())

    # Filter by pattern if provided
    if pattern:
        services = [
            s for s in services if fnmatch.fnmatch(s.label.lower(), pattern.lower())
        ]
    get_all_loaded_services.cache_clear()
    loaded = get_all_loaded_services()

    uid = os.getuid()
    disabled_result = subprocess.run(
        ["launchctl", "print-disabled", f"gui/{uid}"],
        capture_output=True,
        text=True,
    )
    disabled_output = disabled_result.stdout if disabled_result.returncode == 0 else ""

    rows = []
    for info in sorted(services, key=lambda s: s.label):
        is_loaded = info.label in loaded

        if info.run_at_load or is_loaded:
            file_state = "enabled"
        else:
            file_state = "static"

        if f'"{info.label}" => enabled: false' in disabled_output:
            file_state = "masked"
        elif f'"{info.label}" => disabled' in disabled_output:
            file_state = "disabled"

        if state and file_state != state.value:
            continue

        rows.append(
            {
                "unit": info.label,
                "state": file_state,
                "preset": "enabled" if info.run_at_load else "-",
            }
        )

    if not rows:
        print("UNIT FILE STATE PRESET")
        print()
        print("0 unit files listed." if not _app_module.NO_LEGEND else "")
        return

    # Calculate column width based on content
    unit_width = max(len(r["unit"]) for r in rows)
    unit_width = max(unit_width, 9) + 2  # At least "UNIT FILE" + padding

    print(f"{'UNIT FILE':<{unit_width}} {'STATE':<15} PRESET")

    for row in rows:
        unit = row["unit"]
        state_str = row["state"]
        preset = row["preset"]

        print(f"{unit:<{unit_width}} {state_str:<15} {preset}")

    if not _app_module.NO_LEGEND:
        print()
        print(f"{len(rows)} unit files listed.")


@app.command("list-timers")
def list_timers(
    all_: Annotated[
        bool, typer.Option("--all", "-a", help="Show all timers including inactive")
    ] = False,
):
    """List scheduled/timer services."""
    get_all_loaded_services.cache_clear()
    services = filter_by_scope(get_all_services())
    timers = [s for s in services if s.is_timer]

    if not timers:
        print("No timer services found.")
        return

    rows = []
    for info in sorted(timers, key=lambda s: s.label):
        svc_status = get_service_status(info.label, use_cache=True)

        if svc_status and svc_status.pid:
            active = "running"
            last_run = "now"
        elif svc_status and svc_status.loaded:
            active = "waiting"
            last_run = "-"
        else:
            if not all_:
                continue
            active = "inactive"
            last_run = "-"

        rows.append(
            {
                "unit": info.label,
                "schedule": info.schedule_description or "-",
                "active": active,
                "last_run": last_run,
            }
        )

    if not rows:
        print("No timer services found.")
        return

    # Calculate column widths
    unit_width = max(max(len(r["unit"]) for r in rows), 4) + 2
    sched_width = max(max(len(r["schedule"]) for r in rows), 8) + 2
    active_width = max(max(len(r["active"]) for r in rows), 6) + 2

    header = f"{'UNIT':<{unit_width}} {'SCHEDULE':<{sched_width}} {'ACTIVE':<{active_width}} LAST RUN"
    print(header)

    for row in rows:
        print(
            f"{row['unit']:<{unit_width}} {row['schedule']:<{sched_width}} {row['active']:<{active_width}} {row['last_run']}"
        )

    if not _app_module.NO_LEGEND:
        print()
        print(f"{len(rows)} timers listed.")


@app.command("list-paths")
def list_paths(
    all_: Annotated[
        bool, typer.Option("--all", "-a", help="Show all path units including inactive")
    ] = False,
):
    """List path-triggered services (WatchPaths/QueueDirectories)."""
    get_all_loaded_services.cache_clear()
    services = filter_by_scope(get_all_services())
    path_services = [s for s in services if s.watch_paths or s.queue_directories]

    if not path_services:
        print("No path-triggered services found.")
        return

    rows = []
    for info in sorted(path_services, key=lambda s: s.label):
        svc_status = get_service_status(info.label, use_cache=True)

        if svc_status and svc_status.pid:
            active = "running"
        elif svc_status and svc_status.loaded:
            active = "waiting"
        else:
            if not all_:
                continue
            active = "inactive"

        paths = []
        if info.watch_paths:
            for p in info.watch_paths[:2]:
                paths.append((p, "watch"))
        if info.queue_directories:
            for p in info.queue_directories[:2]:
                paths.append((p, "queue"))

        if paths:
            path_str = paths[0][0]
            path_type = paths[0][1]
            if len(paths) > 1:
                path_str += f" (+{len(paths) - 1})"
        else:
            path_str = "-"
            path_type = "-"

        rows.append(
            {
                "unit": info.label,
                "path": path_str,
                "type": path_type,
                "active": active,
            }
        )

    if not rows:
        print("No path-triggered services found.")
        return

    # Calculate column widths
    unit_width = max(max(len(r["unit"]) for r in rows), 4) + 2
    path_width = max(max(len(r["path"]) for r in rows), 4) + 2
    type_width = max(max(len(r["type"]) for r in rows), 4) + 2

    header = (
        f"{'UNIT':<{unit_width}} {'PATH':<{path_width}} {'TYPE':<{type_width}} ACTIVE"
    )
    print(header)

    for row in rows:
        print(
            f"{row['unit']:<{unit_width}} {row['path']:<{path_width}} {row['type']:<{type_width}} {row['active']}"
        )

    if not _app_module.NO_LEGEND:
        print()
        print(f"{len(rows)} paths listed.")


@app.command("list-sockets")
def list_sockets(
    all_: Annotated[
        bool,
        typer.Option("--all", "-a", help="Show all socket services including inactive"),
    ] = False,
):
    """List socket-activated services."""
    get_all_loaded_services.cache_clear()
    services = filter_by_scope(get_all_services())
    socket_services = [s for s in services if s.is_socket_activated]

    if not socket_services:
        print("No socket-activated services found.")
        return

    rows = []
    for info in sorted(socket_services, key=lambda s: s.label):
        svc_status = get_service_status(info.label, use_cache=True)

        if svc_status and svc_status.pid:
            active = "running"
        elif svc_status and svc_status.loaded:
            active = "listening"
        else:
            if not all_:
                continue
            active = "inactive"

        listen_addrs = "; ".join(s.address for s in info.sockets[:2])
        if len(info.sockets) > 2:
            listen_addrs += f" (+{len(info.sockets) - 2})"

        rows.append(
            {
                "listen": listen_addrs or "-",
                "unit": info.label,
                "active": active,
            }
        )

    if not rows:
        print("No socket-activated services found.")
        return

    # Calculate column widths (like real systemctl: LISTEN UNIT ACTIVATES)
    listen_width = max(max(len(r["listen"]) for r in rows), 6) + 2
    unit_width = max(max(len(r["unit"]) for r in rows), 4) + 2

    header = f"{'LISTEN':<{listen_width}} {'UNIT':<{unit_width}} ACTIVATES"
    print(header)

    for row in rows:
        print(f"{row['listen']:<{listen_width}} {row['unit']:<{unit_width}} -")

    if not _app_module.NO_LEGEND:
        print()
        print(f"{len(rows)} sockets listed.")


@app.command("list-dependencies")
def list_dependencies(
    service: ServiceArg,
    reverse: Annotated[
        bool,
        typer.Option("--reverse", "-r", help="Show what depends on this service"),
    ] = False,
):
    """Show activation triggers and dependencies for a service."""
    info = resolve_service(service)
    if not info:
        service_not_found_error(service)
        raise typer.Exit(1)

    if reverse:
        tree = Tree(f"[cyan]{info.label}[/cyan] (reverse dependencies)")
        tree.add("[dim]Note: launchd doesn't track reverse dependencies[/dim]")

        if info.mach_services:
            mach_branch = tree.add("Provides Mach services:")
            for svc in info.mach_services:
                mach_branch.add(f"[green]{svc}[/green]")
    else:
        tree = Tree(f"[cyan]{info.label}[/cyan]")

        triggers = tree.add("Activation triggers:")
        trigger_count = 0

        if info.run_at_load:
            triggers.add("[green]● RunAtLoad[/green] - starts at boot/login")
            trigger_count += 1

        if info.keep_alive:
            triggers.add("[green]● KeepAlive[/green] - restarts if it exits")
            trigger_count += 1

        if info.is_timer:
            triggers.add(f"[green]● Timer[/green] - {info.schedule_description}")
            trigger_count += 1

        if info.sockets:
            sock_branch = triggers.add(
                "[green]● Sockets[/green] - on-demand via network"
            )
            for sock in info.sockets:
                sock_branch.add(f"{sock}")
            trigger_count += 1

        if info.watch_paths:
            watch_branch = triggers.add("[green]● WatchPaths[/green] - on file change")
            for path in info.watch_paths[:3]:
                watch_branch.add(path)
            if len(info.watch_paths) > 3:
                watch_branch.add(f"... and {len(info.watch_paths) - 3} more")
            trigger_count += 1

        if info.queue_directories:
            queue_branch = triggers.add(
                "[green]● QueueDirectories[/green] - on file arrival"
            )
            for path in info.queue_directories[:3]:
                queue_branch.add(path)
            trigger_count += 1

        if info.mach_services:
            mach_branch = triggers.add("[green]● MachServices[/green] - on IPC message")
            for svc in info.mach_services[:3]:
                mach_branch.add(svc)
            if len(info.mach_services) > 3:
                mach_branch.add(f"... and {len(info.mach_services) - 3} more")
            trigger_count += 1

        if trigger_count == 0:
            triggers.add("[dim]No automatic triggers (manual start only)[/dim]")

    console.print(tree)


@app.command("list-jobs")
def list_jobs():
    """List pending/running jobs (processes currently managed by launchd)."""
    get_all_loaded_services.cache_clear()
    loaded = get_all_loaded_services()
    registry = build_registry()

    running = []
    for label, (pid, _) in loaded.items():
        if pid:
            info = registry.get(label)
            running.append(
                {
                    "job_id": pid,
                    "unit": label,
                    "type": "running",
                    "state": "running",
                    "description": info.display_name if info else label.split(".")[-1],
                }
            )

    if not running:
        print("No jobs running.")
        return

    # Calculate column widths
    unit_width = max(max(len(j["unit"]) for j in running), 4) + 2

    print(f"{'JOB':<8} {'UNIT':<{unit_width}} {'TYPE':<10} STATE")

    for job in sorted(running, key=lambda j: j["job_id"]):
        print(
            f"{job['job_id']:<8} {job['unit']:<{unit_width}} {job['type']:<10} {job['state']}"
        )

    if not _app_module.NO_LEGEND:
        print()
        print(f"{len(running)} jobs listed.")


@app.command("is-active")
def is_active(service: ServiceArg):
    """Check if a service is active."""
    info = resolve_service(service)
    if not info:
        console.print("inactive")
        raise typer.Exit(4)

    svc_status = get_service_status(info.label)
    if svc_status and svc_status.pid:
        console.print("active")
        raise typer.Exit(0)
    else:
        console.print("inactive")
        raise typer.Exit(3)


@app.command("is-enabled")
def is_enabled(service: ServiceArg):
    """Check if a service is enabled."""
    info = resolve_service(service)
    if not info:
        console.print("not-found")
        raise typer.Exit(4)

    svc_status = get_service_status(info.label)
    if svc_status and svc_status.loaded or info.run_at_load:
        console.print("enabled")
        raise typer.Exit(0)
    else:
        console.print("disabled")
        raise typer.Exit(1)


@app.command("is-failed")
def is_failed(service: ServiceArg):
    """Check if a service is in failed state."""
    info = resolve_service(service)
    if not info:
        console.print("inactive")
        raise typer.Exit(4)

    svc_status = get_service_status(info.label)
    if (
        svc_status
        and svc_status.loaded
        and svc_status.last_exit_status
        and svc_status.last_exit_status != 0
    ):
        console.print("failed")
        raise typer.Exit(0)
    else:
        console.print("active")
        raise typer.Exit(1)


@app.command("is-system-running")
def is_system_running():
    """Check if the system is fully operational."""
    get_all_loaded_services.cache_clear()
    loaded = get_all_loaded_services()

    failed_count = 0
    running_count = 0

    for _, (pid, exit_status) in loaded.items():
        if pid:
            running_count += 1
        elif exit_status and exit_status != 0:
            failed_count += 1

    if failed_count > 0:
        console.print("degraded")
        raise typer.Exit(1)
    elif running_count > 0:
        console.print("running")
        raise typer.Exit(0)
    else:
        console.print("offline")
        raise typer.Exit(1)


@app.command()
def cat(
    service: ServiceArg,
    json_output: Annotated[
        bool, typer.Option("--json", help="Output as JSON instead of XML")
    ] = False,
):
    """Show the plist file for a service."""
    info = resolve_service(service)
    if not info:
        service_not_found_error(service)
        raise typer.Exit(1)

    print(f"# {info.plist_path}")

    with open(info.plist_path, "rb") as f:
        plist_dict = plistlib.load(f)

    if json_output:
        console.print(json.dumps(plist_to_json_serializable(plist_dict), indent=2))
    else:
        xml_bytes = plistlib.dumps(plist_dict, fmt=plistlib.FMT_XML)
        print(xml_bytes.decode("utf-8"))


def plist_to_json_serializable(obj):
    """Convert plist data types to JSON-serializable types."""
    if isinstance(obj, dict):
        return {k: plist_to_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [plist_to_json_serializable(v) for v in obj]
    elif isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")
    elif isinstance(obj, datetime):
        return obj.isoformat()
    return obj


@app.command()
def edit(service: ServiceArg):
    """Edit the plist file for a service."""
    info = resolve_service(service)
    if not info:
        service_not_found_error(service)
        raise typer.Exit(1)

    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vim"

    path_str = str(info.plist_path)
    if "/System/" in path_str:
        err_console.print(
            "[yellow]Warning:[/yellow] System plists require root to edit"
        )
        err_console.print(f"  sudo {editor} {info.plist_path}")
        raise typer.Exit(1)

    subprocess.run([editor, str(info.plist_path)])
    console.print("[dim]Run 'systemctl daemon-reload' to refresh the registry[/dim]")


@app.command("daemon-reload")
def daemon_reload():
    """Refresh the service registry and launchctl caches."""
    build_registry.cache_clear()
    clear_caches()
    build_registry()
    console.print("[green]Registry reloaded[/green]")


@app.command("get-default")
def get_default():
    """Get the name of the default target (boot mode)."""
    # macOS always boots to GUI (equivalent to graphical.target)
    # The loginwindow determines the boot mode
    print("graphical.target")
