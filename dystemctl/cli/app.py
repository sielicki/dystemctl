"""Shared CLI application and utilities."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console

from ..registry import complete_service, find_similar_services

console = Console()
err_console = Console(stderr=True)

QUIET_MODE = False
NO_LEGEND = False
SCOPE: str | None = None
VERSION = "0.1.0"


def version_callback(value: bool):
    if value:
        print(f"dystemctl {VERSION}")
        print("systemd emulation for Darwin (launchd)")
        raise typer.Exit(0)


def quiet_callback(value: bool):
    global QUIET_MODE
    if value:
        QUIET_MODE = True
        console.quiet = True


def no_legend_callback(value: bool):
    global NO_LEGEND
    if value:
        NO_LEGEND = True


def user_callback(value: bool):
    global SCOPE
    if value:
        SCOPE = "user"


def system_callback(value: bool):
    global SCOPE
    if value:
        SCOPE = "system"


def is_user_service(info) -> bool:
    path_str = str(info.plist_path)
    return "LaunchAgents" in path_str


def is_system_service(info) -> bool:
    path_str = str(info.plist_path)
    return "LaunchDaemons" in path_str


def filter_by_scope(services):
    if SCOPE == "user":
        return [s for s in services if is_user_service(s)]
    elif SCOPE == "system":
        return [s for s in services if is_system_service(s)]
    return services


cli_app = typer.Typer(
    name="systemctl",
    help="systemd emulation for Darwin",
    no_args_is_help=True,
    add_completion=True,
    rich_markup_mode=None,
    pretty_exceptions_enable=False,
)


@cli_app.callback()
def main_callback(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show version and exit",
            callback=version_callback,
            is_eager=True,
        ),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option(
            "-q",
            "--quiet",
            help="Suppress output",
            callback=quiet_callback,
            is_eager=True,
        ),
    ] = False,
    user: Annotated[
        bool,
        typer.Option(
            "--user",
            help="Only user services (LaunchAgents)",
            callback=user_callback,
            is_eager=True,
        ),
    ] = False,
    system: Annotated[
        bool,
        typer.Option(
            "--system",
            help="Only system services (LaunchDaemons)",
            callback=system_callback,
            is_eager=True,
        ),
    ] = False,
    no_legend: Annotated[
        bool,
        typer.Option(
            "--no-legend",
            help="Suppress footer with unit count",
            callback=no_legend_callback,
            is_eager=True,
        ),
    ] = False,
    no_pager: Annotated[
        bool,
        typer.Option(
            "--no-pager",
            help="Do not pipe output into a pager",
        ),
    ] = False,
):
    pass


def service_completion(incomplete: str) -> list[str]:
    return complete_service(incomplete)


ServiceArg = Annotated[str, typer.Argument(autocompletion=service_completion)]
OptionalServiceArg = Annotated[
    str | None, typer.Argument(autocompletion=service_completion)
]


def service_not_found_error(query: str) -> None:
    """Print a helpful error message when a service is not found."""
    err_console.print(f"[red]Unit {query} not found.[/red]")
    similar = find_similar_services(query)
    if similar:
        err_console.print("[dim]Did you mean:[/dim]")
        for s in similar[:5]:
            err_console.print(f"  [cyan]{s}[/cyan]")
