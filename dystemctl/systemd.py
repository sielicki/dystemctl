"""Systemd unit file parsing and translation."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path

from .models import ServiceInfo
from .paths import dystemctl_log_dir


@dataclass
class SystemdUnit:
    name: str
    source_path: Path
    unit: dict[str, str] = field(default_factory=dict)
    service: dict[str, str] = field(default_factory=dict)
    install: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def parse_systemd_unit(path: Path) -> SystemdUnit:
    unit = SystemdUnit(
        name=path.stem,
        source_path=path,
    )

    current_section = None
    section_map = {
        "[Unit]": unit.unit,
        "[Service]": unit.service,
        "[Install]": unit.install,
    }

    with open(path) as f:
        for line in f:
            line = line.strip()

            if not line or line.startswith("#") or line.startswith(";"):
                continue

            if line.startswith("[") and line.endswith("]"):
                current_section = section_map.get(line)
                if current_section is None and line not in section_map:
                    unit.warnings.append(f"Unknown section: {line}")
                continue

            if current_section is None:
                continue

            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()

                # Handle line continuations
                while value.endswith("\\"):
                    value = value[:-1]
                    next_line = next(f, "").strip()
                    value += next_line

                # Handle multiple values (systemd allows repeated keys)
                if key in current_section:
                    current_section[key] += "\n" + value
                else:
                    current_section[key] = value

    return unit


def expand_specifiers(value: str, unit_name: str) -> str:
    replacements = {
        "%n": unit_name,
        "%N": unit_name,
        "%p": unit_name.split("@")[0] if "@" in unit_name else unit_name,
        "%i": unit_name.split("@")[1].replace(".service", "")
        if "@" in unit_name
        else "",
        "%u": os.environ.get("USER", ""),
        "%U": str(os.getuid()),
        "%h": str(Path.home()),
        "%t": os.environ.get("TMPDIR", "/tmp"),
        "%S": str(Path.home() / "Library" / "Application Support"),
        "%C": str(Path.home() / "Library" / "Caches"),
        "%L": str(Path.home() / "Library" / "Logs"),
        "%%": "%",
    }

    for spec, replacement in replacements.items():
        value = value.replace(spec, replacement)

    return value


def parse_exec_start(value: str) -> tuple[list[str], list[str]]:
    """Parse ExecStart, returning (program_arguments, warnings)."""
    warnings = []

    # Handle prefixes
    value = value.strip()
    while value and value[0] in "-@!+:":
        prefix = value[0]
        value = value[1:].strip()
        if prefix == "-":
            warnings.append(
                "ExecStart prefix '-' (ignore exit code) not fully supported"
            )
        elif prefix == "@":
            warnings.append("ExecStart prefix '@' (custom argv[0]) not supported")
        elif prefix in "!+":
            warnings.append(
                f"ExecStart prefix '{prefix}' (elevated privileges) ignored"
            )

    # Split into arguments (simple split, doesn't handle all quoting)
    try:
        args = shlex.split(value)
    except ValueError:
        args = value.split()

    return args, warnings


UNSUPPORTED_SERVICE_KEYS = {
    "Type": lambda v: None
    if v in ("simple", "exec", "oneshot")
    else (
        "Type=notify not supported (no sd_notify equivalent on macOS)"
        if v == "notify"
        else f"Type={v} not supported (launchd expects foreground processes)"
    ),
    "After": lambda v: "After= not supported (launchd uses on-demand activation, not explicit ordering)",
    "Before": lambda v: "Before= not supported",
    "Requires": lambda v: "Requires= not supported (launchd uses on-demand activation)",
    "Wants": lambda v: "Wants= not supported",
    "BindsTo": lambda v: "BindsTo= not supported",
    "PartOf": lambda v: "PartOf= not supported",
    "Conflicts": lambda v: "Conflicts= not supported",
    "RuntimeDirectory": lambda v: "RuntimeDirectory= not directly supported",
    "RuntimeDirectoryMode": lambda v: None,
    "StateDirectory": lambda v: "StateDirectory= not directly supported",
    "CacheDirectory": lambda v: "CacheDirectory= not directly supported",
    "LogsDirectory": lambda v: "LogsDirectory= not directly supported",
    "PrivateTmp": lambda v: "PrivateTmp= not supported (use macOS sandbox profiles instead)",
    "ProtectSystem": lambda v: "ProtectSystem= not supported",
    "ProtectHome": lambda v: "ProtectHome= not supported",
    "NoNewPrivileges": lambda v: "NoNewPrivileges= not supported",
    "CapabilityBoundingSet": lambda v: "CapabilityBoundingSet= not supported",
    "AmbientCapabilities": lambda v: "AmbientCapabilities= not supported",
    "RestrictNamespaces": lambda v: "RestrictNamespaces= not supported",
    "RestrictSUIDSGID": lambda v: "RestrictSUIDSGID= not supported",
    "MemoryLimit": lambda v: "MemoryLimit= not supported (no cgroup equivalent)",
    "CPUQuota": lambda v: "CPUQuota= not supported",
    "TasksMax": lambda v: "TasksMax= not supported",
    "LimitNOFILE": lambda v: None,  # Could map to SoftResourceLimits
    "LimitNPROC": lambda v: None,
    "KillMode": lambda v: "KillMode= not supported (launchd always kills process group)",
    "KillSignal": lambda v: "KillSignal= not supported (launchd uses SIGTERM then SIGKILL)",
    "TimeoutStartSec": lambda v: "TimeoutStartSec= not directly supported",
    "TimeoutStopSec": lambda v: None,  # Maps to ExitTimeOut
    "WatchdogSec": lambda v: "WatchdogSec= not supported (no sd_notify equivalent)",
    "NotifyAccess": lambda v: "NotifyAccess= not supported",
    "Sockets": lambda v: "Sockets= not supported (launchd has different socket activation)",
    "ExecStartPre": lambda v: "ExecStartPre= requires a wrapper script; consider combining commands in a shell script",
    "ExecStartPost": lambda v: "ExecStartPost= requires a wrapper script; consider combining commands in a shell script",
    "ExecReload": lambda v: "ExecReload= not supported (launchd has no reload concept)",
    "ExecStop": lambda v: "ExecStop= not supported (launchd sends SIGTERM)",
    "ExecStopPost": lambda v: "ExecStopPost= not supported",
}


def translate_to_plist(unit: SystemdUnit) -> tuple[dict, list[str]]:
    plist: dict = {}
    warnings = unit.warnings.copy()

    # Label
    label = f"org.dystemctl.{os.environ.get('USER', 'user')}.{unit.name}"
    plist["Label"] = label

    # ExecStart → ProgramArguments
    if "ExecStart" in unit.service:
        exec_start = expand_specifiers(unit.service["ExecStart"], unit.name)
        args, exec_warnings = parse_exec_start(exec_start)
        warnings.extend(exec_warnings)
        plist["ProgramArguments"] = args

    # WorkingDirectory
    if "WorkingDirectory" in unit.service:
        wd = expand_specifiers(unit.service["WorkingDirectory"], unit.name)
        if wd == "~":
            wd = str(Path.home())
        plist["WorkingDirectory"] = wd

    # User/Group
    if "User" in unit.service:
        plist["UserName"] = unit.service["User"]
    if "Group" in unit.service:
        plist["GroupName"] = unit.service["Group"]

    # UMask
    if "UMask" in unit.service:
        try:
            umask_val = unit.service["UMask"]
            # Convert from octal string (e.g., "0022") to integer
            plist["Umask"] = int(umask_val, 8)
        except ValueError:
            warnings.append(f"Could not parse UMask={unit.service['UMask']}")

    # Environment
    env_vars = {}
    if "Environment" in unit.service:
        for env_line in unit.service["Environment"].split("\n"):
            # Handle quoted environment variables like "FOO=bar" "BAZ=qux"
            try:
                parts = shlex.split(env_line)
            except ValueError:
                parts = env_line.split()
            for part in parts:
                if "=" in part:
                    key, _, val = part.partition("=")
                    # Strip quotes from key and value
                    key = key.strip("'\"")
                    val = val.strip("'\"")
                    env_vars[key] = expand_specifiers(val, unit.name)
    if env_vars:
        plist["EnvironmentVariables"] = env_vars

    # Restart → KeepAlive
    restart = unit.service.get("Restart", "no")
    if restart == "always":
        plist["KeepAlive"] = True
    elif restart == "on-failure":
        plist["KeepAlive"] = {"SuccessfulExit": False}
    elif restart == "on-success":
        plist["KeepAlive"] = {"SuccessfulExit": True}
    elif restart == "on-abnormal":
        plist["KeepAlive"] = {"SuccessfulExit": False}
        warnings.append(
            "Restart=on-abnormal mapped to SuccessfulExit=false (not exact)"
        )
    elif restart != "no":
        warnings.append(f"Restart={restart} not fully supported")

    # RestartSec → ThrottleInterval
    if "RestartSec" in unit.service:
        try:
            secs = int(unit.service["RestartSec"].rstrip("s"))
            plist["ThrottleInterval"] = secs
        except ValueError:
            warnings.append(f"Could not parse RestartSec={unit.service['RestartSec']}")

    # StandardOutput/StandardError
    stdout = unit.service.get("StandardOutput", "")
    stderr = unit.service.get("StandardError", "")

    log_dir = dystemctl_log_dir()

    if stdout.startswith("file:"):
        plist["StandardOutPath"] = expand_specifiers(stdout[5:], unit.name)
    elif stdout in ("journal", "syslog", ""):
        plist["StandardOutPath"] = str(log_dir / f"{unit.name}.log")
    elif stdout == "null":
        plist["StandardOutPath"] = "/dev/null"
    else:
        warnings.append(f"StandardOutput={stdout} not fully supported")
        plist["StandardOutPath"] = str(log_dir / f"{unit.name}.log")

    if stderr.startswith("file:"):
        plist["StandardErrorPath"] = expand_specifiers(stderr[5:], unit.name)
    elif stderr in ("journal", "syslog", "inherit", ""):
        plist["StandardErrorPath"] = plist.get(
            "StandardOutPath", str(log_dir / f"{unit.name}.err")
        )
    elif stderr == "null":
        plist["StandardErrorPath"] = "/dev/null"
    else:
        warnings.append(f"StandardError={stderr} not fully supported")

    # TimeoutStopSec → ExitTimeOut
    if "TimeoutStopSec" in unit.service:
        try:
            secs = int(unit.service["TimeoutStopSec"].rstrip("s"))
            plist["ExitTimeOut"] = secs
        except ValueError:
            pass

    # Resource limits → SoftResourceLimits
    soft_limits = {}
    if "LimitNOFILE" in unit.service:
        try:
            limit_val = unit.service["LimitNOFILE"]
            if limit_val.lower() == "infinity":
                # macOS maximum is typically around 12288 for soft limit
                soft_limits["NumberOfFiles"] = 10240
            else:
                soft_limits["NumberOfFiles"] = int(limit_val)
        except ValueError:
            pass

    if "LimitNPROC" in unit.service:
        try:
            limit_val = unit.service["LimitNPROC"]
            if limit_val.lower() != "infinity":
                soft_limits["NumberOfProcesses"] = int(limit_val)
        except ValueError:
            pass

    if "LimitCORE" in unit.service:
        try:
            limit_val = unit.service["LimitCORE"]
            if limit_val.lower() == "infinity":
                soft_limits["CoreFileSize"] = -1  # unlimited
            elif limit_val != "0":
                soft_limits["CoreFileSize"] = int(limit_val)
        except ValueError:
            pass

    if soft_limits:
        plist["SoftResourceLimits"] = soft_limits

    # RunAtLoad (from Install section)
    wanted_by = unit.install.get("WantedBy", "")
    if "default.target" in wanted_by or "multi-user.target" in wanted_by:
        plist["RunAtLoad"] = True

    # Check for unsupported keys
    for key, value in unit.service.items():
        if key in UNSUPPORTED_SERVICE_KEYS:
            warning = UNSUPPORTED_SERVICE_KEYS[key](value)
            if warning:
                warnings.append(warning)

    # Check Unit section
    for key in ["After", "Before", "Requires", "Wants", "BindsTo"]:
        if key in unit.unit:
            warnings.append(f"{key}= not supported (launchd uses on-demand activation)")

    return plist, warnings


def translate_plist_to_unit(info: ServiceInfo) -> tuple[str, list[str]]:
    """Convert a launchd plist to a systemd unit file string."""
    warnings = []
    lines = []

    # [Unit] section
    lines.append("[Unit]")
    lines.append(f"Description={info.display_name}")
    lines.append("")

    # [Service] section
    lines.append("[Service]")

    if info.program_arguments:
        exec_start = " ".join(info.program_arguments)
        lines.append(f"ExecStart={exec_start}")
    elif info.program:
        lines.append(f"ExecStart={info.program}")

    if info.working_directory:
        lines.append(f"WorkingDirectory={info.working_directory}")

    if info.user_name:
        lines.append(f"User={info.user_name}")

    if info.keep_alive:
        lines.append("Restart=always")
    else:
        lines.append("Restart=on-failure")

    if info.standard_out_path:
        lines.append(f"StandardOutput=file:{info.standard_out_path}")

    if info.standard_error_path:
        lines.append(f"StandardError=file:{info.standard_error_path}")

    # Timer -> OnCalendar (basic support)
    if info.start_interval:
        warnings.append(
            f"StartInterval={info.start_interval} should be a separate .timer unit"
        )
    if info.start_calendar_interval:
        warnings.append("StartCalendarInterval should be a separate .timer unit")

    # Socket activation
    if info.sockets:
        warnings.append("Socket activation should be a separate .socket unit")

    lines.append("")

    # [Install] section
    lines.append("[Install]")
    if info.run_at_load:
        lines.append("WantedBy=default.target")
    else:
        lines.append("WantedBy=multi-user.target")

    return "\n".join(lines), warnings
