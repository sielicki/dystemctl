"""System commands: environment, power management."""

from __future__ import annotations

import os
import subprocess
from typing import Annotated

import typer

from .app import cli_app as app
from .app import console, err_console


@app.command("show-environment")
def show_environment():
    """Show launchd environment variables."""
    common_vars = ["PATH", "HOME", "USER", "SHELL", "LANG", "TERM", "TMPDIR"]

    for var in common_vars:
        result = subprocess.run(
            ["launchctl", "getenv", var], capture_output=True, text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            console.print(f"{var}={result.stdout.strip()}")
        elif var in os.environ:
            console.print(
                f"[dim]{var}={os.environ[var]}[/dim]  # (from shell, not launchd)"
            )


@app.command("set-environment")
def set_environment(
    assignments: Annotated[list[str], typer.Argument(help="VAR=VALUE assignments")],
):
    """Set launchd environment variables."""
    for assignment in assignments:
        if "=" not in assignment:
            err_console.print(
                f"[red]Invalid format:[/red] {assignment} (expected VAR=VALUE)"
            )
            continue

        var, _, value = assignment.partition("=")
        result = subprocess.run(
            ["launchctl", "setenv", var, value], capture_output=True, text=True
        )

        if result.returncode == 0:
            console.print(f"[green]Set[/green] {var}={value}")
        else:
            err_console.print(f"[red]Failed to set[/red] {var}: {result.stderr}")


@app.command("unset-environment")
def unset_environment(
    variables: Annotated[list[str], typer.Argument(help="Variable names to unset")],
):
    """Unset launchd environment variables."""
    for var in variables:
        result = subprocess.run(
            ["launchctl", "unsetenv", var], capture_output=True, text=True
        )

        if result.returncode == 0:
            console.print(f"[green]Unset[/green] {var}")
        else:
            err_console.print(f"[red]Failed to unset[/red] {var}: {result.stderr}")


# --- Power Management ---


@app.command()
def poweroff(
    force: Annotated[
        bool, typer.Option("-f", "--force", help="Force immediate shutdown")
    ] = False,
):
    """Power off the system."""
    if force:
        result = subprocess.run(
            ["sudo", "shutdown", "-h", "now"], capture_output=True, text=True
        )
    else:
        console.print("[yellow]System will power off...[/yellow]")
        result = subprocess.run(
            ["osascript", "-e", 'tell app "System Events" to shut down'],
            capture_output=True,
            text=True,
        )

    if result.returncode != 0:
        err_console.print(
            f"[red]Failed:[/red] {result.stderr or 'requires privileges'}"
        )
        raise typer.Exit(1)


@app.command()
def reboot(
    force: Annotated[
        bool, typer.Option("-f", "--force", help="Force immediate reboot")
    ] = False,
):
    """Reboot the system."""
    if force:
        result = subprocess.run(
            ["sudo", "shutdown", "-r", "now"], capture_output=True, text=True
        )
    else:
        console.print("[yellow]System will reboot...[/yellow]")
        result = subprocess.run(
            ["osascript", "-e", 'tell app "System Events" to restart'],
            capture_output=True,
            text=True,
        )

    if result.returncode != 0:
        err_console.print(
            f"[red]Failed:[/red] {result.stderr or 'requires privileges'}"
        )
        raise typer.Exit(1)


@app.command()
def suspend():
    """Suspend the system (sleep)."""
    result = subprocess.run(["pmset", "sleepnow"], capture_output=True, text=True)
    if result.returncode != 0:
        err_console.print(f"[red]Failed to suspend:[/red] {result.stderr}")
        raise typer.Exit(1)


@app.command()
def hibernate():
    """Hibernate the system (deep sleep with state saved to disk)."""
    result = subprocess.run(["pmset", "-g"], capture_output=True, text=True)
    if result.returncode == 0:
        console.print("[dim]Setting hibernate mode and sleeping...[/dim]")

    subprocess.run(["sudo", "pmset", "hibernatemode", "25"], capture_output=True)
    result = subprocess.run(["pmset", "sleepnow"], capture_output=True, text=True)
    if result.returncode != 0:
        err_console.print(f"[red]Failed to hibernate:[/red] {result.stderr}")
        raise typer.Exit(1)


@app.command("hybrid-sleep")
def hybrid_sleep():
    """Hybrid sleep (suspend + hibernate)."""
    hibernate()


@app.command()
def halt(
    force: Annotated[
        bool, typer.Option("-f", "--force", help="Force immediate halt")
    ] = False,
):
    """Halt the system (alias for poweroff)."""
    poweroff(force=force)


# --- journalctl-style commands ---
