"""Transient services and analysis: run, analyze, cancel."""

from __future__ import annotations

import os
import plistlib
import re
import shutil
import signal as sig_module
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from ..launchctl import get_all_loaded_services, get_process_info
from ..paths import dystemctl_log_dir, user_launch_agents
from ..registry import build_registry
from ..utils import format_elapsed
from .app import cli_app as app
from .app import console, err_console
from .info import list_jobs


@app.command()
def run(
    command: Annotated[list[str], typer.Argument(help="Command and arguments to run")],
    unit: Annotated[
        str | None,
        typer.Option("-u", "--unit", help="Unit name for the transient service"),
    ] = None,
    description: Annotated[
        str | None,
        typer.Option(
            "-d", "--description", help="Description for the transient service"
        ),
    ] = None,
    remain_after_exit: Annotated[
        bool,
        typer.Option(
            "--remain-after-exit", help="Keep service active after process exits"
        ),
    ] = False,
    working_directory: Annotated[
        Path | None,
        typer.Option(
            "-w", "--working-directory", help="Working directory for the command"
        ),
    ] = None,
    env: Annotated[
        list[str] | None,
        typer.Option("-E", "--env", help="Environment variables (VAR=VALUE)"),
    ] = None,
    scope: Annotated[
        bool, typer.Option("--scope", help="Run as scope unit (don't create plist)")
    ] = False,
):
    """Run a command as a transient service.

    This is similar to systemd-run. The command runs under launchd control.
    With --scope, runs the command directly without creating a plist.
    """
    if scope:
        subprocess.run(
            command,
            cwd=working_directory,
            env={**os.environ, **(dict(e.split("=", 1) for e in env) if env else {})},
        )
        return

    if not unit:
        unit = f"run-{uuid.uuid4().hex[:8]}"

    # Resolve command to absolute path if needed
    resolved_command = list(command)
    if resolved_command and not Path(resolved_command[0]).is_absolute():
        resolved = shutil.which(resolved_command[0])
        if resolved:
            resolved_command[0] = resolved
        else:
            err_console.print(f"[red]Command not found:[/red] {resolved_command[0]}")
            raise typer.Exit(1)

    # Default to current working directory
    if working_directory is None:
        working_directory = Path.cwd()

    label = f"org.dystemctl.transient.{unit}"
    plist_dict = {
        "Label": label,
        "ProgramArguments": resolved_command,
        "RunAtLoad": True,
        "KeepAlive": False,
        "AbandonProcessGroup": True,
        "WorkingDirectory": str(working_directory),
    }

    if env:
        env_dict = {}
        for e in env:
            if "=" in e:
                k, v = e.split("=", 1)
                env_dict[k] = v
        if env_dict:
            plist_dict["EnvironmentVariables"] = env_dict

    log_dir = dystemctl_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    plist_dict["StandardOutPath"] = str(log_dir / f"{unit}.log")
    plist_dict["StandardErrorPath"] = str(log_dir / f"{unit}.log")

    launch_agents = user_launch_agents()
    launch_agents.mkdir(parents=True, exist_ok=True)
    plist_path = launch_agents / f"{label}.plist"

    with open(plist_path, "wb") as f:
        plistlib.dump(plist_dict, f)

    result = subprocess.run(
        ["launchctl", "load", str(plist_path)],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        console.print(f"[green]Running as unit:[/green] {label}")
        console.print(f"[dim]Logs:[/dim] {log_dir / f'{unit}.log'}")
        if not remain_after_exit:
            console.print(f"[dim]To stop:[/dim] systemctl stop {label}")
    else:
        err_console.print(
            f"[red]Failed to start transient service:[/red] {result.stderr}"
        )
        plist_path.unlink(missing_ok=True)
        raise typer.Exit(1)


@app.command()
def analyze(
    what: Annotated[
        str | None,
        typer.Argument(help="What to analyze: time, blame, critical-chain"),
    ] = "time",
):
    """Analyze system boot-up performance (like systemd-analyze).

    Subcommands:
        time            - Show how long the boot took
        blame           - Show services by startup time
        critical-chain  - Show critical chain of services
    """
    result = subprocess.run(
        ["sysctl", "-n", "kern.boottime"], capture_output=True, text=True
    )
    if result.returncode != 0:
        err_console.print("[red]Could not determine boot time[/red]")
        raise typer.Exit(1)

    match = re.search(r"sec = (\d+)", result.stdout)
    if not match:
        err_console.print("[red]Could not parse boot time[/red]")
        raise typer.Exit(1)

    boot_time = datetime.fromtimestamp(int(match.group(1)))
    uptime = datetime.now() - boot_time

    if what == "time":
        console.print(f"[bold]Startup finished in {format_elapsed(uptime)}[/bold]")
        console.print()

        log_result = subprocess.run(
            [
                "log",
                "show",
                "--predicate",
                'process == "kernel"',
                "--start",
                boot_time.strftime("%Y-%m-%d %H:%M:%S"),
                "--last",
                "5m",
                "--style",
                "compact",
            ],
            capture_output=True,
            text=True,
        )
        if log_result.returncode == 0 and log_result.stdout:
            lines = log_result.stdout.strip().split("\n")
            first_line = lines[0] if lines else ""
            if first_line:
                console.print("[dim]First kernel log:[/dim]")
                console.print(f"  {first_line[:100]}")

    elif what == "blame":
        console.print("[bold]Services by time since boot:[/bold]")
        console.print()

        get_all_loaded_services.cache_clear()
        loaded = get_all_loaded_services()
        registry = build_registry()

        rows = []
        for label, (pid, _) in loaded.items():
            if pid:
                info = registry.get(label)
                proc_info = get_process_info(pid)
                if proc_info and proc_info.elapsed:
                    rows.append(
                        (
                            proc_info.elapsed,
                            label,
                            info.display_name if info else label.split(".")[-1],
                        )
                    )

        rows.sort(key=lambda x: -x[0])

        for elapsed, label, _ in rows[:20]:
            console.print(f"  {format_elapsed(elapsed):>10}  {label}")

    elif what == "critical-chain":
        console.print("[bold]Critical chain (boot sequence)[/bold]")
        console.print()
        console.print(f"multi-user.target reached after {format_elapsed(uptime)}")
        console.print()
        console.print(
            "[dim]Note: macOS doesn't have explicit service dependencies like systemd.[/dim]"
        )
        console.print(
            "[dim]Services are activated on-demand or at boot via RunAtLoad.[/dim]"
        )

    else:
        err_console.print(f"[red]Unknown analyze subcommand:[/red] {what}")
        err_console.print("Valid options: time, blame, critical-chain")
        raise typer.Exit(1)


@app.command()
def cancel(
    jobs: Annotated[list[int] | None, typer.Argument(help="Job IDs to cancel")] = None,
):
    """Cancel pending jobs (running processes).

    Without arguments, lists all jobs that could be cancelled.
    With job IDs, kills those processes.
    """
    if not jobs:
        list_jobs()
        return

    failed = False
    for job_id in jobs:
        try:
            os.kill(job_id, sig_module.SIGTERM)
            console.print(f"[green]Cancelled job {job_id}[/green]")
        except ProcessLookupError:
            err_console.print(f"[yellow]Job {job_id} not found[/yellow]")
        except PermissionError:
            err_console.print(f"[red]Permission denied for job {job_id}[/red]")
            failed = True

    if failed:
        raise typer.Exit(1)
