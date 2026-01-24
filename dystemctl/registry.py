"""Service registry for discovering and resolving launchd services."""

from __future__ import annotations

import plistlib
import sys
from functools import cache
from pathlib import Path

from .config import CONFIG
from .models import ServiceInfo, ServiceMatch, SocketInfo
from .paths import user_launch_agents
from .utils import levenshtein_distance

HOMEBREW_PREFIX = "homebrew.mxcl."


def _ensure_list(value: str | list | None, default: list | None = None) -> list:
    """Normalize a value to a list (handles single strings or None)."""
    if value is None:
        return default if default is not None else []
    if isinstance(value, str):
        return [value]
    return value


def _get_plist_search_paths() -> list[Path]:
    """Return list of directories to search for plist files."""
    paths = [
        Path("/System/Library/LaunchDaemons"),
        Path("/System/Library/LaunchAgents"),
        Path("/Library/LaunchDaemons"),
        Path("/Library/LaunchAgents"),
        user_launch_agents(),
    ]

    # Homebrew paths
    for prefix in [Path("/opt/homebrew"), Path("/usr/local")]:
        if prefix.exists():
            paths.append(prefix / "Cellar")

    # nix-darwin
    nix_darwin = Path("/run/current-system/Library/LaunchDaemons")
    if nix_darwin.exists():
        paths.append(nix_darwin)

    return paths


def _parse_single_socket(name: str, sock_data: dict) -> SocketInfo:
    """Parse a single socket definition from plist data."""
    sock_type = sock_data.get("SockType", "stream")
    family = sock_data.get("SockFamily", "IPv4")

    if "SockPathName" in sock_data:
        family = "Unix"
        address = sock_data["SockPathName"]
    else:
        host = sock_data.get("SockNodeName", "*")
        port = sock_data.get("SockServiceName", "?")
        address = f"{host}:{port}"

    return SocketInfo(name=name, sock_type=sock_type, family=family, address=address)


def parse_sockets(sockets_dict: dict) -> list[SocketInfo]:
    """Parse socket definitions from a plist Sockets dictionary."""
    sockets = []
    for name, sock_data in sockets_dict.items():
        if isinstance(sock_data, dict):
            sockets.append(_parse_single_socket(name, sock_data))
        elif isinstance(sock_data, list):
            for i, sd in enumerate(sock_data):
                if isinstance(sd, dict):
                    sockets.append(_parse_single_socket(f"{name}[{i}]", sd))
    return sockets


def parse_plist(path: Path) -> ServiceInfo | None:
    """Parse a launchd plist file into a ServiceInfo object, or None on error."""
    try:
        with open(path, "rb") as f:
            data = plistlib.load(f)

        label = data.get("Label")
        if not label:
            return None

        calendar = data.get("StartCalendarInterval")
        if isinstance(calendar, dict):
            calendar = [calendar]

        sockets = []
        if "Sockets" in data:
            sockets = parse_sockets(data["Sockets"])

        watch_paths = _ensure_list(data.get("WatchPaths"))
        queue_dirs = _ensure_list(data.get("QueueDirectories"))

        mach_services = []
        if "MachServices" in data:
            mach_services = (
                list(data["MachServices"].keys())
                if isinstance(data["MachServices"], dict)
                else []
            )

        return ServiceInfo(
            label=label,
            plist_path=path,
            program=data.get("Program"),
            program_arguments=data.get("ProgramArguments"),
            run_at_load=data.get("RunAtLoad", False),
            keep_alive=bool(data.get("KeepAlive", False)),
            standard_out_path=Path(p) if (p := data.get("StandardOutPath")) else None,
            standard_error_path=Path(p)
            if (p := data.get("StandardErrorPath"))
            else None,
            user_name=data.get("UserName"),
            group_name=data.get("GroupName"),
            working_directory=Path(p) if (p := data.get("WorkingDirectory")) else None,
            start_interval=data.get("StartInterval"),
            start_calendar_interval=calendar,
            sockets=sockets,
            watch_paths=watch_paths,
            queue_directories=queue_dirs,
            mach_services=mach_services,
        )
    except Exception:
        # plist files can fail in many ways: corrupted XML, missing keys, permission errors
        return None


@cache
def build_registry() -> dict[str, ServiceInfo]:
    registry: dict[str, ServiceInfo] = {}

    for search_path in _get_plist_search_paths():
        if not search_path.exists():
            continue

        for plist_path in search_path.rglob("*.plist"):
            if info := parse_plist(plist_path):
                registry[info.label] = info

    return registry


def get_all_services() -> list[ServiceInfo]:
    return list(build_registry().values())


def get_service_labels() -> list[str]:
    return list(build_registry().keys())


def find_similar_services(query: str, max_suggestions: int = 3) -> list[str]:
    registry = build_registry()
    query_lower = query.lower()

    scored = []
    for label, info in registry.items():
        label_lower = label.lower()
        short_name = label.split(".")[-1].lower()

        dist_full = levenshtein_distance(query_lower, label_lower)
        dist_short = levenshtein_distance(query_lower, short_name)
        dist = min(dist_full, dist_short)

        if dist <= max(len(query) // 2, 3):
            scored.append((dist, label))

        if info.binary_name:
            bin_dist = levenshtein_distance(query_lower, info.binary_name.lower())
            if bin_dist <= max(len(query) // 2, 3):
                scored.append((bin_dist, label))

    scored.sort(key=lambda x: x[0])
    seen = set()
    suggestions = []
    for _, label in scored:
        if label not in seen:
            seen.add(label)
            suggestions.append(label)
            if len(suggestions) >= max_suggestions:
                break
    return suggestions


def resolve_service(query: str, warn_ambiguous: bool = True) -> ServiceInfo | None:
    """Resolve a service query to a ServiceInfo.

    Args:
        query: Service name, alias, or pattern to resolve
        warn_ambiguous: If True, print warning when multiple services match

    Returns:
        ServiceInfo if found, None otherwise
    """
    registry = build_registry()

    if query in CONFIG.aliases:
        query = CONFIG.aliases[query]

    if query in registry:
        return registry[query]

    if query.endswith(".service"):
        base = query[:-8]
        if base in registry:
            return registry[base]

    candidates: list[ServiceMatch] = []
    query_lower = query.lower()

    # Handle template-style queries (e.g., "foo@bar" -> match "foo@bar" or "foo")
    template_base = None
    template_instance = None
    if "@" in query:
        template_base, template_instance = query.split("@", 1)
        template_base_lower = template_base.lower()

    for label, info in registry.items():
        label_lower = label.lower()

        if label_lower == query_lower:
            candidates.append(ServiceMatch(info, 1.0, "exact"))
            continue

        if info.binary_name and info.binary_name.lower() == query_lower:
            candidates.append(ServiceMatch(info, 0.95, "binary"))
            continue

        if label_lower.endswith(f".{query_lower}"):
            candidates.append(ServiceMatch(info, 0.9, "suffix"))
            continue

        # Handle versioned/templated service names (e.g., emacs-plus@30)
        if "@" in label:
            label_base = label.split("@")[0]
            label_base_lower = label_base.lower()

            # Match base name if query has no @
            if "@" not in query and query_lower == label_base_lower:
                candidates.append(ServiceMatch(info, 0.88, "template_base"))
                continue

            # Match full template pattern
            if template_base and template_base_lower in label_base_lower:
                candidates.append(ServiceMatch(info, 0.87, "template_match"))
                continue

        # Match versioned homebrew services: homebrew.mxcl.foo@version
        if label_lower.startswith(HOMEBREW_PREFIX):
            brew_name = label_lower[len(HOMEBREW_PREFIX) :]
            if query_lower == brew_name:
                candidates.append(ServiceMatch(info, 0.92, "homebrew_exact"))
                continue
            # Strip version suffix for matching (e.g., "emacs-plus@30" -> "emacs-plus")
            if "@" in brew_name:
                brew_base = brew_name.split("@")[0]
                if query_lower == brew_base:
                    candidates.append(ServiceMatch(info, 0.88, "homebrew_base"))
                    continue
            if query_lower in brew_name:
                candidates.append(ServiceMatch(info, 0.85, "homebrew"))
                continue

        if query_lower in label_lower:
            candidates.append(ServiceMatch(info, 0.7, "substring"))
            continue

    if not candidates:
        return None

    candidates.sort(key=lambda m: m.confidence, reverse=True)

    # Check for ambiguous matches - multiple candidates with similar confidence
    if warn_ambiguous and len(candidates) > 1:
        top = candidates[0]
        ambiguous = [
            c for c in candidates[1:] if abs(c.confidence - top.confidence) < 0.05
        ]
        if ambiguous and top.match_type not in ("exact", "binary"):
            print(
                f"Warning: '{query}' matches multiple services, using {top.info.label}",
                file=sys.stderr,
            )
            print("  Other matches:", file=sys.stderr)
            for c in ambiguous[:3]:
                print(f"    - {c.info.label}", file=sys.stderr)

    if candidates[0].confidence >= 0.7:
        return candidates[0].info

    return None


def complete_service(incomplete: str) -> list[str]:
    """Return service labels matching the incomplete string for shell completion."""
    registry = build_registry()
    incomplete_lower = incomplete.lower()

    matches = []
    for label, info in registry.items():
        if (
            incomplete_lower in label.lower()
            or info.binary_name
            and incomplete_lower in info.binary_name.lower()
        ):
            matches.append(label)

    # Also add aliases
    for alias in CONFIG.aliases:
        if incomplete_lower in alias.lower():
            matches.append(alias)

    return sorted(set(matches))
