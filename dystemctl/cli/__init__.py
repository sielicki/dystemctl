"""CLI package for dystemctl.

This package contains the CLI commands split into logical modules:
- app: Core app setup, callbacks, and shared utilities
- control: Service control commands (start, stop, restart, etc.)
- info: Service information commands (status, show, list-*, is-*, cat, edit)
- journal: Journal/logging commands (logs, disk-usage, vacuum-*, list-boots)
- system: System commands (poweroff, reboot, environment)
- units: Unit file management (link, import, export, verify)
- run: Transient services and analysis (run, analyze, cancel)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Re-export commonly used functions for backward compatibility with tests
from ..launchctl import (  # noqa: F401
    detect_domain,
    get_all_loaded_services,
    get_process_info,
    get_service_status,
    launchctl_disable,
    launchctl_enable,
    launchctl_start,
    launchctl_stop,
)
from ..logs import query_os_log, tail_log_file  # noqa: F401
from ..registry import (  # noqa: F401
    build_registry,
    find_similar_services,
    get_all_services,
    resolve_service,
)

# Import app module and expose commonly needed attributes
from . import app as _app_module
from . import (
    control,  # noqa: F401
    info,  # noqa: F401
    journal,  # noqa: F401
    run,  # noqa: F401
    system,  # noqa: F401
    units,  # noqa: F401
)
from .app import cli_app as app  # noqa: F401
from .app import console, err_console, filter_by_scope  # noqa: F401

# Re-export mutable globals so tests can modify them
# These are the actual module-level variables from app.py
QUIET_MODE = _app_module.QUIET_MODE
NO_LEGEND = _app_module.NO_LEGEND
SCOPE = _app_module.SCOPE

# Command sets for mode filtering
JOURNALCTL_COMMANDS = {
    "logs",
    "disk-usage",
    "vacuum-time",
    "vacuum-size",
    "list-boots",
}

SYSTEMCTL_COMMANDS = {
    "start",
    "stop",
    "restart",
    "reload",
    "kill",
    "try-restart",
    "reload-or-restart",
    "try-reload-or-restart",
    "reenable",
    "whoami",
    "enable",
    "disable",
    "mask",
    "unmask",
    "reset-failed",
    "clean",
    "status",
    "show",
    "list-units",
    "list-unit-files",
    "list-timers",
    "list-paths",
    "list-sockets",
    "list-dependencies",
    "list-jobs",
    "is-active",
    "is-enabled",
    "is-failed",
    "is-system-running",
    "cat",
    "edit",
    "daemon-reload",
    "get-default",
    "show-environment",
    "set-environment",
    "unset-environment",
    "poweroff",
    "reboot",
    "suspend",
    "hibernate",
    "hybrid-sleep",
    "halt",
    "link",
    "revert",
    "import",
    "export",
    "resolve",
    "setup",
    "escape",
    "verify",
    "alias",
    "run",
    "analyze",
    "cancel",
}


def get_command_name(cmd_info) -> str:
    """Get the effective command name from a CommandInfo object."""
    if cmd_info.name:
        return cmd_info.name
    if cmd_info.callback:
        return cmd_info.callback.__name__.replace("_", "-")
    return ""


def hide_commands_for_mode(mode: str) -> None:
    """Hide commands that don't belong to the current invocation mode."""
    if mode == "journalctl":
        hidden_commands = SYSTEMCTL_COMMANDS
    elif mode == "systemctl":
        hidden_commands = JOURNALCTL_COMMANDS
    else:
        return

    for cmd_info in app.registered_commands:
        cmd_name = get_command_name(cmd_info)
        if cmd_name in hidden_commands:
            cmd_info.hidden = True


def main():
    invoked_as = Path(sys.argv[0]).name

    if invoked_as == "journalctl":
        hide_commands_for_mode("journalctl")

        if len(sys.argv) > 1 and sys.argv[1] not in (
            "--help",
            "-h",
            "--install-completion",
            "--show-completion",
            "-q",
            "--quiet",
            "--user",
            "--system",
            "--no-legend",
            "--version",
        ):
            cmd = sys.argv[1]
            if cmd in SYSTEMCTL_COMMANDS:
                err_console.print(f"[red]Unknown command:[/red] {cmd}")
                err_console.print(
                    f"[dim]'{cmd}' is a systemctl command. Use systemctl instead.[/dim]"
                )
                raise SystemExit(1)

        if len(sys.argv) == 1:
            sys.argv.append("logs")
        elif (
            sys.argv[1]
            not in (
                "--help",
                "-h",
                "--install-completion",
                "--show-completion",
                "--version",
            )
            and sys.argv[1] not in JOURNALCTL_COMMANDS
        ):
            sys.argv.insert(1, "logs")

        app(prog_name="journalctl")

    elif invoked_as == "systemctl":
        hide_commands_for_mode("systemctl")

        if len(sys.argv) > 1 and sys.argv[1] not in (
            "--help",
            "-h",
            "--install-completion",
            "--show-completion",
            "-q",
            "--quiet",
            "--user",
            "--system",
            "--no-legend",
            "--version",
        ):
            cmd = sys.argv[1]
            if cmd in JOURNALCTL_COMMANDS:
                err_console.print(f"[red]Unknown command:[/red] {cmd}")
                err_console.print(
                    f"[dim]'{cmd}' is a journalctl command. Use journalctl instead.[/dim]"
                )
                raise SystemExit(1)

        app(prog_name="systemctl")
    else:
        app()


__all__ = ["app", "console", "err_console", "main"]
