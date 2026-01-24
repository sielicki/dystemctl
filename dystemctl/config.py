"""Configuration management for dystemctl."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .paths import dystemctl_config_dir


@dataclass
class Config:
    cache_ttl_seconds: int = 300
    extra_plist_paths: list[Path] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls) -> Config:
        config_dir = dystemctl_config_dir()
        config = cls()

        alias_file = config_dir / "aliases.toml"
        if alias_file.exists():
            try:
                import tomllib

                with open(alias_file, "rb") as f:
                    data = tomllib.load(f)
                    config.aliases = data.get("aliases", {})
            except (OSError, tomllib.TOMLDecodeError):
                pass

        return config


CONFIG = Config.load()
