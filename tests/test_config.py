"""Tests for dystemctl.config module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from dystemctl.config import Config


class TestConfig:
    def test_default_values(self):
        config = Config()
        assert config.cache_ttl_seconds == 300
        assert config.extra_plist_paths == []
        assert config.aliases == {}

    def test_load_no_config_dir(self, temp_dir: Path):
        with patch("pathlib.Path.home", return_value=temp_dir):
            config = Config.load()
            assert config.aliases == {}

    def test_load_with_aliases(self, temp_dir: Path):
        config_dir = temp_dir / ".config" / "dystemctl"
        config_dir.mkdir(parents=True)

        alias_file = config_dir / "aliases.toml"
        alias_file.write_text("""
[aliases]
pg = "homebrew.mxcl.postgresql"
redis = "homebrew.mxcl.redis"
""")

        with patch("pathlib.Path.home", return_value=temp_dir):
            config = Config.load()
            assert config.aliases == {
                "pg": "homebrew.mxcl.postgresql",
                "redis": "homebrew.mxcl.redis",
            }

    def test_load_with_invalid_toml(self, temp_dir: Path):
        config_dir = temp_dir / ".config" / "dystemctl"
        config_dir.mkdir(parents=True)

        alias_file = config_dir / "aliases.toml"
        alias_file.write_text("invalid toml content ][[[")

        with patch("pathlib.Path.home", return_value=temp_dir):
            config = Config.load()
            assert config.aliases == {}

    def test_load_with_empty_aliases(self, temp_dir: Path):
        config_dir = temp_dir / ".config" / "dystemctl"
        config_dir.mkdir(parents=True)

        alias_file = config_dir / "aliases.toml"
        alias_file.write_text("")

        with patch("pathlib.Path.home", return_value=temp_dir):
            config = Config.load()
            assert config.aliases == {}

    def test_load_with_missing_aliases_key(self, temp_dir: Path):
        config_dir = temp_dir / ".config" / "dystemctl"
        config_dir.mkdir(parents=True)

        alias_file = config_dir / "aliases.toml"
        alias_file.write_text("""
[other_section]
key = "value"
""")

        with patch("pathlib.Path.home", return_value=temp_dir):
            config = Config.load()
            assert config.aliases == {}
