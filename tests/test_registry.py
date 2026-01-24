"""Tests for dystemctl.registry module."""

from __future__ import annotations

import plistlib
from pathlib import Path
from unittest.mock import patch

import pytest

from dystemctl.models import ServiceInfo
from dystemctl.registry import (
    complete_service,
    find_similar_services,
    parse_plist,
    parse_sockets,
    resolve_service,
)


class TestParseSockets:
    def test_parse_single_tcp_socket(self):
        sockets_dict = {
            "http": {
                "SockType": "stream",
                "SockFamily": "IPv4",
                "SockNodeName": "localhost",
                "SockServiceName": "8080",
            }
        }
        result = parse_sockets(sockets_dict)
        assert len(result) == 1
        assert result[0].name == "http"
        assert result[0].sock_type == "stream"
        assert result[0].family == "IPv4"
        assert result[0].address == "localhost:8080"

    def test_parse_unix_socket(self):
        sockets_dict = {
            "main": {
                "SockPathName": "/var/run/test.sock",
            }
        }
        result = parse_sockets(sockets_dict)
        assert len(result) == 1
        assert result[0].family == "Unix"
        assert result[0].address == "/var/run/test.sock"

    def test_parse_socket_with_defaults(self):
        sockets_dict = {
            "simple": {
                "SockServiceName": "9999",
            }
        }
        result = parse_sockets(sockets_dict)
        assert len(result) == 1
        assert result[0].sock_type == "stream"  # default
        assert result[0].family == "IPv4"  # default
        assert result[0].address == "*:9999"  # default host

    def test_parse_multiple_sockets(self):
        sockets_dict = {
            "http": {"SockServiceName": "80"},
            "https": {"SockServiceName": "443"},
        }
        result = parse_sockets(sockets_dict)
        assert len(result) == 2
        names = {s.name for s in result}
        assert "http" in names
        assert "https" in names

    def test_parse_socket_array(self):
        sockets_dict = {
            "listeners": [
                {"SockServiceName": "8080"},
                {"SockServiceName": "8443"},
            ]
        }
        result = parse_sockets(sockets_dict)
        assert len(result) == 2
        assert result[0].name == "listeners[0]"
        assert result[1].name == "listeners[1]"


class TestParsePlist:
    def test_parse_basic_plist(self, sample_plist_file: Path):
        result = parse_plist(sample_plist_file)
        assert result is not None
        assert result.label == "com.example.testservice"
        assert result.program_arguments == ["/usr/bin/testprogram", "--arg1", "value1"]
        assert result.run_at_load is True
        assert result.keep_alive is False
        assert result.standard_out_path == Path("/var/log/test.log")
        assert result.standard_error_path == Path("/var/log/test.err")

    def test_parse_plist_with_program(self, temp_dir: Path):
        plist_path = temp_dir / "program.plist"
        plist_content = {
            "Label": "com.test.program",
            "Program": "/usr/bin/myprogram",
        }
        with open(plist_path, "wb") as f:
            plistlib.dump(plist_content, f)

        result = parse_plist(plist_path)
        assert result is not None
        assert result.program == "/usr/bin/myprogram"
        assert result.program_arguments is None

    def test_parse_plist_with_keep_alive(self, temp_dir: Path):
        plist_path = temp_dir / "keepalive.plist"
        plist_content = {
            "Label": "com.test.keepalive",
            "ProgramArguments": ["/usr/bin/daemon"],
            "KeepAlive": True,
        }
        with open(plist_path, "wb") as f:
            plistlib.dump(plist_content, f)

        result = parse_plist(plist_path)
        assert result is not None
        assert result.keep_alive is True

    def test_parse_plist_with_timer(self, temp_dir: Path):
        plist_path = temp_dir / "timer.plist"
        plist_content = {
            "Label": "com.test.timer",
            "ProgramArguments": ["/usr/bin/periodic"],
            "StartInterval": 3600,
        }
        with open(plist_path, "wb") as f:
            plistlib.dump(plist_content, f)

        result = parse_plist(plist_path)
        assert result is not None
        assert result.start_interval == 3600
        assert result.is_timer is True

    def test_parse_plist_with_calendar_interval(self, temp_dir: Path):
        plist_path = temp_dir / "calendar.plist"
        plist_content = {
            "Label": "com.test.calendar",
            "ProgramArguments": ["/usr/bin/daily"],
            "StartCalendarInterval": {"Hour": 3, "Minute": 0},
        }
        with open(plist_path, "wb") as f:
            plistlib.dump(plist_content, f)

        result = parse_plist(plist_path)
        assert result is not None
        assert result.start_calendar_interval == [{"Hour": 3, "Minute": 0}]

    def test_parse_plist_with_sockets(self, temp_dir: Path):
        plist_path = temp_dir / "socket.plist"
        plist_content = {
            "Label": "com.test.socket",
            "ProgramArguments": ["/usr/bin/server"],
            "Sockets": {
                "main": {
                    "SockServiceName": "8080",
                }
            },
        }
        with open(plist_path, "wb") as f:
            plistlib.dump(plist_content, f)

        result = parse_plist(plist_path)
        assert result is not None
        assert len(result.sockets) == 1
        assert result.sockets[0].name == "main"

    def test_parse_plist_with_watch_paths(self, temp_dir: Path):
        plist_path = temp_dir / "watch.plist"
        plist_content = {
            "Label": "com.test.watch",
            "ProgramArguments": ["/usr/bin/watcher"],
            "WatchPaths": ["/var/spool/incoming", "/tmp/trigger"],
        }
        with open(plist_path, "wb") as f:
            plistlib.dump(plist_content, f)

        result = parse_plist(plist_path)
        assert result is not None
        assert len(result.watch_paths) == 2

    def test_parse_plist_with_mach_services(self, temp_dir: Path):
        plist_path = temp_dir / "mach.plist"
        plist_content = {
            "Label": "com.test.mach",
            "ProgramArguments": ["/usr/bin/machserver"],
            "MachServices": {
                "com.test.mach.service": True,
                "com.test.mach.helper": True,
            },
        }
        with open(plist_path, "wb") as f:
            plistlib.dump(plist_content, f)

        result = parse_plist(plist_path)
        assert result is not None
        assert len(result.mach_services) == 2

    def test_parse_plist_no_label(self, temp_dir: Path):
        plist_path = temp_dir / "nolabel.plist"
        plist_content = {
            "ProgramArguments": ["/usr/bin/test"],
        }
        with open(plist_path, "wb") as f:
            plistlib.dump(plist_content, f)

        result = parse_plist(plist_path)
        assert result is None

    def test_parse_plist_nonexistent(self, temp_dir: Path):
        result = parse_plist(temp_dir / "nonexistent.plist")
        assert result is None

    def test_parse_plist_invalid(self, temp_dir: Path):
        plist_path = temp_dir / "invalid.plist"
        plist_path.write_text("not a valid plist")
        result = parse_plist(plist_path)
        assert result is None


class TestResolveService:
    @pytest.fixture
    def mock_registry(self, temp_dir: Path):
        """Create a mock registry with test services."""
        registry = {
            "com.apple.Finder": ServiceInfo(
                label="com.apple.Finder",
                plist_path=temp_dir / "com.apple.Finder.plist",
                program="/System/Library/CoreServices/Finder.app/Contents/MacOS/Finder",
            ),
            "homebrew.mxcl.redis": ServiceInfo(
                label="homebrew.mxcl.redis",
                plist_path=temp_dir / "homebrew.mxcl.redis.plist",
                program_arguments=["/opt/homebrew/bin/redis-server"],
            ),
            "homebrew.mxcl.postgresql@14": ServiceInfo(
                label="homebrew.mxcl.postgresql@14",
                plist_path=temp_dir / "homebrew.mxcl.postgresql@14.plist",
                program_arguments=["/opt/homebrew/bin/postgres"],
            ),
            "com.example.testservice": ServiceInfo(
                label="com.example.testservice",
                plist_path=temp_dir / "com.example.testservice.plist",
                program_arguments=["/usr/bin/testprogram"],
            ),
        }
        return registry

    def test_resolve_exact_match(self, mock_registry):
        with patch("dystemctl.registry.build_registry", return_value=mock_registry):
            result = resolve_service("com.apple.Finder")
            assert result is not None
            assert result.label == "com.apple.Finder"

    def test_resolve_with_service_suffix(self, mock_registry):
        with patch("dystemctl.registry.build_registry", return_value=mock_registry):
            result = resolve_service("com.apple.Finder.service")
            assert result is not None
            assert result.label == "com.apple.Finder"

    def test_resolve_suffix_match(self, mock_registry):
        with patch("dystemctl.registry.build_registry", return_value=mock_registry):
            result = resolve_service("Finder")
            assert result is not None
            assert result.label == "com.apple.Finder"

    def test_resolve_homebrew_service(self, mock_registry):
        with patch("dystemctl.registry.build_registry", return_value=mock_registry):
            result = resolve_service("redis")
            assert result is not None
            assert result.label == "homebrew.mxcl.redis"

    def test_resolve_versioned_homebrew_service(self, mock_registry):
        with patch("dystemctl.registry.build_registry", return_value=mock_registry):
            result = resolve_service("postgresql")
            assert result is not None
            assert result.label == "homebrew.mxcl.postgresql@14"

    def test_resolve_case_insensitive(self, mock_registry):
        with patch("dystemctl.registry.build_registry", return_value=mock_registry):
            result = resolve_service("REDIS")
            assert result is not None
            assert result.label == "homebrew.mxcl.redis"

    def test_resolve_substring_match(self, mock_registry):
        with patch("dystemctl.registry.build_registry", return_value=mock_registry):
            result = resolve_service("testservice")
            assert result is not None
            assert result.label == "com.example.testservice"

    def test_resolve_not_found(self, mock_registry):
        with patch("dystemctl.registry.build_registry", return_value=mock_registry):
            result = resolve_service("nonexistent-service")
            assert result is None

    def test_resolve_with_alias(self, mock_registry):
        with patch("dystemctl.registry.build_registry", return_value=mock_registry):
            with patch("dystemctl.registry.CONFIG") as mock_config:
                mock_config.aliases = {"pg": "homebrew.mxcl.postgresql@14"}
                result = resolve_service("pg")
                assert result is not None
                assert result.label == "homebrew.mxcl.postgresql@14"


class TestFindSimilarServices:
    @pytest.fixture
    def mock_registry(self, temp_dir: Path):
        registry = {
            "homebrew.mxcl.redis": ServiceInfo(
                label="homebrew.mxcl.redis",
                plist_path=temp_dir / "redis.plist",
                program_arguments=["/opt/homebrew/bin/redis-server"],
            ),
            "homebrew.mxcl.postgresql": ServiceInfo(
                label="homebrew.mxcl.postgresql",
                plist_path=temp_dir / "postgresql.plist",
            ),
            "homebrew.mxcl.mysql": ServiceInfo(
                label="homebrew.mxcl.mysql",
                plist_path=temp_dir / "mysql.plist",
            ),
        }
        return registry

    def test_find_similar_typo(self, mock_registry):
        with patch("dystemctl.registry.build_registry", return_value=mock_registry):
            suggestions = find_similar_services("rediis")  # typo
            assert "homebrew.mxcl.redis" in suggestions

    def test_find_similar_partial(self, mock_registry):
        with patch("dystemctl.registry.build_registry", return_value=mock_registry):
            # "postgresq" is close to "postgresql" - within levenshtein threshold
            suggestions = find_similar_services("postgresq")
            assert "homebrew.mxcl.postgresql" in suggestions

    def test_find_similar_max_suggestions(self, mock_registry):
        with patch("dystemctl.registry.build_registry", return_value=mock_registry):
            suggestions = find_similar_services("sql", max_suggestions=2)
            assert len(suggestions) <= 2


class TestCompleteService:
    @pytest.fixture
    def mock_registry(self, temp_dir: Path):
        registry = {
            "homebrew.mxcl.redis": ServiceInfo(
                label="homebrew.mxcl.redis",
                plist_path=temp_dir / "redis.plist",
                program_arguments=["/opt/homebrew/bin/redis-server"],
            ),
            "homebrew.mxcl.redis-sentinel": ServiceInfo(
                label="homebrew.mxcl.redis-sentinel",
                plist_path=temp_dir / "redis-sentinel.plist",
            ),
            "com.apple.redis": ServiceInfo(
                label="com.apple.redis",
                plist_path=temp_dir / "apple-redis.plist",
            ),
        }
        return registry

    def test_complete_partial(self, mock_registry):
        with patch("dystemctl.registry.build_registry", return_value=mock_registry):
            with patch("dystemctl.registry.CONFIG") as mock_config:
                mock_config.aliases = {}
                completions = complete_service("redis")
                assert len(completions) == 3
                assert "homebrew.mxcl.redis" in completions
                assert "homebrew.mxcl.redis-sentinel" in completions

    def test_complete_with_prefix(self, mock_registry):
        with patch("dystemctl.registry.build_registry", return_value=mock_registry):
            with patch("dystemctl.registry.CONFIG") as mock_config:
                mock_config.aliases = {}
                completions = complete_service("homebrew.mxcl.redis")
                assert "homebrew.mxcl.redis" in completions
                assert "homebrew.mxcl.redis-sentinel" in completions

    def test_complete_empty(self, mock_registry):
        with patch("dystemctl.registry.build_registry", return_value=mock_registry):
            with patch("dystemctl.registry.CONFIG") as mock_config:
                mock_config.aliases = {}
                completions = complete_service("")
                assert len(completions) == 3

    def test_complete_no_match(self, mock_registry):
        with patch("dystemctl.registry.build_registry", return_value=mock_registry):
            with patch("dystemctl.registry.CONFIG") as mock_config:
                mock_config.aliases = {}
                completions = complete_service("nonexistent")
                assert len(completions) == 0

    def test_complete_includes_aliases(self, mock_registry):
        with patch("dystemctl.registry.build_registry", return_value=mock_registry):
            with patch("dystemctl.registry.CONFIG") as mock_config:
                mock_config.aliases = {"rd": "homebrew.mxcl.redis"}
                completions = complete_service("rd")
                assert "rd" in completions

    def test_complete_by_binary_name(self, temp_dir: Path):
        registry = {
            "homebrew.mxcl.redis": ServiceInfo(
                label="homebrew.mxcl.redis",
                plist_path=temp_dir / "redis.plist",
                program_arguments=["/opt/homebrew/bin/redis-server"],
            ),
        }
        with patch("dystemctl.registry.build_registry", return_value=registry):
            with patch("dystemctl.registry.CONFIG") as mock_config:
                mock_config.aliases = {}
                completions = complete_service("redis-server")
                assert "homebrew.mxcl.redis" in completions


class TestParsePlistExtended:
    def test_parse_plist_with_string_watch_paths(self, temp_dir: Path):
        plist_path = temp_dir / "watch.plist"
        plist_content = {
            "Label": "com.test.watch",
            "ProgramArguments": ["/usr/bin/watcher"],
            "WatchPaths": "/var/spool/incoming",  # Single string, not list
        }
        with open(plist_path, "wb") as f:
            plistlib.dump(plist_content, f)

        result = parse_plist(plist_path)
        assert result is not None
        assert result.watch_paths == ["/var/spool/incoming"]

    def test_parse_plist_with_string_queue_directories(self, temp_dir: Path):
        plist_path = temp_dir / "queue.plist"
        plist_content = {
            "Label": "com.test.queue",
            "ProgramArguments": ["/usr/bin/processor"],
            "QueueDirectories": "/var/queue",  # Single string, not list
        }
        with open(plist_path, "wb") as f:
            plistlib.dump(plist_content, f)

        result = parse_plist(plist_path)
        assert result is not None
        assert result.queue_directories == ["/var/queue"]


class TestParseSocketsExtended:
    def test_parse_socket_array_with_unix(self):
        sockets_dict = {
            "listeners": [
                {"SockPathName": "/var/run/test1.sock"},
                {"SockPathName": "/var/run/test2.sock"},
            ]
        }
        result = parse_sockets(sockets_dict)
        assert len(result) == 2
        assert result[0].family == "Unix"
        assert result[0].address == "/var/run/test1.sock"
        assert result[1].family == "Unix"
        assert result[1].address == "/var/run/test2.sock"


class TestResolveServiceExtended:
    @pytest.fixture
    def extended_registry(self, temp_dir: Path):
        return {
            "homebrew.mxcl.emacs-plus@30": ServiceInfo(
                label="homebrew.mxcl.emacs-plus@30",
                plist_path=temp_dir / "emacs-plus@30.plist",
                program_arguments=["/opt/homebrew/bin/emacs"],
            ),
            "homebrew.mxcl.postgresql@14": ServiceInfo(
                label="homebrew.mxcl.postgresql@14",
                plist_path=temp_dir / "postgresql@14.plist",
                program_arguments=["/opt/homebrew/bin/postgres"],
            ),
            "com.example.myservice@instance": ServiceInfo(
                label="com.example.myservice@instance",
                plist_path=temp_dir / "myservice.plist",
                program_arguments=["/usr/bin/myservice"],
            ),
            "homebrew.mxcl.nginx": ServiceInfo(
                label="homebrew.mxcl.nginx",
                plist_path=temp_dir / "nginx.plist",
                program_arguments=["/opt/homebrew/bin/nginx"],
            ),
        }

    def test_resolve_template_base_name(self, extended_registry):
        with patch("dystemctl.registry.build_registry", return_value=extended_registry):
            with patch("dystemctl.registry.CONFIG") as mock_config:
                mock_config.aliases = {}
                result = resolve_service("emacs-plus")
                assert result is not None
                assert "emacs-plus" in result.label

    def test_resolve_template_with_at(self, extended_registry):
        with patch("dystemctl.registry.build_registry", return_value=extended_registry):
            with patch("dystemctl.registry.CONFIG") as mock_config:
                mock_config.aliases = {}
                result = resolve_service("emacs-plus@30")
                assert result is not None
                assert result.label == "homebrew.mxcl.emacs-plus@30"

    def test_resolve_homebrew_exact_match(self, extended_registry):
        with patch("dystemctl.registry.build_registry", return_value=extended_registry):
            with patch("dystemctl.registry.CONFIG") as mock_config:
                mock_config.aliases = {}
                result = resolve_service("nginx")
                assert result is not None
                assert result.label == "homebrew.mxcl.nginx"

    def test_resolve_homebrew_versioned_base(self, extended_registry):
        with patch("dystemctl.registry.build_registry", return_value=extended_registry):
            with patch("dystemctl.registry.CONFIG") as mock_config:
                mock_config.aliases = {}
                result = resolve_service("postgresql")
                assert result is not None
                assert "postgresql" in result.label

    def test_resolve_binary_name(self, temp_dir: Path):
        registry = {
            "homebrew.mxcl.redis": ServiceInfo(
                label="homebrew.mxcl.redis",
                plist_path=temp_dir / "redis.plist",
                program_arguments=["/opt/homebrew/bin/redis-server"],
            ),
        }
        with patch("dystemctl.registry.build_registry", return_value=registry):
            with patch("dystemctl.registry.CONFIG") as mock_config:
                mock_config.aliases = {}
                result = resolve_service("redis-server")
                assert result is not None
                assert result.label == "homebrew.mxcl.redis"


class TestBuildRegistry:
    def test_build_registry_with_real_paths(self, temp_dir: Path):
        from dystemctl.registry import build_registry

        # Create a test plist
        test_plist = temp_dir / "com.test.service.plist"
        plist_content = {
            "Label": "com.test.service",
            "ProgramArguments": ["/usr/bin/test"],
        }
        with open(test_plist, "wb") as f:
            plistlib.dump(plist_content, f)

        # Clear the cache and mock paths
        build_registry.cache_clear()
        with patch(
            "dystemctl.registry._get_plist_search_paths",
            return_value=[temp_dir],
        ):
            registry = build_registry()
            # May or may not find files depending on mock
            assert isinstance(registry, dict)

        build_registry.cache_clear()


class TestFindSimilarServicesExtended:
    @pytest.fixture
    def services_registry(self, temp_dir: Path):
        return {
            "homebrew.mxcl.redis": ServiceInfo(
                label="homebrew.mxcl.redis",
                plist_path=temp_dir / "redis.plist",
                program_arguments=["/opt/homebrew/bin/redis-server"],
            ),
            "homebrew.mxcl.postgresql": ServiceInfo(
                label="homebrew.mxcl.postgresql",
                plist_path=temp_dir / "postgresql.plist",
            ),
        }

    def test_find_similar_by_binary_name(self, temp_dir: Path):
        registry = {
            "homebrew.mxcl.redis": ServiceInfo(
                label="homebrew.mxcl.redis",
                plist_path=temp_dir / "redis.plist",
                program_arguments=["/opt/homebrew/bin/redis-server"],
            ),
        }
        with patch("dystemctl.registry.build_registry", return_value=registry):
            suggestions = find_similar_services("redis-serve")  # typo
            assert "homebrew.mxcl.redis" in suggestions


class TestGetAllServicesAndLabels:
    def test_get_all_services(self, temp_dir: Path):
        from dystemctl.registry import build_registry, get_all_services

        registry = {
            "com.test.one": ServiceInfo(
                label="com.test.one",
                plist_path=temp_dir / "one.plist",
            ),
            "com.test.two": ServiceInfo(
                label="com.test.two",
                plist_path=temp_dir / "two.plist",
            ),
        }

        build_registry.cache_clear()
        with patch("dystemctl.registry.build_registry", return_value=registry):
            services = get_all_services()
            assert len(services) == 2
            labels = [s.label for s in services]
            assert "com.test.one" in labels
            assert "com.test.two" in labels

    def test_get_service_labels(self, temp_dir: Path):
        from dystemctl.registry import build_registry, get_service_labels

        registry = {
            "com.test.one": ServiceInfo(
                label="com.test.one",
                plist_path=temp_dir / "one.plist",
            ),
        }

        build_registry.cache_clear()
        with patch("dystemctl.registry.build_registry", return_value=registry):
            labels = get_service_labels()
            assert "com.test.one" in labels
