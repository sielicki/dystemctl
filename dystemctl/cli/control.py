"""Service control commands: start, stop, restart, reload, kill, enable, disable, etc."""

from __future__ import annotations

import os
import signal as sig_module
import subprocess
from enum import Enum
from typing import Annotated

import typer

from ..launchctl import (
    detect_domain,
    get_all_loaded_services,
    get_service_status,
    launchctl_disable,
    launchctl_enable,
    launchctl_start,
    launchctl_stop,
)
from ..registry import build_registry, resolve_service
from .app import (
    cli_app as app,
)
from .app import (
    console,
    err_console,
    service_completion,
    service_not_found_error,
)


@app.command()
def start(
    services: Annotated[list[str], typer.Argument(autocompletion=service_completion)],
):
    """Start service(s)."""
    failed = False
    for service in services:
        info = resolve_service(service)
        if not info:
            service_not_found_error(service)
            failed = True
            continue

        if launchctl_start(info.label):
            console.print(f"[green]Started[/green] {info.label}")
        else:
            err_console.print(f"[red]Failed to start[/red] {info.label}")
            failed = True

    if failed:
        raise typer.Exit(1)


@app.command()
def stop(
    services: Annotated[list[str], typer.Argument(autocompletion=service_completion)],
):
    """Stop service(s)."""
    failed = False
    for service in services:
        info = resolve_service(service)
        if not info:
            service_not_found_error(service)
            failed = True
            continue

        if launchctl_stop(info.label):
            console.print(f"[green]Stopped[/green] {info.label}")
        else:
            err_console.print(f"[red]Failed to stop[/red] {info.label}")
            failed = True

    if failed:
        raise typer.Exit(1)


@app.command()
def restart(
    services: Annotated[list[str], typer.Argument(autocompletion=service_completion)],
):
    """Restart service(s)."""
    failed = False
    for service in services:
        info = resolve_service(service)
        if not info:
            service_not_found_error(service)
            failed = True
            continue

        launchctl_stop(info.label)
        if launchctl_start(info.label):
            console.print(f"[green]Restarted[/green] {info.label}")
        else:
            err_console.print(f"[red]Failed to restart[/red] {info.label}")
            failed = True

    if failed:
        raise typer.Exit(1)


@app.command()
def reload(
    services: Annotated[list[str], typer.Argument(autocompletion=service_completion)],
):
    """Reload service(s) by sending SIGHUP."""
    failed = False
    for service in services:
        info = resolve_service(service)
        if not info:
            service_not_found_error(service)
            failed = True
            continue

        status = get_service_status(info.label)
        if not status or not status.pid:
            err_console.print(f"[yellow]Not running:[/yellow] {info.label}")
            failed = True
            continue

        try:
            os.kill(status.pid, sig_module.SIGHUP)
            console.print(
                f"[green]Reloaded[/green] {info.label} (sent SIGHUP to PID {status.pid})"
            )
        except ProcessLookupError:
            err_console.print(
                f"[red]Process not found:[/red] {info.label} (PID {status.pid})"
            )
            failed = True
        except PermissionError:
            err_console.print(
                f"[red]Permission denied:[/red] {info.label} (PID {status.pid})"
            )
            failed = True

    if failed:
        raise typer.Exit(1)


class Signal(str, Enum):
    SIGTERM = "SIGTERM"
    SIGKILL = "SIGKILL"
    SIGHUP = "SIGHUP"
    SIGINT = "SIGINT"
    SIGUSR1 = "SIGUSR1"
    SIGUSR2 = "SIGUSR2"


@app.command()
def kill(
    services: Annotated[list[str], typer.Argument(autocompletion=service_completion)],
    signal_: Annotated[
        Signal, typer.Option("-s", "--signal", help="Signal to send")
    ] = Signal.SIGTERM,
):
    """Send a signal to service process(es)."""
    failed = False

    sig_map = {
        Signal.SIGTERM: sig_module.SIGTERM,
        Signal.SIGKILL: sig_module.SIGKILL,
        Signal.SIGHUP: sig_module.SIGHUP,
        Signal.SIGINT: sig_module.SIGINT,
        Signal.SIGUSR1: sig_module.SIGUSR1,
        Signal.SIGUSR2: sig_module.SIGUSR2,
    }
    sig = sig_map[signal_]

    for service in services:
        info = resolve_service(service)
        if not info:
            service_not_found_error(service)
            failed = True
            continue

        status = get_service_status(info.label)
        if not status or not status.pid:
            err_console.print(f"[yellow]Not running:[/yellow] {info.label}")
            failed = True
            continue

        try:
            os.kill(status.pid, sig)
            console.print(
                f"[green]Sent {signal_.value}[/green] to {info.label} (PID {status.pid})"
            )
        except ProcessLookupError:
            err_console.print(f"[red]Process not found:[/red] {info.label}")
            failed = True
        except PermissionError:
            err_console.print(f"[red]Permission denied:[/red] {info.label}")
            failed = True

    if failed:
        raise typer.Exit(1)


@app.command("try-restart")
def try_restart(
    services: Annotated[list[str], typer.Argument(autocompletion=service_completion)],
):
    """Restart service(s) if they are running."""
    failed = False
    for service in services:
        info = resolve_service(service)
        if not info:
            service_not_found_error(service)
            failed = True
            continue

        status = get_service_status(info.label)
        if not status or not status.pid:
            console.print(f"[dim]Skipped (not running):[/dim] {info.label}")
            continue

        launchctl_stop(info.label)
        if launchctl_start(info.label):
            console.print(f"[green]Restarted[/green] {info.label}")
        else:
            err_console.print(f"[red]Failed to restart[/red] {info.label}")
            failed = True

    if failed:
        raise typer.Exit(1)


@app.command("reload-or-restart")
def reload_or_restart(
    services: Annotated[list[str], typer.Argument(autocompletion=service_completion)],
):
    """Reload service(s) if supported, otherwise restart."""
    failed = False
    for service in services:
        info = resolve_service(service)
        if not info:
            service_not_found_error(service)
            failed = True
            continue

        status = get_service_status(info.label)
        if not status or not status.pid:
            if launchctl_start(info.label):
                console.print(f"[green]Started[/green] {info.label}")
            else:
                err_console.print(f"[red]Failed to start[/red] {info.label}")
                failed = True
            continue

        try:
            os.kill(status.pid, sig_module.SIGHUP)
            console.print(f"[green]Reloaded[/green] {info.label}")
        except (ProcessLookupError, PermissionError):
            launchctl_stop(info.label)
            if launchctl_start(info.label):
                console.print(f"[green]Restarted[/green] {info.label}")
            else:
                err_console.print(f"[red]Failed to restart[/red] {info.label}")
                failed = True

    if failed:
        raise typer.Exit(1)


@app.command("try-reload-or-restart")
def try_reload_or_restart(
    services: Annotated[list[str], typer.Argument(autocompletion=service_completion)],
):
    """If active, reload or restart service(s)."""
    failed = False
    for service in services:
        info = resolve_service(service)
        if not info:
            service_not_found_error(service)
            failed = True
            continue

        status = get_service_status(info.label)
        if not status or not status.pid:
            console.print(f"[dim]Skipped (not running):[/dim] {info.label}")
            continue

        try:
            os.kill(status.pid, sig_module.SIGHUP)
            console.print(f"[green]Reloaded[/green] {info.label}")
        except (ProcessLookupError, PermissionError):
            launchctl_stop(info.label)
            if launchctl_start(info.label):
                console.print(f"[green]Restarted[/green] {info.label}")
            else:
                err_console.print(f"[red]Failed to restart[/red] {info.label}")
                failed = True

    if failed:
        raise typer.Exit(1)


@app.command()
def reenable(
    services: Annotated[list[str], typer.Argument(autocompletion=service_completion)],
    now: Annotated[
        bool, typer.Option("--now", help="Also restart the service")
    ] = False,
):
    """Reenable service(s) (disable then enable)."""
    failed = False
    for service in services:
        info = resolve_service(service)
        if not info:
            service_not_found_error(service)
            failed = True
            continue

        launchctl_disable(info.label, info.plist_path)

        if launchctl_enable(info.plist_path):
            console.print(f"[green]Reenabled[/green] {info.label}")
            if now:
                launchctl_stop(info.label)
                if launchctl_start(info.label):
                    console.print(f"[green]Restarted[/green] {info.label}")
                else:
                    err_console.print(f"[red]Failed to restart[/red] {info.label}")
                    failed = True
        else:
            err_console.print(f"[red]Failed to reenable[/red] {info.label}")
            failed = True

    if failed:
        raise typer.Exit(1)


@app.command()
def whoami(
    pids: Annotated[list[int] | None, typer.Argument(help="PIDs to look up")] = None,
):
    """Show which service a PID belongs to."""
    if not pids:
        pids = [os.getpid()]

    get_all_loaded_services.cache_clear()
    loaded = get_all_loaded_services()
    registry = build_registry()

    for pid in pids:
        found = False
        for label, (service_pid, _) in loaded.items():
            if service_pid == pid:
                info = registry.get(label)
                console.print(
                    f"{pid}: {label}" + (f" ({info.display_name})" if info else "")
                )
                found = True
                break

        if not found:
            try:
                result = subprocess.run(
                    ["ps", "-o", "ppid=", "-p", str(pid)],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0 and result.stdout.strip():
                    ppid = int(result.stdout.strip())
                    for label, (service_pid, _) in loaded.items():
                        if service_pid == ppid:
                            console.print(f"{pid}: child of {label}")
                            found = True
                            break
            except (ValueError, subprocess.SubprocessError):
                pass

            if not found:
                console.print(f"{pid}: not part of any tracked service")


@app.command()
def enable(
    services: Annotated[list[str], typer.Argument(autocompletion=service_completion)],
    now: Annotated[bool, typer.Option("--now", help="Also start the service")] = False,
):
    """Enable service(s) to start at boot/login."""
    failed = False
    for service in services:
        info = resolve_service(service)
        if not info:
            service_not_found_error(service)
            failed = True
            continue

        if launchctl_enable(info.plist_path):
            console.print(f"[green]Enabled[/green] {info.label}")
            if now:
                if launchctl_start(info.label):
                    console.print(f"[green]Started[/green] {info.label}")
                else:
                    err_console.print(f"[red]Failed to start[/red] {info.label}")
                    failed = True
        else:
            err_console.print(f"[red]Failed to enable[/red] {info.label}")
            failed = True

    if failed:
        raise typer.Exit(1)


@app.command()
def disable(
    services: Annotated[list[str], typer.Argument(autocompletion=service_completion)],
    now: Annotated[bool, typer.Option("--now", help="Also stop the service")] = False,
):
    """Disable service(s) from starting at boot/login."""
    failed = False
    for service in services:
        info = resolve_service(service)
        if not info:
            service_not_found_error(service)
            failed = True
            continue

        if now:
            launchctl_stop(info.label)
            console.print(f"[green]Stopped[/green] {info.label}")

        if launchctl_disable(info.label, info.plist_path):
            console.print(f"[green]Disabled[/green] {info.label}")
        else:
            err_console.print(f"[red]Failed to disable[/red] {info.label}")
            failed = True

    if failed:
        raise typer.Exit(1)


@app.command()
def mask(
    services: Annotated[list[str], typer.Argument(autocompletion=service_completion)],
    now: Annotated[bool, typer.Option("--now", help="Also stop the service")] = False,
):
    """Mask service(s) to prevent starting."""
    failed = False
    uid = os.getuid()

    for service in services:
        info = resolve_service(service)
        if not info:
            service_not_found_error(service)
            failed = True
            continue

        if now:
            launchctl_stop(info.label)
            console.print(f"[green]Stopped[/green] {info.label}")

        launchctl_disable(info.label, info.plist_path)

        result = subprocess.run(
            ["launchctl", "disable", f"gui/{uid}/{info.label}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            subprocess.run(
                ["launchctl", "disable", f"user/{uid}/{info.label}"],
                capture_output=True,
                text=True,
            )

        console.print(f"[green]Masked[/green] {info.label}")

    if failed:
        raise typer.Exit(1)


@app.command()
def unmask(
    services: Annotated[list[str], typer.Argument(autocompletion=service_completion)],
):
    """Unmask service(s) to allow starting."""
    failed = False
    uid = os.getuid()

    for service in services:
        info = resolve_service(service)
        if not info:
            service_not_found_error(service)
            failed = True
            continue

        result = subprocess.run(
            ["launchctl", "enable", f"gui/{uid}/{info.label}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            subprocess.run(
                ["launchctl", "enable", f"user/{uid}/{info.label}"],
                capture_output=True,
                text=True,
            )

        console.print(f"[green]Unmasked[/green] {info.label}")

    if failed:
        raise typer.Exit(1)


@app.command("reset-failed")
def reset_failed(
    services: Annotated[
        list[str] | None, typer.Argument(autocompletion=service_completion)
    ] = None,
):
    """Reset failed state of service(s). With no args, resets all."""
    if services:
        for service in services:
            info = resolve_service(service)
            if not info:
                service_not_found_error(service)
                continue

            domain = detect_domain(info.label)
            if domain:
                subprocess.run(
                    ["launchctl", "kickstart", "-k", f"{domain.path()}/{info.label}"],
                    capture_output=True,
                )
            console.print(f"[green]Reset[/green] {info.label}")
    else:
        get_all_loaded_services.cache_clear()
        loaded = get_all_loaded_services()
        reset_count = 0
        for label, (pid, exit_status) in loaded.items():
            if pid is None and exit_status and exit_status != 0:
                domain = detect_domain(label)
                if domain:
                    subprocess.run(
                        ["launchctl", "kickstart", "-k", f"{domain.path()}/{label}"],
                        capture_output=True,
                    )
                    reset_count += 1
        console.print(f"[green]Reset {reset_count} failed service(s)[/green]")
