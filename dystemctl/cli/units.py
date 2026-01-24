"""Unit file management: link, revert, import, export, resolve, verify, alias."""

from __future__ import annotations

import os
import plistlib
import sys
from pathlib import Path
from typing import Annotated

import typer

from ..launchctl import launchctl_disable, launchctl_enable, launchctl_stop
from ..paths import (
    SYSTEM_LAUNCH_DAEMONS,
    dystemctl_config_dir,
    dystemctl_log_dir,
    user_launch_agents,
)
from ..registry import build_registry, resolve_service
from ..systemd import parse_systemd_unit, translate_plist_to_unit, translate_to_plist
from .app import (
    ServiceArg,
    console,
    err_console,
    service_completion,
    service_not_found_error,
)
from .app import (
    cli_app as app,
)


@app.command()
def link(
    files: Annotated[list[Path], typer.Argument(help="Unit files to link")],
    user: Annotated[
        bool, typer.Option("--user", help="Install for current user (LaunchAgents)")
    ] = True,
):
    """Link unit file(s) into the search path.

    Creates a symbolic link from a unit file to ~/Library/LaunchAgents
    or /Library/LaunchDaemons (with --system).
    """
    for file_path in files:
        if not file_path.exists():
            err_console.print(f"[red]File not found:[/red] {file_path}")
            continue

        if not file_path.is_absolute():
            file_path = file_path.resolve()

        if file_path.suffix == ".service":
            unit = parse_systemd_unit(file_path)
            plist_dict, warnings = translate_to_plist(unit)
            label = plist_dict["Label"]

            if user:
                target_dir = user_launch_agents()
            else:
                target_dir = SYSTEM_LAUNCH_DAEMONS

            target_path = target_dir / f"{label}.plist"
            target_dir.mkdir(parents=True, exist_ok=True)

            with open(target_path, "wb") as f:
                plistlib.dump(plist_dict, f)

            if warnings:
                console.print(f"[yellow]Linked with warnings:[/yellow] {file_path}")
                for w in warnings[:3]:
                    console.print(f"  {w}")
            else:
                console.print(f"[green]Linked:[/green] {file_path} → {target_path}")

        elif file_path.suffix == ".plist":
            if user:
                target_dir = user_launch_agents()
            else:
                target_dir = SYSTEM_LAUNCH_DAEMONS

            target_path = target_dir / file_path.name
            target_dir.mkdir(parents=True, exist_ok=True)

            if target_path.exists() or target_path.is_symlink():
                target_path.unlink()

            target_path.symlink_to(file_path)
            console.print(f"[green]Linked:[/green] {file_path} → {target_path}")

        else:
            err_console.print(
                f"[yellow]Unknown file type:[/yellow] {file_path} (expected .service or .plist)"
            )

    build_registry.cache_clear()


@app.command()
def revert(
    services: Annotated[list[str], typer.Argument(autocompletion=service_completion)],
):
    """Revert to the vendor version of unit files.

    For dystemctl, this removes units that were imported via 'import' or 'link'.
    Only removes units in ~/Library/LaunchAgents with dystemctl label prefix.
    """
    for service in services:
        info = resolve_service(service)
        if not info:
            service_not_found_error(service)
            continue

        if "dystemctl" not in info.label and "transient" not in info.label:
            err_console.print(
                f"[yellow]Not a dystemctl-managed unit:[/yellow] {info.label}"
            )
            console.print(f"  Plist at: {info.plist_path}")
            console.print("  Use 'edit' or 'disable' to manage this unit instead")
            continue

        launchctl_stop(info.label)
        launchctl_disable(info.label, info.plist_path)

        if info.plist_path.exists():
            info.plist_path.unlink()
            console.print(f"[green]Reverted:[/green] {info.label}")
            console.print(f"  Removed: {info.plist_path}")
        else:
            console.print(f"[yellow]Already removed:[/yellow] {info.label}")

    build_registry.cache_clear()


@app.command("import")
def import_unit(
    unit_file: Annotated[Path, typer.Argument(help="Path to .service file")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", "-n", help="Show what would be done")
    ] = False,
    enable_: Annotated[
        bool, typer.Option("--enable", "-e", help="Enable after import")
    ] = False,
):
    """Import a systemd unit file and convert to launchd plist."""
    if not unit_file.exists():
        err_console.print(f"[red]File not found:[/red] {unit_file}")
        raise typer.Exit(1)

    if not unit_file.name.endswith(".service"):
        err_console.print("[yellow]Warning:[/yellow] Expected .service file")

    unit = parse_systemd_unit(unit_file)
    plist_dict, warnings = translate_to_plist(unit)

    if warnings:
        console.print("[yellow]Warnings:[/yellow]")
        for warning in warnings:
            console.print(f"  • {warning}")
        console.print()

    launch_agents = user_launch_agents()
    launch_agents.mkdir(parents=True, exist_ok=True)
    plist_path = launch_agents / f"{plist_dict['Label']}.plist"

    log_dir = dystemctl_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        console.print(f"[dim]Would write to: {plist_path}[/dim]")
        console.print()
        console.print(plistlib.dumps(plist_dict).decode())
        return

    with open(plist_path, "wb") as f:
        plistlib.dump(plist_dict, f)

    console.print(f"[green]Created:[/green] {plist_path}")

    build_registry.cache_clear()

    if enable_:
        if launchctl_enable(plist_path):
            console.print(f"[green]Enabled:[/green] {plist_dict['Label']}")
        else:
            err_console.print(f"[red]Failed to enable[/red] {plist_dict['Label']}")


@app.command("export")
def export_unit(
    service: ServiceArg,
    output: Annotated[
        Path | None, typer.Option("-o", "--output", help="Output file path")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", "-n", help="Show what would be generated")
    ] = False,
):
    """Export a launchd service to systemd unit file format."""
    info = resolve_service(service)
    if not info:
        service_not_found_error(service)
        raise typer.Exit(1)

    unit_content, warnings = translate_plist_to_unit(info)

    if warnings:
        console.print("[yellow]Warnings:[/yellow]")
        for warning in warnings:
            console.print(f"  • {warning}")
        console.print()

    if dry_run or output is None:
        console.print(f"[dim]# {info.label}.service[/dim]")
        console.print(unit_content)
        if output is None and not dry_run:
            console.print()
            console.print("[dim]Use --output to write to a file[/dim]")
        return

    output.write_text(unit_content)
    console.print(f"[green]Exported:[/green] {output}")


# --- Utility commands ---


@app.command()
def resolve(query: str):
    """Show what a service name resolves to."""
    info = resolve_service(query)
    if info:
        console.print(f"{query} → {info.label}")
        console.print(f"  Plist: {info.plist_path}")
        if info.binary_name:
            console.print(f"  Binary: {info.binary_name}")
    else:
        err_console.print(f"[red]No match found for:[/red] {query}")
        raise typer.Exit(1)


@app.command()
def setup(
    shell: Annotated[
        str | None,
        typer.Option(help="Shell to generate completions for (bash/zsh/fish)"),
    ] = None,
    bin_dir: Annotated[
        Path | None, typer.Option(help="Directory to install symlinks")
    ] = None,
):
    """Set up symlinks and shell completions."""
    import typer.completion

    if bin_dir is None:
        bin_dir = Path.home() / ".local" / "bin"

    if not shell:
        shell_path = os.environ.get("SHELL", "/bin/zsh")
        shell = Path(shell_path).name
        if shell not in ("bash", "zsh", "fish"):
            shell = "zsh"

    bin_dir.mkdir(parents=True, exist_ok=True)

    script_path = Path(__file__).resolve().parent.parent / "dystemctl.py"
    if not script_path.exists():
        script_path = Path(sys.executable)

    for name in ["systemctl", "journalctl"]:
        link_path = bin_dir / name
        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()
        link_path.symlink_to(script_path)
        console.print(f"[green]Created symlink:[/green] {link_path} → {script_path}")

    console.print()
    console.print(f"[bold]Shell completions for {shell}:[/bold]")

    for prog_name in ["systemctl", "journalctl"]:
        complete_var = f"_{prog_name.upper()}_COMPLETE"
        script = typer.completion.get_completion_script(
            prog_name=prog_name,
            complete_var=complete_var,
            shell=shell,
        )
        console.print(f"\n[dim]# {prog_name} completion[/dim]")
        console.print(script)

    console.print()
    console.print("[bold]To enable completions, add to your shell config:[/bold]")

    if shell == "zsh":
        comp_dir = Path.home() / ".local" / "share" / "zsh" / "completions"
        comp_dir.mkdir(parents=True, exist_ok=True)

        for prog_name in ["systemctl", "journalctl"]:
            complete_var = f"_{prog_name.upper()}_COMPLETE"
            script = typer.completion.get_completion_script(
                prog_name=prog_name,
                complete_var=complete_var,
                shell=shell,
            )
            comp_file = comp_dir / f"_{prog_name}"
            comp_file.write_text(script)
            console.print(f"[green]Wrote:[/green] {comp_file}")

        console.print()
        console.print("[bold]Add to ~/.zshrc:[/bold]")
        console.print(f'  fpath=("{comp_dir}" $fpath)')
        console.print("  autoload -Uz compinit && compinit")

    elif shell == "bash":
        console.print('  eval "$(systemctl --show-completion bash)"')
        console.print('  eval "$(journalctl --show-completion bash)"')

    elif shell == "fish":
        console.print("  systemctl --show-completion fish | source")
        console.print("  journalctl --show-completion fish | source")

    console.print()
    console.print(f"[yellow]Note:[/yellow] Ensure {bin_dir} is in your PATH")


@app.command()
def escape(
    strings: Annotated[list[str], typer.Argument(help="Strings to escape")],
    path: Annotated[
        bool, typer.Option("-p", "--path", help="Escape as path (remove leading /)")
    ] = False,
    unescape: Annotated[
        bool, typer.Option("-u", "--unescape", help="Unescape instead of escaping")
    ] = False,
):
    """Escape strings for use in service names.

    Similar to systemd's escaping: replaces / with -, removes leading dash for paths.
    """
    for s in strings:
        if unescape:
            result = s.replace("-", "/")
            if path and not result.startswith("/"):
                result = "/" + result
        else:
            result = s
            if path and result.startswith("/"):
                result = result[1:]
            result = result.replace("/", "-")
        console.print(result)


@app.command()
def verify(
    files: Annotated[
        list[Path], typer.Argument(help="Plist or service files to verify")
    ],
):
    """Verify service definition files for correctness."""
    failed = False

    for file_path in files:
        if not file_path.exists():
            err_console.print(f"[red]✗[/red] {file_path}: File not found")
            failed = True
            continue

        if file_path.suffix == ".service":
            try:
                unit = parse_systemd_unit(file_path)
                _, warnings = translate_to_plist(unit)
                if warnings:
                    console.print(
                        f"[yellow]⚠[/yellow] {file_path}: Valid with warnings"
                    )
                    for w in warnings:
                        console.print(f"    {w}")
                else:
                    console.print(f"[green]✓[/green] {file_path}: Valid systemd unit")
            except (OSError, ValueError, KeyError) as e:
                err_console.print(f"[red]✗[/red] {file_path}: {e}")
                failed = True

        elif file_path.suffix == ".plist":
            try:
                with open(file_path, "rb") as f:
                    plist_dict = plistlib.load(f)

                issues = []

                if "Label" not in plist_dict:
                    issues.append("Missing required 'Label' key")

                if "ProgramArguments" not in plist_dict and "Program" not in plist_dict:
                    issues.append("Missing 'ProgramArguments' or 'Program' key")

                if "ProgramArguments" in plist_dict:
                    args = plist_dict["ProgramArguments"]
                    if args and not Path(args[0]).is_absolute():
                        issues.append(f"Program path should be absolute: {args[0]}")

                if "Program" in plist_dict:
                    prog = plist_dict["Program"]
                    if not Path(prog).is_absolute():
                        issues.append(f"Program path should be absolute: {prog}")

                if issues:
                    console.print(f"[yellow]⚠[/yellow] {file_path}: Issues found")
                    for issue in issues:
                        console.print(f"    {issue}")
                else:
                    console.print(f"[green]✓[/green] {file_path}: Valid plist")

            except plistlib.InvalidFileException as e:
                err_console.print(
                    f"[red]✗[/red] {file_path}: Invalid plist format - {e}"
                )
                failed = True
            except OSError as e:
                err_console.print(f"[red]✗[/red] {file_path}: {e}")
                failed = True
        else:
            err_console.print(
                f"[yellow]⚠[/yellow] {file_path}: Unknown file type (expected .service or .plist)"
            )

    if failed:
        raise typer.Exit(1)


@app.command()
def alias(name: str, label: str):
    """Add an alias for a service label."""
    config_dir = dystemctl_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)

    alias_file = config_dir / "aliases.toml"

    try:
        import tomllib

        if alias_file.exists():
            with open(alias_file, "rb") as f:
                data = tomllib.load(f)
        else:
            data = {}
    except (OSError, tomllib.TOMLDecodeError):
        data = {}

    if "aliases" not in data:
        data["aliases"] = {}

    data["aliases"][name] = label

    lines = ["[aliases]"]
    for k, v in data["aliases"].items():
        lines.append(f'{k} = "{v}"')
    alias_file.write_text("\n".join(lines) + "\n")

    console.print(f"[green]Added alias:[/green] {name} → {label}")
