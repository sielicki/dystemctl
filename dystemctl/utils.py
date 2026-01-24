"""Utility functions for dystemctl."""

from __future__ import annotations

from datetime import datetime, timedelta


def format_bytes(n: int) -> str:
    """Format bytes as human-readable string (e.g., 1024 -> '1.0K')."""
    for unit in ("B", "K", "M", "G"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}T"


def format_elapsed(td: timedelta) -> str:
    """Format a timedelta as human-readable duration (e.g., '2h 30min')."""
    total_seconds = int(td.total_seconds())
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    if days > 0:
        return f"{days}d {hours}h"
    elif hours > 0:
        return f"{hours}h {minutes}min"
    elif minutes > 0:
        return f"{minutes}min {seconds}s"
    else:
        return f"{seconds}s"


def format_since(elapsed: timedelta) -> str:
    """Format elapsed time as 'date; Xh ago' string."""
    now = datetime.now()
    since = now - elapsed
    since_str = since.strftime("%a %Y-%m-%d %H:%M:%S")
    return f"{since_str}; {format_elapsed(elapsed)} ago"


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate the Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]
