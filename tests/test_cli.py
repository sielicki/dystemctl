"""Tests for dystemctl.cli module."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from dystemctl.cli import app
from dystemctl.models import Domain, ServiceInfo, ServiceStatus

runner = CliRunner()


@pytest.fixture(autouse=True)
def reset_cli_state():
    """Reset CLI global state before each test."""
    from importlib import import_module

    app_module = import_module("dystemctl.cli.app")

    app_module.QUIET_MODE = False
    app_module.NO_LEGEND = False
    app_module.SCOPE = None
    app_module.console.quiet = False
    yield
    app_module.QUIET_MODE = False
    app_module.NO_LEGEND = False
    app_module.SCOPE = None
    app_module.console.quiet = False


@pytest.fixture
def mock_service_info(temp_dir: Path):
    return ServiceInfo(
        label="com.example.test",
        plist_path=temp_dir / "com.example.test.plist",
        program_arguments=["/usr/bin/test"],
        run_at_load=True,
        keep_alive=False,
    )


@pytest.fixture
def mock_running_status():
    return ServiceStatus(
        label="com.example.test",
        pid=1234,
        last_exit_status=None,
        loaded=True,
        domain=Domain.GUI,
    )


@pytest.fixture
def mock_stopped_status():
    return ServiceStatus(
        label="com.example.test",
        pid=None,
        last_exit_status=0,
        loaded=True,
        domain=Domain.GUI,
    )


class TestHelpCommand:
    def test_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "systemd emulation for Darwin" in result.stdout
        assert "start" in result.stdout
        assert "stop" in result.stdout
        assert "status" in result.stdout


class TestStartCommand:
    def test_start_success(self, mock_service_info):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch("dystemctl.cli.control.launchctl_start", return_value=True),
        ):
            result = runner.invoke(app, ["start", "test"])
            assert result.exit_code == 0
            assert "Started" in result.stdout

    def test_start_failure(self, mock_service_info):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch("dystemctl.cli.control.launchctl_start", return_value=False),
        ):
            result = runner.invoke(app, ["start", "test"])
            assert result.exit_code == 1
            assert "Failed to start" in result.output

    def test_start_not_found(self):
        with patch("dystemctl.cli.control.resolve_service", return_value=None):
            with patch("dystemctl.cli.app.find_similar_services", return_value=[]):
                result = runner.invoke(app, ["start", "nonexistent"])
                assert result.exit_code == 1
                assert "not found" in result.output

    def test_start_multiple_services(self, mock_service_info):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch("dystemctl.cli.control.launchctl_start", return_value=True),
        ):
            result = runner.invoke(app, ["start", "svc1", "svc2"])
            assert result.exit_code == 0
            assert result.stdout.count("Started") == 2


class TestStopCommand:
    def test_stop_success(self, mock_service_info):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch("dystemctl.cli.control.launchctl_stop", return_value=True),
        ):
            result = runner.invoke(app, ["stop", "test"])
            assert result.exit_code == 0
            assert "Stopped" in result.stdout

    def test_stop_failure(self, mock_service_info):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch("dystemctl.cli.control.launchctl_stop", return_value=False),
        ):
            result = runner.invoke(app, ["stop", "test"])
            assert result.exit_code == 1


class TestRestartCommand:
    def test_restart_success(self, mock_service_info):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch("dystemctl.cli.control.launchctl_stop", return_value=True),
        ):
            with patch("dystemctl.cli.control.launchctl_start", return_value=True):
                result = runner.invoke(app, ["restart", "test"])
                assert result.exit_code == 0
                assert "Restarted" in result.stdout


class TestEnableCommand:
    def test_enable_success(self, mock_service_info):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch("dystemctl.cli.control.launchctl_enable", return_value=True),
        ):
            result = runner.invoke(app, ["enable", "test"])
            assert result.exit_code == 0
            assert "Enabled" in result.stdout

    def test_enable_with_now(self, mock_service_info):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch("dystemctl.cli.control.launchctl_enable", return_value=True),
        ):
            with patch("dystemctl.cli.control.launchctl_start", return_value=True):
                result = runner.invoke(app, ["enable", "--now", "test"])
                assert result.exit_code == 0
                assert "Enabled" in result.stdout
                assert "Started" in result.stdout


class TestDisableCommand:
    def test_disable_success(self, mock_service_info):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch("dystemctl.cli.control.launchctl_disable", return_value=True),
        ):
            result = runner.invoke(app, ["disable", "test"])
            assert result.exit_code == 0
            assert "Disabled" in result.stdout

    def test_disable_with_now(self, mock_service_info):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch("dystemctl.cli.control.launchctl_stop", return_value=True),
            patch("dystemctl.cli.control.launchctl_disable", return_value=True),
        ):
            result = runner.invoke(app, ["disable", "--now", "test"])
            assert result.exit_code == 0
            assert "Stopped" in result.stdout
            assert "Disabled" in result.stdout


class TestStatusCommand:
    def test_status_running(self, mock_service_info, mock_running_status):
        mock_process_info = MagicMock()
        mock_process_info.rss_bytes = 104857600
        mock_process_info.elapsed = timedelta(hours=1)
        mock_process_info.cpu_percent = 0.5

        with (
            patch("dystemctl.cli.info.resolve_service", return_value=mock_service_info),
            patch(
                "dystemctl.cli.info.get_service_status",
                return_value=mock_running_status,
            ),
            patch(
                "dystemctl.cli.info.get_process_info",
                return_value=mock_process_info,
            ),
        ):
            result = runner.invoke(app, ["status", "test"])
            assert result.exit_code == 0
            assert "com.example.test" in result.stdout
            assert (
                "active" in result.stdout.lower() or "running" in result.stdout.lower()
            )

    def test_status_stopped(self, mock_service_info, mock_stopped_status):
        with (
            patch("dystemctl.cli.info.resolve_service", return_value=mock_service_info),
            patch(
                "dystemctl.cli.info.get_service_status",
                return_value=mock_stopped_status,
            ),
            patch("dystemctl.cli.info.get_process_info", return_value=None),
        ):
            result = runner.invoke(app, ["status", "test"])
            assert result.exit_code == 0
            assert "inactive" in result.stdout.lower()

    def test_status_not_found(self):
        with patch("dystemctl.cli.info.resolve_service", return_value=None):
            with patch("dystemctl.cli.app.find_similar_services", return_value=[]):
                result = runner.invoke(app, ["status", "nonexistent"])
                assert result.exit_code == 1


class TestIsActiveCommand:
    def test_is_active_true(self, mock_service_info, mock_running_status):
        with (
            patch("dystemctl.cli.info.resolve_service", return_value=mock_service_info),
            patch(
                "dystemctl.cli.info.get_service_status",
                return_value=mock_running_status,
            ),
        ):
            result = runner.invoke(app, ["is-active", "test"])
            assert result.exit_code == 0
            assert "active" in result.stdout

    def test_is_active_false(self, mock_service_info, mock_stopped_status):
        with (
            patch("dystemctl.cli.info.resolve_service", return_value=mock_service_info),
            patch(
                "dystemctl.cli.info.get_service_status",
                return_value=mock_stopped_status,
            ),
        ):
            result = runner.invoke(app, ["is-active", "test"])
            assert result.exit_code == 3
            assert "inactive" in result.stdout

    def test_is_active_unknown(self):
        with patch("dystemctl.cli.info.resolve_service", return_value=None):
            result = runner.invoke(app, ["is-active", "nonexistent"])
            assert result.exit_code == 4
            assert "inactive" in result.stdout


class TestIsEnabledCommand:
    def test_is_enabled_loaded(self, mock_service_info, mock_running_status):
        with (
            patch("dystemctl.cli.info.resolve_service", return_value=mock_service_info),
            patch(
                "dystemctl.cli.info.get_service_status",
                return_value=mock_running_status,
            ),
        ):
            result = runner.invoke(app, ["is-enabled", "test"])
            assert result.exit_code == 0
            assert "enabled" in result.stdout

    def test_is_enabled_run_at_load(self, mock_service_info, mock_stopped_status):
        mock_stopped_status.loaded = False
        mock_service_info.run_at_load = True
        with (
            patch("dystemctl.cli.info.resolve_service", return_value=mock_service_info),
            patch(
                "dystemctl.cli.info.get_service_status",
                return_value=mock_stopped_status,
            ),
        ):
            result = runner.invoke(app, ["is-enabled", "test"])
            assert result.exit_code == 0
            assert "enabled" in result.stdout


class TestCatCommand:
    def test_cat_service(self, mock_service_info, temp_dir: Path):
        plist_path = temp_dir / "com.example.test.plist"
        plist_content = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.example.test</string>
    <key>TestKey</key>
    <string>test content</string>
</dict>
</plist>"""
        plist_path.write_text(plist_content)
        mock_service_info.plist_path = plist_path

        with patch(
            "dystemctl.cli.info.resolve_service", return_value=mock_service_info
        ):
            result = runner.invoke(app, ["cat", "test"])
            assert result.exit_code == 0
            assert "test content" in result.stdout


class TestShowCommand:
    def test_show_all_properties(self, mock_service_info, mock_running_status):
        mock_process_info = MagicMock()
        mock_process_info.rss_bytes = 104857600
        mock_process_info.cpu_percent = 5.0

        with (
            patch("dystemctl.cli.info.resolve_service", return_value=mock_service_info),
            patch(
                "dystemctl.cli.info.get_service_status",
                return_value=mock_running_status,
            ),
            patch(
                "dystemctl.cli.info.get_process_info",
                return_value=mock_process_info,
            ),
        ):
            result = runner.invoke(app, ["show", "test"])
            assert result.exit_code == 0
            assert "Id=" in result.stdout
            assert "MainPID=" in result.stdout

    def test_show_specific_property(self, mock_service_info, mock_running_status):
        with (
            patch("dystemctl.cli.info.resolve_service", return_value=mock_service_info),
            patch(
                "dystemctl.cli.info.get_service_status",
                return_value=mock_running_status,
            ),
            patch("dystemctl.cli.info.get_process_info", return_value=None),
        ):
            result = runner.invoke(app, ["show", "-p", "MainPID", "test"])
            assert result.exit_code == 0
            assert "MainPID=" in result.stdout


class TestDaemonReloadCommand:
    def test_daemon_reload(self):
        with patch("dystemctl.cli.info.build_registry") as mock_build:
            mock_build.cache_clear = MagicMock()
            result = runner.invoke(app, ["daemon-reload"])
            assert result.exit_code == 0
            assert "reloaded" in result.stdout.lower()


class TestResolveCommand:
    def test_resolve_found(self, mock_service_info):
        with patch(
            "dystemctl.cli.units.resolve_service", return_value=mock_service_info
        ):
            result = runner.invoke(app, ["resolve", "test"])
            assert result.exit_code == 0
            assert "com.example.test" in result.stdout

    def test_resolve_not_found(self):
        with patch("dystemctl.cli.units.resolve_service", return_value=None):
            result = runner.invoke(app, ["resolve", "nonexistent"])
            assert result.exit_code == 1
            assert "No match found" in result.output


class TestListUnitsCommand:
    def test_list_units_basic(self, mock_service_info, mock_running_status):
        with patch("dystemctl.cli.info.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {"com.example.test": (1234, 0)}
            with (
                patch(
                    "dystemctl.cli.info.get_all_services",
                    return_value=[mock_service_info],
                ),
                patch(
                    "dystemctl.cli.info.get_service_status",
                    return_value=mock_running_status,
                ),
                patch("dystemctl.cli.info.filter_by_scope", side_effect=lambda x: x),
            ):
                result = runner.invoke(app, ["list-units"])
                assert result.exit_code == 0
                assert "UNIT" in result.stdout
                assert "LOAD" in result.stdout

    def test_list_units_json(self, mock_service_info, mock_running_status):
        with patch("dystemctl.cli.info.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {"com.example.test": (1234, 0)}
            with (
                patch(
                    "dystemctl.cli.info.get_all_services",
                    return_value=[mock_service_info],
                ),
                patch(
                    "dystemctl.cli.info.get_service_status",
                    return_value=mock_running_status,
                ),
                patch("dystemctl.cli.info.filter_by_scope", side_effect=lambda x: x),
            ):
                result = runner.invoke(app, ["list-units", "-o", "json"])
                assert result.exit_code == 0
                assert "[" in result.stdout  # JSON array


class TestLogsCommand:
    def test_logs_with_unit(self, mock_service_info):
        with (
            patch(
                "dystemctl.cli.journal.resolve_service", return_value=mock_service_info
            ),
            patch("dystemctl.cli.info.tail_log_file", return_value=["line1", "line2"]),
            patch("dystemctl.cli.info.query_os_log", return_value=[]),
        ):
            result = runner.invoke(app, ["logs", "-u", "test", "-n", "5"])
            # Just verify it doesn't crash
            assert result.exit_code == 0

    def test_logs_not_found(self):
        with patch("dystemctl.cli.journal.resolve_service", return_value=None):
            with patch("dystemctl.cli.app.find_similar_services", return_value=[]):
                result = runner.invoke(app, ["logs", "-u", "nonexistent"])
                assert result.exit_code == 1


class TestImportCommand:
    def test_import_dry_run(self, sample_systemd_unit: Path):
        result = runner.invoke(app, ["import", "--dry-run", str(sample_systemd_unit)])
        assert result.exit_code == 0
        assert "Would write to" in result.stdout

    def test_import_file_not_found(self, temp_dir: Path):
        result = runner.invoke(app, ["import", str(temp_dir / "nonexistent.service")])
        assert result.exit_code == 1
        assert "File not found" in result.output


class TestExportCommand:
    def test_export_dry_run(self, mock_service_info):
        with patch(
            "dystemctl.cli.units.resolve_service", return_value=mock_service_info
        ):
            result = runner.invoke(app, ["export", "--dry-run", "test"])
            assert result.exit_code == 0
            assert "[Unit]" in result.stdout
            assert "[Service]" in result.stdout

    def test_export_not_found(self):
        with patch("dystemctl.cli.units.resolve_service", return_value=None):
            with patch("dystemctl.cli.app.find_similar_services", return_value=[]):
                result = runner.invoke(app, ["export", "nonexistent"])
                assert result.exit_code == 1


class TestGlobalOptions:
    def test_quiet_option(self, mock_service_info):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch("dystemctl.cli.control.launchctl_start", return_value=True),
        ):
            result = runner.invoke(app, ["--quiet", "start", "test"])
            assert result.exit_code == 0

    def test_user_option(self, mock_service_info, mock_running_status):
        with patch("dystemctl.cli.control.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {}
            with (
                patch(
                    "dystemctl.cli.get_all_services", return_value=[mock_service_info]
                ),
                patch(
                    "dystemctl.cli.control.get_service_status",
                    return_value=mock_running_status,
                ),
            ):
                result = runner.invoke(app, ["--user", "list-units"])
                assert result.exit_code == 0

    def test_system_option(self, mock_service_info, mock_running_status):
        with patch("dystemctl.cli.control.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {}
            with (
                patch(
                    "dystemctl.cli.get_all_services", return_value=[mock_service_info]
                ),
                patch(
                    "dystemctl.cli.control.get_service_status",
                    return_value=mock_running_status,
                ),
            ):
                result = runner.invoke(app, ["--system", "list-units"])
                assert result.exit_code == 0


class TestEnvironmentCommands:
    def test_show_environment(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "/usr/bin:/bin"

        with patch("subprocess.run", return_value=mock_result):
            result = runner.invoke(app, ["show-environment"])
            assert result.exit_code == 0

    def test_set_environment(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            result = runner.invoke(app, ["set-environment", "FOO=bar"])
            assert result.exit_code == 0

    def test_set_environment_invalid(self):
        # Invalid format just prints an error but doesn't fail the command
        result = runner.invoke(app, ["set-environment", "INVALID"])
        assert result.exit_code == 0

    def test_unset_environment(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            result = runner.invoke(app, ["unset-environment", "FOO"])
            assert result.exit_code == 0


class TestReloadCommand:
    def test_reload_success(self, mock_service_info, mock_running_status):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch(
                "dystemctl.cli.control.get_service_status",
                return_value=mock_running_status,
            ),
            patch("os.kill") as mock_kill,
        ):
            result = runner.invoke(app, ["reload", "test"])
            assert result.exit_code == 0
            assert "Reloaded" in result.stdout
            mock_kill.assert_called_once()

    def test_reload_not_running(self, mock_service_info, mock_stopped_status):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch(
                "dystemctl.cli.control.get_service_status",
                return_value=mock_stopped_status,
            ),
        ):
            result = runner.invoke(app, ["reload", "test"])
            assert result.exit_code == 1
            assert "Not running" in result.output

    def test_reload_not_found(self):
        with patch("dystemctl.cli.control.resolve_service", return_value=None):
            with patch("dystemctl.cli.app.find_similar_services", return_value=[]):
                result = runner.invoke(app, ["reload", "nonexistent"])
                assert result.exit_code == 1
                assert "not found" in result.output

    def test_reload_process_not_found(self, mock_service_info, mock_running_status):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch(
                "dystemctl.cli.control.get_service_status",
                return_value=mock_running_status,
            ),
            patch("os.kill", side_effect=ProcessLookupError()),
        ):
            result = runner.invoke(app, ["reload", "test"])
            assert result.exit_code == 1
            assert "Process not found" in result.output

    def test_reload_permission_denied(self, mock_service_info, mock_running_status):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch(
                "dystemctl.cli.control.get_service_status",
                return_value=mock_running_status,
            ),
            patch("os.kill", side_effect=PermissionError()),
        ):
            result = runner.invoke(app, ["reload", "test"])
            assert result.exit_code == 1
            assert "Permission denied" in result.output


class TestKillCommand:
    def test_kill_default_sigterm(self, mock_service_info, mock_running_status):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch(
                "dystemctl.cli.control.get_service_status",
                return_value=mock_running_status,
            ),
            patch("os.kill") as mock_kill,
        ):
            result = runner.invoke(app, ["kill", "test"])
            assert result.exit_code == 0
            assert "Sent SIGTERM" in result.stdout
            mock_kill.assert_called_once()

    def test_kill_sigkill(self, mock_service_info, mock_running_status):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch(
                "dystemctl.cli.control.get_service_status",
                return_value=mock_running_status,
            ),
            patch("os.kill"),
        ):
            result = runner.invoke(app, ["kill", "-s", "SIGKILL", "test"])
            assert result.exit_code == 0
            assert "Sent SIGKILL" in result.stdout

    def test_kill_sighup(self, mock_service_info, mock_running_status):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch(
                "dystemctl.cli.control.get_service_status",
                return_value=mock_running_status,
            ),
            patch("os.kill"),
        ):
            result = runner.invoke(app, ["kill", "-s", "SIGHUP", "test"])
            assert result.exit_code == 0
            assert "Sent SIGHUP" in result.stdout

    def test_kill_not_running(self, mock_service_info, mock_stopped_status):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch(
                "dystemctl.cli.control.get_service_status",
                return_value=mock_stopped_status,
            ),
        ):
            result = runner.invoke(app, ["kill", "test"])
            assert result.exit_code == 1
            assert "Not running" in result.output

    def test_kill_not_found(self):
        with patch("dystemctl.cli.control.resolve_service", return_value=None):
            with patch("dystemctl.cli.app.find_similar_services", return_value=[]):
                result = runner.invoke(app, ["kill", "nonexistent"])
                assert result.exit_code == 1

    def test_kill_process_lookup_error(self, mock_service_info, mock_running_status):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch(
                "dystemctl.cli.control.get_service_status",
                return_value=mock_running_status,
            ),
            patch("os.kill", side_effect=ProcessLookupError()),
        ):
            result = runner.invoke(app, ["kill", "test"])
            assert result.exit_code == 1
            assert "Process not found" in result.output

    def test_kill_permission_error(self, mock_service_info, mock_running_status):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch(
                "dystemctl.cli.control.get_service_status",
                return_value=mock_running_status,
            ),
            patch("os.kill", side_effect=PermissionError()),
        ):
            result = runner.invoke(app, ["kill", "test"])
            assert result.exit_code == 1
            assert "Permission denied" in result.output


class TestTryRestartCommand:
    def test_try_restart_running(self, mock_service_info, mock_running_status):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch(
                "dystemctl.cli.control.get_service_status",
                return_value=mock_running_status,
            ),
            patch("dystemctl.cli.control.launchctl_stop", return_value=True),
            patch("dystemctl.cli.control.launchctl_start", return_value=True),
        ):
            result = runner.invoke(app, ["try-restart", "test"])
            assert result.exit_code == 0
            assert "Restarted" in result.stdout

    def test_try_restart_not_running(self, mock_service_info, mock_stopped_status):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch(
                "dystemctl.cli.control.get_service_status",
                return_value=mock_stopped_status,
            ),
        ):
            result = runner.invoke(app, ["try-restart", "test"])
            assert result.exit_code == 0
            assert "Skipped" in result.stdout

    def test_try_restart_not_found(self):
        with patch("dystemctl.cli.control.resolve_service", return_value=None):
            with patch("dystemctl.cli.app.find_similar_services", return_value=[]):
                result = runner.invoke(app, ["try-restart", "nonexistent"])
                assert result.exit_code == 1

    def test_try_restart_failure(self, mock_service_info, mock_running_status):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch(
                "dystemctl.cli.control.get_service_status",
                return_value=mock_running_status,
            ),
            patch("dystemctl.cli.control.launchctl_stop", return_value=True),
            patch("dystemctl.cli.control.launchctl_start", return_value=False),
        ):
            result = runner.invoke(app, ["try-restart", "test"])
            assert result.exit_code == 1
            assert "Failed to restart" in result.output


class TestReloadOrRestartCommand:
    def test_reload_or_restart_reload_success(
        self, mock_service_info, mock_running_status
    ):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch(
                "dystemctl.cli.control.get_service_status",
                return_value=mock_running_status,
            ),
            patch("os.kill"),
        ):
            result = runner.invoke(app, ["reload-or-restart", "test"])
            assert result.exit_code == 0
            assert "Reloaded" in result.stdout

    def test_reload_or_restart_fallback_restart(
        self, mock_service_info, mock_running_status
    ):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch(
                "dystemctl.cli.control.get_service_status",
                return_value=mock_running_status,
            ),
            patch("os.kill", side_effect=ProcessLookupError()),
            patch("dystemctl.cli.control.launchctl_stop", return_value=True),
            patch("dystemctl.cli.control.launchctl_start", return_value=True),
        ):
            result = runner.invoke(app, ["reload-or-restart", "test"])
            assert result.exit_code == 0
            assert "Restarted" in result.stdout

    def test_reload_or_restart_start_when_not_running(
        self, mock_service_info, mock_stopped_status
    ):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch(
                "dystemctl.cli.control.get_service_status",
                return_value=mock_stopped_status,
            ),
            patch("dystemctl.cli.control.launchctl_start", return_value=True),
        ):
            result = runner.invoke(app, ["reload-or-restart", "test"])
            assert result.exit_code == 0
            assert "Started" in result.stdout

    def test_reload_or_restart_not_found(self):
        with patch("dystemctl.cli.control.resolve_service", return_value=None):
            with patch("dystemctl.cli.app.find_similar_services", return_value=[]):
                result = runner.invoke(app, ["reload-or-restart", "nonexistent"])
                assert result.exit_code == 1

    def test_reload_or_restart_start_failure(
        self, mock_service_info, mock_stopped_status
    ):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch(
                "dystemctl.cli.control.get_service_status",
                return_value=mock_stopped_status,
            ),
            patch("dystemctl.cli.control.launchctl_start", return_value=False),
        ):
            result = runner.invoke(app, ["reload-or-restart", "test"])
            assert result.exit_code == 1
            assert "Failed to start" in result.output

    def test_reload_or_restart_restart_failure(
        self, mock_service_info, mock_running_status
    ):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch(
                "dystemctl.cli.control.get_service_status",
                return_value=mock_running_status,
            ),
            patch("os.kill", side_effect=PermissionError()),
            patch("dystemctl.cli.control.launchctl_stop", return_value=True),
            patch("dystemctl.cli.control.launchctl_start", return_value=False),
        ):
            result = runner.invoke(app, ["reload-or-restart", "test"])
            assert result.exit_code == 1
            assert "Failed to restart" in result.output


class TestMaskCommand:
    def test_mask_success(self, mock_service_info):
        mock_result = MagicMock()
        mock_result.returncode = 0

        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch("dystemctl.cli.control.launchctl_disable", return_value=True),
        ):
            with patch("subprocess.run", return_value=mock_result):
                result = runner.invoke(app, ["mask", "test"])
                assert result.exit_code == 0
                assert "Masked" in result.stdout

    def test_mask_with_now(self, mock_service_info):
        mock_result = MagicMock()
        mock_result.returncode = 0

        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch("dystemctl.cli.control.launchctl_stop", return_value=True),
            patch("dystemctl.cli.control.launchctl_disable", return_value=True),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = runner.invoke(app, ["mask", "--now", "test"])
            assert result.exit_code == 0
            assert "Stopped" in result.stdout
            assert "Masked" in result.stdout

    def test_mask_not_found(self):
        with patch("dystemctl.cli.control.resolve_service", return_value=None):
            with patch("dystemctl.cli.app.find_similar_services", return_value=[]):
                result = runner.invoke(app, ["mask", "nonexistent"])
                assert result.exit_code == 1

    def test_mask_fallback_to_user_domain(self, mock_service_info):
        mock_gui_fail = MagicMock()
        mock_gui_fail.returncode = 1
        mock_user_ok = MagicMock()
        mock_user_ok.returncode = 0

        def mock_run(args, **kwargs):
            if "gui" in str(args):
                return mock_gui_fail
            return mock_user_ok

        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch("dystemctl.cli.control.launchctl_disable", return_value=True),
        ):
            with patch("subprocess.run", side_effect=mock_run):
                result = runner.invoke(app, ["mask", "test"])
                assert result.exit_code == 0
                assert "Masked" in result.stdout


class TestUnmaskCommand:
    def test_unmask_success(self, mock_service_info):
        mock_result = MagicMock()
        mock_result.returncode = 0

        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = runner.invoke(app, ["unmask", "test"])
            assert result.exit_code == 0
            assert "Unmasked" in result.stdout

    def test_unmask_not_found(self):
        with patch("dystemctl.cli.control.resolve_service", return_value=None):
            with patch("dystemctl.cli.app.find_similar_services", return_value=[]):
                result = runner.invoke(app, ["unmask", "nonexistent"])
                assert result.exit_code == 1


class TestResetFailedCommand:
    def test_reset_failed_specific_service(self, mock_service_info):
        mock_result = MagicMock()
        mock_result.returncode = 0

        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch("dystemctl.cli.control.detect_domain", return_value=Domain.GUI),
        ):
            with patch("subprocess.run", return_value=mock_result):
                result = runner.invoke(app, ["reset-failed", "test"])
                assert result.exit_code == 0
                assert "Reset" in result.stdout

    def test_reset_failed_all(self):
        with patch("dystemctl.cli.control.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {
                "com.example.failed": (None, 1),  # failed service
                "com.example.running": (1234, 0),  # running service
            }
            with patch("dystemctl.cli.control.detect_domain", return_value=Domain.GUI):
                with patch("subprocess.run", return_value=MagicMock(returncode=0)):
                    result = runner.invoke(app, ["reset-failed"])
                    assert result.exit_code == 0
                    assert "Reset 1 failed" in result.stdout

    def test_reset_failed_service_not_found(self):
        with patch("dystemctl.cli.control.resolve_service", return_value=None):
            with patch("dystemctl.cli.app.find_similar_services", return_value=[]):
                result = runner.invoke(app, ["reset-failed", "nonexistent"])
                assert result.exit_code == 0  # Continues with empty output


class TestCleanCommand:
    def test_clean_logs(self, mock_service_info, temp_dir: Path):
        log_file = temp_dir / "test.log"
        log_file.write_text("test log content")
        mock_service_info.standard_out_path = log_file

        with patch(
            "dystemctl.cli.info.resolve_service", return_value=mock_service_info
        ):
            result = runner.invoke(app, ["clean", "-w", "logs", "test"])
            assert result.exit_code == 0
            assert "Cleaned" in result.stdout
            assert not log_file.exists()

    def test_clean_invalid_what(self, mock_service_info):
        with patch(
            "dystemctl.cli.info.resolve_service", return_value=mock_service_info
        ):
            result = runner.invoke(app, ["clean", "-w", "invalid", "test"])
            assert result.exit_code == 1
            assert "Invalid --what" in result.output

    def test_clean_nothing_to_clean(self, mock_service_info):
        mock_service_info.standard_out_path = None
        mock_service_info.standard_error_path = None

        with patch(
            "dystemctl.cli.info.resolve_service", return_value=mock_service_info
        ):
            result = runner.invoke(app, ["clean", "test"])
            assert result.exit_code == 0
            assert "Nothing to clean" in result.stdout

    def test_clean_not_found(self):
        with patch("dystemctl.cli.info.resolve_service", return_value=None):
            with patch("dystemctl.cli.app.find_similar_services", return_value=[]):
                result = runner.invoke(app, ["clean", "nonexistent"])
                assert (
                    result.exit_code == 0
                )  # Command continues even if service not found


class TestListUnitFilesCommand:
    def test_list_unit_files(self, mock_service_info):
        mock_subprocess = MagicMock()
        mock_subprocess.returncode = 0
        mock_subprocess.stdout = ""

        with (
            patch(
                "dystemctl.cli.info.get_all_services", return_value=[mock_service_info]
            ),
            patch("dystemctl.cli.info.get_all_loaded_services") as mock_loaded,
        ):
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {}
            with (
                patch("dystemctl.cli.info.filter_by_scope", side_effect=lambda x: x),
                patch("subprocess.run", return_value=mock_subprocess),
            ):
                result = runner.invoke(app, ["list-unit-files"])
                assert result.exit_code == 0
                assert "UNIT FILE" in result.stdout
                assert "STATE" in result.stdout

    def test_list_unit_files_with_state_filter(self, mock_service_info):
        mock_subprocess = MagicMock()
        mock_subprocess.returncode = 0
        mock_subprocess.stdout = ""

        with (
            patch(
                "dystemctl.cli.info.get_all_services", return_value=[mock_service_info]
            ),
            patch("dystemctl.cli.info.get_all_loaded_services") as mock_loaded,
        ):
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {"com.example.test": (1234, 0)}
            with (
                patch("dystemctl.cli.info.filter_by_scope", side_effect=lambda x: x),
                patch("subprocess.run", return_value=mock_subprocess),
            ):
                result = runner.invoke(app, ["list-unit-files", "--state", "enabled"])
                assert result.exit_code == 0


class TestListTimersCommand:
    def test_list_timers(self, temp_dir: Path):
        timer_service = ServiceInfo(
            label="com.example.timer",
            plist_path=temp_dir / "timer.plist",
            program_arguments=["/usr/bin/periodic"],
            start_interval=3600,
        )

        with patch("dystemctl.cli.info.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {"com.example.timer": (None, 0)}
            with (
                patch(
                    "dystemctl.cli.info.get_all_services", return_value=[timer_service]
                ),
                patch(
                    "dystemctl.cli.info.get_service_status",
                    return_value=ServiceStatus(
                        label="com.example.timer",
                        pid=None,
                        last_exit_status=0,
                        loaded=True,
                        domain=Domain.GUI,
                    ),
                ),
                patch("dystemctl.cli.info.filter_by_scope", side_effect=lambda x: x),
            ):
                result = runner.invoke(app, ["list-timers"])
                assert result.exit_code == 0

    def test_list_timers_no_timers(self, mock_service_info):
        with patch("dystemctl.cli.info.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {}
            with (
                patch(
                    "dystemctl.cli.info.get_all_services",
                    return_value=[mock_service_info],
                ),
                patch("dystemctl.cli.info.filter_by_scope", side_effect=lambda x: x),
            ):
                result = runner.invoke(app, ["list-timers"])
                assert result.exit_code == 0
                assert "No timer services found" in result.stdout


class TestListSocketsCommand:
    def test_list_sockets(self, temp_dir: Path):
        from dystemctl.models import SocketInfo

        socket_service = ServiceInfo(
            label="com.example.socket",
            plist_path=temp_dir / "socket.plist",
            program_arguments=["/usr/bin/server"],
            sockets=[
                SocketInfo(
                    name="main", sock_type="stream", family="IPv4", address="*:8080"
                )
            ],
        )

        with patch("dystemctl.cli.info.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {"com.example.socket": (None, 0)}
            with (
                patch(
                    "dystemctl.cli.info.get_all_services", return_value=[socket_service]
                ),
                patch(
                    "dystemctl.cli.info.get_service_status",
                    return_value=ServiceStatus(
                        label="com.example.socket",
                        pid=None,
                        last_exit_status=0,
                        loaded=True,
                        domain=Domain.GUI,
                    ),
                ),
                patch("dystemctl.cli.info.filter_by_scope", side_effect=lambda x: x),
            ):
                result = runner.invoke(app, ["list-sockets"])
                assert result.exit_code == 0

    def test_list_sockets_no_sockets(self, mock_service_info):
        with patch("dystemctl.cli.info.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {}
            with (
                patch(
                    "dystemctl.cli.info.get_all_services",
                    return_value=[mock_service_info],
                ),
                patch("dystemctl.cli.info.filter_by_scope", side_effect=lambda x: x),
            ):
                result = runner.invoke(app, ["list-sockets"])
                assert result.exit_code == 0
                assert "No socket-activated services found" in result.stdout


class TestListDependenciesCommand:
    def test_list_dependencies(self, mock_service_info):
        mock_service_info.run_at_load = True
        mock_service_info.keep_alive = True

        with patch(
            "dystemctl.cli.info.resolve_service", return_value=mock_service_info
        ):
            result = runner.invoke(app, ["list-dependencies", "test"])
            assert result.exit_code == 0
            assert "Activation triggers" in result.stdout

    def test_list_dependencies_reverse(self, mock_service_info):
        mock_service_info.mach_services = ["com.example.test.service"]

        with patch(
            "dystemctl.cli.info.resolve_service", return_value=mock_service_info
        ):
            result = runner.invoke(app, ["list-dependencies", "--reverse", "test"])
            assert result.exit_code == 0
            assert "reverse dependencies" in result.stdout

    def test_list_dependencies_not_found(self):
        with patch("dystemctl.cli.info.resolve_service", return_value=None):
            with patch("dystemctl.cli.app.find_similar_services", return_value=[]):
                result = runner.invoke(app, ["list-dependencies", "nonexistent"])
                assert result.exit_code == 1


class TestListJobsCommand:
    def test_list_jobs(self, mock_service_info):
        with patch("dystemctl.cli.info.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {
                "com.example.test": (1234, 0),
            }
            with patch(
                "dystemctl.cli.info.build_registry",
                return_value={
                    "com.example.test": mock_service_info,
                },
            ):
                result = runner.invoke(app, ["list-jobs"])
                assert result.exit_code == 0
                assert "JOB" in result.stdout
                assert "UNIT" in result.stdout

    def test_list_jobs_no_jobs(self):
        with patch("dystemctl.cli.info.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {}
            result = runner.invoke(app, ["list-jobs"])
            assert result.exit_code == 0
            assert "No jobs running" in result.stdout


class TestIsFailedCommand:
    def test_is_failed_true(self, mock_service_info):
        failed_status = ServiceStatus(
            label="com.example.test",
            pid=None,
            last_exit_status=1,
            loaded=True,
            domain=Domain.GUI,
        )
        with (
            patch("dystemctl.cli.info.resolve_service", return_value=mock_service_info),
            patch("dystemctl.cli.info.get_service_status", return_value=failed_status),
        ):
            result = runner.invoke(app, ["is-failed", "test"])
            assert result.exit_code == 0
            assert "failed" in result.stdout

    def test_is_failed_false(self, mock_service_info, mock_running_status):
        with (
            patch("dystemctl.cli.info.resolve_service", return_value=mock_service_info),
            patch(
                "dystemctl.cli.info.get_service_status",
                return_value=mock_running_status,
            ),
        ):
            result = runner.invoke(app, ["is-failed", "test"])
            assert result.exit_code == 1
            assert "active" in result.stdout

    def test_is_failed_unknown(self):
        with patch("dystemctl.cli.info.resolve_service", return_value=None):
            result = runner.invoke(app, ["is-failed", "nonexistent"])
            assert result.exit_code == 4
            assert "inactive" in result.stdout


class TestIsSystemRunningCommand:
    def test_is_system_running_running(self):
        with patch("dystemctl.cli.info.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {
                "com.example.test": (1234, 0),  # running
            }
            result = runner.invoke(app, ["is-system-running"])
            assert result.exit_code == 0
            assert "running" in result.stdout

    def test_is_system_running_degraded(self):
        with patch("dystemctl.cli.info.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {
                "com.example.running": (1234, 0),
                "com.example.failed": (None, 1),  # failed
            }
            result = runner.invoke(app, ["is-system-running"])
            assert result.exit_code == 1
            assert "degraded" in result.stdout

    def test_is_system_running_offline(self):
        with patch("dystemctl.cli.info.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {}
            result = runner.invoke(app, ["is-system-running"])
            assert result.exit_code == 1
            assert "offline" in result.stdout


class TestEditCommand:
    def test_edit_success(self, mock_service_info, temp_dir: Path):
        plist_path = temp_dir / "Library" / "LaunchAgents" / "test.plist"
        plist_path.parent.mkdir(parents=True)
        plist_path.touch()
        mock_service_info.plist_path = plist_path

        with (
            patch("dystemctl.cli.info.resolve_service", return_value=mock_service_info),
            patch("subprocess.run") as mock_run,
        ):
            result = runner.invoke(app, ["edit", "test"])
            assert result.exit_code == 0
            mock_run.assert_called_once()

    def test_edit_system_plist(self, mock_service_info, temp_dir: Path):
        plist_path = temp_dir / "System" / "Library" / "LaunchDaemons" / "test.plist"
        plist_path.parent.mkdir(parents=True)
        plist_path.touch()
        mock_service_info.plist_path = plist_path

        with patch(
            "dystemctl.cli.info.resolve_service", return_value=mock_service_info
        ):
            result = runner.invoke(app, ["edit", "test"])
            assert result.exit_code == 1
            assert "System plists require root" in result.output

    def test_edit_not_found(self):
        with patch("dystemctl.cli.info.resolve_service", return_value=None):
            with patch("dystemctl.cli.app.find_similar_services", return_value=[]):
                result = runner.invoke(app, ["edit", "nonexistent"])
                assert result.exit_code == 1


class TestLogsCommandExtended:
    def test_logs_json_output(self, mock_service_info):
        with (
            patch(
                "dystemctl.cli.journal.resolve_service", return_value=mock_service_info
            ),
            patch("dystemctl.cli.info.tail_log_file", return_value=["line1", "line2"]),
        ):
            result = runner.invoke(app, ["logs", "-u", "test", "-o", "json"])
            assert result.exit_code == 0
            assert "[" in result.stdout  # JSON array

    def test_logs_json_pretty_output(self, mock_service_info):
        with (
            patch(
                "dystemctl.cli.journal.resolve_service", return_value=mock_service_info
            ),
            patch("dystemctl.cli.info.tail_log_file", return_value=["line1", "line2"]),
        ):
            result = runner.invoke(app, ["logs", "-u", "test", "-o", "json-pretty"])
            assert result.exit_code == 0

    def test_logs_cat_output(self, mock_service_info):
        with (
            patch(
                "dystemctl.cli.journal.resolve_service", return_value=mock_service_info
            ),
            patch("dystemctl.cli.info.tail_log_file", return_value=["line1", "line2"]),
        ):
            result = runner.invoke(app, ["logs", "-u", "test", "-o", "cat"])
            assert result.exit_code == 0

    def test_logs_reverse(self, mock_service_info):
        with (
            patch(
                "dystemctl.cli.journal.resolve_service", return_value=mock_service_info
            ),
            patch("dystemctl.cli.info.tail_log_file", return_value=["line1", "line2"]),
        ):
            result = runner.invoke(app, ["logs", "-u", "test", "-r"])
            assert result.exit_code == 0

    def test_logs_with_grep(self, mock_service_info):
        with (
            patch(
                "dystemctl.cli.journal.resolve_service", return_value=mock_service_info
            ),
            patch(
                "dystemctl.cli.journal.tail_log_file",
                return_value=["error line", "normal line"],
            ),
        ):
            result = runner.invoke(app, ["logs", "-u", "test", "-g", "error"])
            assert result.exit_code == 0


class TestImportExportExtended:
    def test_import_with_enable(self, sample_systemd_unit: Path, temp_dir: Path):
        launch_agents = temp_dir / "Library" / "LaunchAgents"
        launch_agents.mkdir(parents=True)

        with patch("pathlib.Path.home", return_value=temp_dir):
            with patch("dystemctl.cli.units.launchctl_enable", return_value=True):
                with patch("dystemctl.cli.units.build_registry") as mock_build:
                    mock_build.cache_clear = MagicMock()
                    result = runner.invoke(
                        app, ["import", "--enable", str(sample_systemd_unit)]
                    )
                    assert result.exit_code == 0
                    assert "Created" in result.stdout
                    assert "Enabled" in result.stdout

    def test_import_non_service_file(self, temp_dir: Path):
        non_service = temp_dir / "test.txt"
        non_service.write_text("[Unit]\nDescription=Test\n")

        with patch("pathlib.Path.home", return_value=temp_dir):
            result = runner.invoke(app, ["import", "--dry-run", str(non_service)])
            assert result.exit_code == 0
            assert "Warning" in result.output

    def test_export_to_file(self, mock_service_info, temp_dir: Path):
        output_path = temp_dir / "test.service"

        with patch(
            "dystemctl.cli.units.resolve_service", return_value=mock_service_info
        ):
            result = runner.invoke(app, ["export", "-o", str(output_path), "test"])
            assert result.exit_code == 0
            assert "Exported" in result.stdout
            assert output_path.exists()


class TestAliasCommand:
    def test_alias_create(self, temp_dir: Path):
        config_dir = temp_dir / ".config" / "dystemctl"

        with patch("pathlib.Path.home", return_value=temp_dir):
            result = runner.invoke(app, ["alias", "pg", "homebrew.mxcl.postgresql"])
            assert result.exit_code == 0
            assert "Added alias" in result.stdout
            assert (config_dir / "aliases.toml").exists()


class TestEnableDisableErrors:
    def test_enable_failure(self, mock_service_info):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch("dystemctl.cli.control.launchctl_enable", return_value=False),
        ):
            result = runner.invoke(app, ["enable", "test"])
            assert result.exit_code == 1
            assert "Failed to enable" in result.output

    def test_enable_with_now_start_failure(self, mock_service_info):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch("dystemctl.cli.control.launchctl_enable", return_value=True),
        ):
            with patch("dystemctl.cli.control.launchctl_start", return_value=False):
                result = runner.invoke(app, ["enable", "--now", "test"])
                assert result.exit_code == 1
                assert "Failed to start" in result.output

    def test_disable_failure(self, mock_service_info):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch("dystemctl.cli.control.launchctl_disable", return_value=False),
        ):
            result = runner.invoke(app, ["disable", "test"])
            assert result.exit_code == 1
            assert "Failed to disable" in result.output


class TestRestartErrors:
    def test_restart_not_found(self):
        with patch("dystemctl.cli.control.resolve_service", return_value=None):
            with patch("dystemctl.cli.app.find_similar_services", return_value=[]):
                result = runner.invoke(app, ["restart", "nonexistent"])
                assert result.exit_code == 1
                assert "not found" in result.output

    def test_restart_failure(self, mock_service_info):
        with (
            patch(
                "dystemctl.cli.control.resolve_service", return_value=mock_service_info
            ),
            patch("dystemctl.cli.control.launchctl_stop", return_value=True),
        ):
            with patch("dystemctl.cli.control.launchctl_start", return_value=False):
                result = runner.invoke(app, ["restart", "test"])
                assert result.exit_code == 1
                assert "Failed to restart" in result.output


class TestServiceNotFoundSuggestions:
    def test_service_not_found_with_suggestions(self):
        with patch("dystemctl.cli.control.resolve_service", return_value=None):
            with patch(
                "dystemctl.cli.app.find_similar_services",
                return_value=["homebrew.mxcl.redis"],
            ):
                result = runner.invoke(app, ["start", "rediis"])
                assert result.exit_code == 1
                assert "not found" in result.output
                assert "Did you mean" in result.output
                assert "homebrew.mxcl.redis" in result.output


class TestNoLegendOption:
    def test_no_legend(self, mock_service_info, mock_running_status):
        with patch("dystemctl.cli.info.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {"com.example.test": (1234, 0)}
            with (
                patch(
                    "dystemctl.cli.info.get_all_services",
                    return_value=[mock_service_info],
                ),
                patch(
                    "dystemctl.cli.info.get_service_status",
                    return_value=mock_running_status,
                ),
                patch("dystemctl.cli.info.filter_by_scope", side_effect=lambda x: x),
            ):
                result = runner.invoke(app, ["--no-legend", "list-units"])
                assert result.exit_code == 0
                assert "loaded units listed" not in result.stdout


class TestShowPropertyNotFound:
    def test_show_unknown_property(self, mock_service_info, mock_running_status):
        with (
            patch("dystemctl.cli.info.resolve_service", return_value=mock_service_info),
            patch(
                "dystemctl.cli.info.get_service_status",
                return_value=mock_running_status,
            ),
            patch("dystemctl.cli.info.get_process_info", return_value=None),
        ):
            result = runner.invoke(app, ["show", "-p", "UnknownProperty", "test"])
            assert result.exit_code == 0
            assert "UnknownProperty=" in result.stdout


class TestStatusWithTriggers:
    def test_status_with_keep_alive(self, temp_dir: Path, mock_running_status):
        service_info = ServiceInfo(
            label="com.example.test",
            plist_path=temp_dir / "test.plist",
            program_arguments=["/usr/bin/test"],
            keep_alive=True,
        )
        mock_process_info = MagicMock()
        mock_process_info.rss_bytes = 104857600
        mock_process_info.elapsed = timedelta(hours=1)
        mock_process_info.cpu_percent = 0.5

        with patch("dystemctl.cli.info.resolve_service", return_value=service_info):
            with patch(
                "dystemctl.cli.info.get_service_status",
                return_value=mock_running_status,
            ):
                with patch(
                    "dystemctl.cli.info.get_process_info",
                    return_value=mock_process_info,
                ):
                    with patch("dystemctl.cli.info.tail_log_file", return_value=[]):
                        result = runner.invoke(app, ["status", "test"])
                        assert result.exit_code == 0
                        assert "KeepAlive" in result.stdout

    def test_status_with_timer(self, temp_dir: Path, mock_running_status):
        service_info = ServiceInfo(
            label="com.example.timer",
            plist_path=temp_dir / "timer.plist",
            program_arguments=["/usr/bin/periodic"],
            start_interval=3600,
        )

        with patch("dystemctl.cli.info.resolve_service", return_value=service_info):
            with patch(
                "dystemctl.cli.info.get_service_status",
                return_value=mock_running_status,
            ):
                with patch("dystemctl.cli.info.get_process_info", return_value=None):
                    with patch("dystemctl.cli.info.tail_log_file", return_value=[]):
                        result = runner.invoke(app, ["status", "test"])
                        assert result.exit_code == 0
                        assert "Timer" in result.stdout

    def test_status_with_socket(self, temp_dir: Path, mock_running_status):
        from dystemctl.models import SocketInfo

        service_info = ServiceInfo(
            label="com.example.socket",
            plist_path=temp_dir / "socket.plist",
            program_arguments=["/usr/bin/server"],
            sockets=[
                SocketInfo(
                    name="main", sock_type="stream", family="IPv4", address="*:8080"
                )
            ],
        )

        with patch("dystemctl.cli.info.resolve_service", return_value=service_info):
            with patch(
                "dystemctl.cli.info.get_service_status",
                return_value=mock_running_status,
            ):
                with patch("dystemctl.cli.info.get_process_info", return_value=None):
                    with patch("dystemctl.cli.info.tail_log_file", return_value=[]):
                        result = runner.invoke(app, ["status", "test"])
                        assert result.exit_code == 0
                        assert "Socket" in result.stdout

    def test_status_with_watch_paths(self, temp_dir: Path, mock_running_status):
        service_info = ServiceInfo(
            label="com.example.watcher",
            plist_path=temp_dir / "watcher.plist",
            program_arguments=["/usr/bin/watcher"],
            watch_paths=["/var/spool/incoming"],
        )

        with patch("dystemctl.cli.info.resolve_service", return_value=service_info):
            with patch(
                "dystemctl.cli.info.get_service_status",
                return_value=mock_running_status,
            ):
                with patch("dystemctl.cli.info.get_process_info", return_value=None):
                    with patch("dystemctl.cli.info.tail_log_file", return_value=[]):
                        result = runner.invoke(app, ["status", "test"])
                        assert result.exit_code == 0
                        assert "Path" in result.stdout


class TestStatusWithLogs:
    def test_status_with_log_lines(self, temp_dir: Path, mock_running_status):
        log_file = temp_dir / "test.log"
        log_file.write_text("2024-01-01 12:00:00 Test log line\nAnother line\n")

        service_info = ServiceInfo(
            label="com.example.test",
            plist_path=temp_dir / "test.plist",
            program_arguments=["/usr/bin/test"],
            standard_out_path=log_file,
        )
        mock_process_info = MagicMock()
        mock_process_info.rss_bytes = 104857600
        mock_process_info.elapsed = timedelta(hours=1)
        mock_process_info.cpu_percent = 0.5

        with patch("dystemctl.cli.info.resolve_service", return_value=service_info):
            with patch(
                "dystemctl.cli.info.get_service_status",
                return_value=mock_running_status,
            ):
                with patch(
                    "dystemctl.cli.info.get_process_info",
                    return_value=mock_process_info,
                ):
                    result = runner.invoke(app, ["status", "test", "-n", "5"])
                    assert result.exit_code == 0

    def test_status_no_lines(self, mock_service_info, mock_running_status):
        mock_process_info = MagicMock()
        mock_process_info.rss_bytes = 104857600
        mock_process_info.elapsed = timedelta(hours=1)
        mock_process_info.cpu_percent = 0.5

        with (
            patch("dystemctl.cli.info.resolve_service", return_value=mock_service_info),
            patch(
                "dystemctl.cli.info.get_service_status",
                return_value=mock_running_status,
            ),
            patch(
                "dystemctl.cli.info.get_process_info",
                return_value=mock_process_info,
            ),
        ):
            result = runner.invoke(app, ["status", "test", "-n", "0"])
            assert result.exit_code == 0


class TestStatusFailed:
    def test_status_failed_service(self, mock_service_info):
        failed_status = ServiceStatus(
            label="com.example.test",
            pid=None,
            last_exit_status=1,
            loaded=True,
            domain=Domain.GUI,
        )

        with (
            patch("dystemctl.cli.info.resolve_service", return_value=mock_service_info),
            patch("dystemctl.cli.info.get_service_status", return_value=failed_status),
            patch("dystemctl.cli.info.get_process_info", return_value=None),
        ):
            result = runner.invoke(app, ["status", "test"])
            assert result.exit_code == 0
            assert "failed" in result.stdout.lower()


class TestListUnitsFilters:
    def test_list_units_state_filter(self, mock_service_info, mock_running_status):
        with patch("dystemctl.cli.info.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {"com.example.test": (1234, 0)}
            with (
                patch(
                    "dystemctl.cli.info.get_all_services",
                    return_value=[mock_service_info],
                ),
                patch(
                    "dystemctl.cli.info.get_service_status",
                    return_value=mock_running_status,
                ),
                patch("dystemctl.cli.info.filter_by_scope", side_effect=lambda x: x),
            ):
                result = runner.invoke(app, ["list-units", "--state", "running"])
                assert result.exit_code == 0

    def test_list_units_type_filter(self, temp_dir: Path, mock_running_status):
        timer_service = ServiceInfo(
            label="com.example.timer",
            plist_path=temp_dir / "timer.plist",
            program_arguments=["/usr/bin/periodic"],
            start_interval=3600,
        )

        with patch("dystemctl.cli.info.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {"com.example.timer": (None, 0)}
            with (
                patch(
                    "dystemctl.cli.info.get_all_services", return_value=[timer_service]
                ),
                patch(
                    "dystemctl.cli.info.get_service_status",
                    return_value=mock_running_status,
                ),
                patch("dystemctl.cli.info.filter_by_scope", side_effect=lambda x: x),
            ):
                result = runner.invoke(app, ["list-units", "--type", "timer"])
                assert result.exit_code == 0


class TestListTimersRunning:
    def test_list_timers_running(self, temp_dir: Path):
        timer_service = ServiceInfo(
            label="com.example.timer",
            plist_path=temp_dir / "timer.plist",
            program_arguments=["/usr/bin/periodic"],
            start_interval=3600,
        )
        running_status = ServiceStatus(
            label="com.example.timer",
            pid=1234,
            last_exit_status=None,
            loaded=True,
            domain=Domain.GUI,
        )

        with patch("dystemctl.cli.info.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {"com.example.timer": (1234, 0)}
            with (
                patch(
                    "dystemctl.cli.info.get_all_services", return_value=[timer_service]
                ),
                patch(
                    "dystemctl.cli.info.get_service_status", return_value=running_status
                ),
                patch("dystemctl.cli.info.filter_by_scope", side_effect=lambda x: x),
            ):
                result = runner.invoke(app, ["list-timers"])
                assert result.exit_code == 0
                assert "running" in result.stdout.lower()


class TestListSocketsRunning:
    def test_list_sockets_running(self, temp_dir: Path):
        from dystemctl.models import SocketInfo

        socket_service = ServiceInfo(
            label="com.example.socket",
            plist_path=temp_dir / "socket.plist",
            program_arguments=["/usr/bin/server"],
            sockets=[
                SocketInfo(
                    name="main", sock_type="stream", family="IPv4", address="*:8080"
                )
            ],
        )
        running_status = ServiceStatus(
            label="com.example.socket",
            pid=1234,
            last_exit_status=None,
            loaded=True,
            domain=Domain.GUI,
        )

        with patch("dystemctl.cli.info.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {"com.example.socket": (1234, 0)}
            with (
                patch(
                    "dystemctl.cli.info.get_all_services", return_value=[socket_service]
                ),
                patch(
                    "dystemctl.cli.info.get_service_status", return_value=running_status
                ),
                patch("dystemctl.cli.info.filter_by_scope", side_effect=lambda x: x),
            ):
                result = runner.invoke(app, ["list-sockets"])
                assert result.exit_code == 0


class TestListDependenciesExtended:
    def test_list_dependencies_with_timer(self, temp_dir: Path):
        service_info = ServiceInfo(
            label="com.example.timer",
            plist_path=temp_dir / "timer.plist",
            program_arguments=["/usr/bin/periodic"],
            start_interval=3600,
        )

        with patch("dystemctl.cli.info.resolve_service", return_value=service_info):
            result = runner.invoke(app, ["list-dependencies", "test"])
            assert result.exit_code == 0
            assert "Timer" in result.stdout

    def test_list_dependencies_with_sockets(self, temp_dir: Path):
        from dystemctl.models import SocketInfo

        service_info = ServiceInfo(
            label="com.example.socket",
            plist_path=temp_dir / "socket.plist",
            program_arguments=["/usr/bin/server"],
            sockets=[
                SocketInfo(
                    name="main", sock_type="stream", family="IPv4", address="*:8080"
                )
            ],
        )

        with patch("dystemctl.cli.info.resolve_service", return_value=service_info):
            result = runner.invoke(app, ["list-dependencies", "test"])
            assert result.exit_code == 0
            assert "Sockets" in result.stdout

    def test_list_dependencies_with_watch_paths(self, temp_dir: Path):
        service_info = ServiceInfo(
            label="com.example.watcher",
            plist_path=temp_dir / "watcher.plist",
            program_arguments=["/usr/bin/watcher"],
            watch_paths=[
                "/var/spool/incoming",
                "/var/spool/outgoing",
                "/var/spool/other",
                "/var/spool/more",
            ],
        )

        with patch("dystemctl.cli.info.resolve_service", return_value=service_info):
            result = runner.invoke(app, ["list-dependencies", "test"])
            assert result.exit_code == 0
            assert "WatchPaths" in result.stdout

    def test_list_dependencies_with_queue_directories(self, temp_dir: Path):
        service_info = ServiceInfo(
            label="com.example.queue",
            plist_path=temp_dir / "queue.plist",
            program_arguments=["/usr/bin/processor"],
            queue_directories=["/var/queue"],
        )

        with patch("dystemctl.cli.info.resolve_service", return_value=service_info):
            result = runner.invoke(app, ["list-dependencies", "test"])
            assert result.exit_code == 0
            assert "QueueDirectories" in result.stdout

    def test_list_dependencies_with_mach_services(self, temp_dir: Path):
        service_info = ServiceInfo(
            label="com.example.mach",
            plist_path=temp_dir / "mach.plist",
            program_arguments=["/usr/bin/machserver"],
            mach_services=[
                "com.example.service1",
                "com.example.service2",
                "com.example.service3",
                "com.example.service4",
            ],
        )

        with patch("dystemctl.cli.info.resolve_service", return_value=service_info):
            result = runner.invoke(app, ["list-dependencies", "test"])
            assert result.exit_code == 0
            assert "MachServices" in result.stdout

    def test_list_dependencies_no_triggers(self, temp_dir: Path):
        service_info = ServiceInfo(
            label="com.example.manual",
            plist_path=temp_dir / "manual.plist",
            program_arguments=["/usr/bin/manual"],
        )

        with patch("dystemctl.cli.info.resolve_service", return_value=service_info):
            result = runner.invoke(app, ["list-dependencies", "test"])
            assert result.exit_code == 0
            assert "No automatic triggers" in result.stdout


class TestShowWithExecStart:
    def test_show_with_program(self, temp_dir: Path, mock_running_status):
        service_info = ServiceInfo(
            label="com.example.test",
            plist_path=temp_dir / "test.plist",
            program="/usr/bin/myprogram",
        )

        with patch("dystemctl.cli.info.resolve_service", return_value=service_info):
            with patch(
                "dystemctl.cli.info.get_service_status",
                return_value=mock_running_status,
            ):
                with patch("dystemctl.cli.info.get_process_info", return_value=None):
                    result = runner.invoke(app, ["show", "test"])
                    assert result.exit_code == 0
                    assert "ExecStart=/usr/bin/myprogram" in result.stdout

    def test_show_with_working_directory(self, temp_dir: Path, mock_running_status):
        service_info = ServiceInfo(
            label="com.example.test",
            plist_path=temp_dir / "test.plist",
            program_arguments=["/usr/bin/test"],
            working_directory=Path("/var/lib/test"),
        )

        with patch("dystemctl.cli.info.resolve_service", return_value=service_info):
            with patch(
                "dystemctl.cli.info.get_service_status",
                return_value=mock_running_status,
            ):
                with patch("dystemctl.cli.info.get_process_info", return_value=None):
                    result = runner.invoke(app, ["show", "test"])
                    assert result.exit_code == 0
                    assert "WorkingDirectory=/var/lib/test" in result.stdout

    def test_show_with_user(self, temp_dir: Path, mock_running_status):
        service_info = ServiceInfo(
            label="com.example.test",
            plist_path=temp_dir / "test.plist",
            program_arguments=["/usr/bin/test"],
            user_name="testuser",
        )

        with patch("dystemctl.cli.info.resolve_service", return_value=service_info):
            with patch(
                "dystemctl.cli.info.get_service_status",
                return_value=mock_running_status,
            ):
                with patch("dystemctl.cli.info.get_process_info", return_value=None):
                    result = runner.invoke(app, ["show", "test"])
                    assert result.exit_code == 0
                    assert "User=testuser" in result.stdout


class TestResolveWithBinary:
    def test_resolve_shows_binary(self, temp_dir: Path):
        service_info = ServiceInfo(
            label="com.example.test",
            plist_path=temp_dir / "test.plist",
            program_arguments=["/usr/bin/test-binary", "--arg"],
        )

        with patch("dystemctl.cli.units.resolve_service", return_value=service_info):
            result = runner.invoke(app, ["resolve", "test"])
            assert result.exit_code == 0
            assert "Binary: test-binary" in result.stdout


class TestScopeFiltering:
    def test_filter_user_scope(self, temp_dir: Path, mock_running_status):
        user_service = ServiceInfo(
            label="com.example.user",
            plist_path=temp_dir / "Library" / "LaunchAgents" / "user.plist",
            program_arguments=["/usr/bin/user"],
        )
        user_service.plist_path.parent.mkdir(parents=True, exist_ok=True)
        user_service.plist_path.touch()

        with patch("dystemctl.cli.info.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {"com.example.user": (1234, 0)}
            with (
                patch(
                    "dystemctl.cli.info.get_all_services", return_value=[user_service]
                ),
                patch(
                    "dystemctl.cli.info.get_service_status",
                    return_value=mock_running_status,
                ),
            ):
                result = runner.invoke(app, ["--user", "list-units"])
                assert result.exit_code == 0

    def test_filter_system_scope(self, temp_dir: Path, mock_running_status):
        system_service = ServiceInfo(
            label="com.example.system",
            plist_path=temp_dir / "LaunchDaemons" / "system.plist",
            program_arguments=["/usr/bin/system"],
        )
        system_service.plist_path.parent.mkdir(parents=True, exist_ok=True)
        system_service.plist_path.touch()

        with patch("dystemctl.cli.info.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {"com.example.system": (1234, 0)}
            with (
                patch(
                    "dystemctl.cli.info.get_all_services", return_value=[system_service]
                ),
                patch(
                    "dystemctl.cli.info.get_service_status",
                    return_value=mock_running_status,
                ),
            ):
                result = runner.invoke(app, ["--system", "list-units"])
                assert result.exit_code == 0


class TestEscapeCommand:
    def test_escape_simple(self):
        result = runner.invoke(app, ["escape", "foo/bar"])
        assert result.exit_code == 0
        assert "foo-bar" in result.stdout

    def test_escape_path(self):
        result = runner.invoke(app, ["escape", "--path", "/dev/sda1"])
        assert result.exit_code == 0
        assert "dev-sda1" in result.stdout

    def test_unescape_simple(self):
        result = runner.invoke(app, ["escape", "--unescape", "foo-bar"])
        assert result.exit_code == 0
        assert "foo/bar" in result.stdout

    def test_unescape_path(self):
        result = runner.invoke(app, ["escape", "--unescape", "--path", "dev-sda1"])
        assert result.exit_code == 0
        assert "/dev/sda1" in result.stdout

    def test_escape_multiple_strings(self):
        result = runner.invoke(app, ["escape", "a/b", "c/d"])
        assert result.exit_code == 0
        assert "a-b" in result.stdout
        assert "c-d" in result.stdout


class TestVerifyCommand:
    def test_verify_valid_plist(self, temp_dir: Path):
        plist_path = temp_dir / "valid.plist"
        import plistlib

        with open(plist_path, "wb") as f:
            plistlib.dump(
                {
                    "Label": "com.example.valid",
                    "ProgramArguments": ["/usr/bin/test"],
                },
                f,
            )

        result = runner.invoke(app, ["verify", str(plist_path)])
        assert result.exit_code == 0
        assert "Valid plist" in result.stdout

    def test_verify_invalid_plist(self, temp_dir: Path):
        plist_path = temp_dir / "invalid.plist"
        plist_path.write_text("not a valid plist")

        result = runner.invoke(app, ["verify", str(plist_path)])
        assert result.exit_code == 1
        assert "Invalid plist format" in result.output

    def test_verify_missing_label(self, temp_dir: Path):
        plist_path = temp_dir / "nolabel.plist"
        import plistlib

        with open(plist_path, "wb") as f:
            plistlib.dump(
                {
                    "ProgramArguments": ["/usr/bin/test"],
                },
                f,
            )

        result = runner.invoke(app, ["verify", str(plist_path)])
        assert result.exit_code == 0
        assert "Missing required 'Label'" in result.stdout

    def test_verify_nonexistent_file(self, temp_dir: Path):
        result = runner.invoke(app, ["verify", str(temp_dir / "nonexistent.plist")])
        assert result.exit_code == 1
        assert "File not found" in result.output

    def test_verify_systemd_unit(self, sample_systemd_unit: Path):
        result = runner.invoke(app, ["verify", str(sample_systemd_unit)])
        assert result.exit_code == 0
        assert "Valid" in result.stdout


class TestCatJsonOutput:
    def test_cat_json(self, temp_dir: Path):
        import plistlib

        plist_path = temp_dir / "test.plist"
        with open(plist_path, "wb") as f:
            plistlib.dump(
                {
                    "Label": "com.example.test",
                    "ProgramArguments": ["/usr/bin/test"],
                },
                f,
            )

        service_info = ServiceInfo(
            label="com.example.test",
            plist_path=plist_path,
            program_arguments=["/usr/bin/test"],
        )

        with patch("dystemctl.cli.info.resolve_service", return_value=service_info):
            result = runner.invoke(app, ["cat", "--json", "test"])
            assert result.exit_code == 0
            import json

            data = json.loads(result.stdout.split("\n", 1)[1])  # Skip the header line
            assert data["Label"] == "com.example.test"


class TestShowAllOption:
    def test_show_all(self, temp_dir: Path, mock_running_status):
        service_info = ServiceInfo(
            label="com.example.test",
            plist_path=temp_dir / "test.plist",
            program_arguments=["/usr/bin/test"],
            keep_alive=True,
        )

        with patch("dystemctl.cli.info.resolve_service", return_value=service_info):
            with patch(
                "dystemctl.cli.info.get_service_status",
                return_value=mock_running_status,
            ):
                with patch("dystemctl.cli.info.get_process_info", return_value=None):
                    result = runner.invoke(app, ["show", "--all", "test"])
                    assert result.exit_code == 0
                    assert "Type=simple" in result.stdout
                    assert "Restart=always" in result.stdout
                    assert "KillMode=control-group" in result.stdout

    def test_show_all_inactive(self, temp_dir: Path, mock_stopped_status):
        service_info = ServiceInfo(
            label="com.example.test",
            plist_path=temp_dir / "test.plist",
            program_arguments=["/usr/bin/test"],
            keep_alive=False,
        )

        with patch("dystemctl.cli.info.resolve_service", return_value=service_info):
            with patch(
                "dystemctl.cli.info.get_service_status",
                return_value=mock_stopped_status,
            ):
                with patch("dystemctl.cli.info.get_process_info", return_value=None):
                    result = runner.invoke(app, ["show", "--all", "test"])
                    assert result.exit_code == 0
                    assert "Restart=no" in result.stdout


class TestRunCommand:
    def test_run_scope(self):
        with patch("dystemctl.cli.system.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["run", "--scope", "echo", "hello"])
            assert result.exit_code == 0
            mock_run.assert_called_once()

    def test_run_transient_success(self, temp_dir: Path):
        with patch("dystemctl.cli.system.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            with patch("dystemctl.cli.units.Path.home", return_value=temp_dir):
                (temp_dir / "Library" / "LaunchAgents").mkdir(parents=True)
                (temp_dir / "Library" / "Logs" / "dystemctl").mkdir(parents=True)
                result = runner.invoke(app, ["run", "--unit", "test", "echo", "hello"])
                assert result.exit_code == 0
                assert "Running as unit" in result.stdout

    def test_run_with_env(self, temp_dir: Path):
        with patch("dystemctl.cli.system.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            with patch("dystemctl.cli.units.Path.home", return_value=temp_dir):
                (temp_dir / "Library" / "LaunchAgents").mkdir(parents=True)
                (temp_dir / "Library" / "Logs" / "dystemctl").mkdir(parents=True)
                result = runner.invoke(app, ["run", "-E", "FOO=bar", "echo"])
                assert result.exit_code == 0


class TestAnalyzeCommand:
    def test_analyze_time(self):
        import time

        boot_sec = int(time.time()) - 100
        with patch("dystemctl.cli.system.subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout=f"{{ sec = {boot_sec}, usec = 0 }}"),
                MagicMock(returncode=0, stdout=""),
            ]
            result = runner.invoke(app, ["analyze", "time"])
            assert result.exit_code == 0
            assert "Startup finished" in result.stdout

    def test_analyze_blame(self):
        import time

        boot_sec = int(time.time()) - 100
        with patch("dystemctl.cli.system.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=f"{{ sec = {boot_sec}, usec = 0 }}"
            )
            with patch("dystemctl.cli.run.get_all_loaded_services") as mock_loaded:
                mock_loaded.cache_clear = MagicMock()
                mock_loaded.return_value = {}
                with patch("dystemctl.cli.run.build_registry", return_value={}):
                    result = runner.invoke(app, ["analyze", "blame"])
                    assert result.exit_code == 0
                    assert "Services by time" in result.stdout

    def test_analyze_critical_chain(self):
        import time

        boot_sec = int(time.time()) - 100
        with patch("dystemctl.cli.system.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=f"{{ sec = {boot_sec}, usec = 0 }}"
            )
            result = runner.invoke(app, ["analyze", "critical-chain"])
            assert result.exit_code == 0
            assert "Critical chain" in result.stdout

    def test_analyze_invalid(self):
        import time

        boot_sec = int(time.time()) - 100
        with patch("dystemctl.cli.system.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=f"{{ sec = {boot_sec}, usec = 0 }}"
            )
            result = runner.invoke(app, ["analyze", "invalid"])
            assert result.exit_code == 1
            assert "Unknown analyze subcommand" in result.output


class TestCancelCommand:
    def test_cancel_no_args(self):
        with patch("dystemctl.cli.run.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {}
            with patch("dystemctl.cli.run.build_registry", return_value={}):
                result = runner.invoke(app, ["cancel"])
                assert result.exit_code == 0

    def test_cancel_success(self):
        with patch("os.kill"):
            result = runner.invoke(app, ["cancel", "12345"])
            assert result.exit_code == 0
            assert "Cancelled" in result.stdout

    def test_cancel_not_found(self):
        with patch("os.kill", side_effect=ProcessLookupError()):
            result = runner.invoke(app, ["cancel", "99999"])
            assert result.exit_code == 0
            # Output goes to stderr via err_console
            assert "not found" in result.output

    def test_cancel_permission_denied(self):
        with patch("os.kill", side_effect=PermissionError()):
            result = runner.invoke(app, ["cancel", "1"])
            assert result.exit_code == 1
            assert "Permission denied" in result.output


class TestLinkCommand:
    def test_link_plist(self, temp_dir: Path):
        import plistlib

        plist_path = temp_dir / "test.plist"
        with open(plist_path, "wb") as f:
            plistlib.dump(
                {
                    "Label": "com.example.test",
                    "ProgramArguments": ["/usr/bin/test"],
                },
                f,
            )

        with patch("dystemctl.cli.units.Path.home", return_value=temp_dir):
            (temp_dir / "Library" / "LaunchAgents").mkdir(parents=True)
            with patch("dystemctl.cli.units.build_registry") as mock_registry:
                mock_registry.cache_clear = MagicMock()
                result = runner.invoke(app, ["link", str(plist_path)])
                assert result.exit_code == 0
                assert "Linked" in result.stdout

    def test_link_service(self, temp_dir: Path, sample_systemd_unit: Path):
        with patch("dystemctl.cli.units.Path.home", return_value=temp_dir):
            (temp_dir / "Library" / "LaunchAgents").mkdir(parents=True)
            with patch("dystemctl.cli.units.build_registry") as mock_registry:
                mock_registry.cache_clear = MagicMock()
                result = runner.invoke(app, ["link", str(sample_systemd_unit)])
                assert result.exit_code == 0
                assert "Linked" in result.stdout

    def test_link_nonexistent(self, temp_dir: Path):
        result = runner.invoke(app, ["link", str(temp_dir / "nonexistent.plist")])
        assert "File not found" in result.output


class TestRevertCommand:
    def test_revert_dystemctl_unit(self, temp_dir: Path):
        service_info = ServiceInfo(
            label="org.dystemctl.user.test",
            plist_path=temp_dir / "test.plist",
            program_arguments=["/usr/bin/test"],
        )
        service_info.plist_path.touch()

        with patch("dystemctl.cli.units.resolve_service", return_value=service_info):
            with patch("dystemctl.cli.units.launchctl_stop", return_value=True):
                with patch("dystemctl.cli.units.launchctl_disable", return_value=True):
                    with patch("dystemctl.cli.units.build_registry") as mock_registry:
                        mock_registry.cache_clear = MagicMock()
                        result = runner.invoke(app, ["revert", "test"])
                        assert result.exit_code == 0
                        assert "Reverted" in result.stdout
                        assert not service_info.plist_path.exists()

    def test_revert_non_dystemctl_unit(self, temp_dir: Path):
        service_info = ServiceInfo(
            label="com.apple.some.service",
            plist_path=temp_dir / "some.plist",
            program_arguments=["/usr/bin/test"],
        )

        with patch("dystemctl.cli.units.resolve_service", return_value=service_info):
            result = runner.invoke(app, ["revert", "some"])
            assert result.exit_code == 0
            assert "Not a dystemctl-managed unit" in result.output

    def test_revert_not_found(self):
        with patch("dystemctl.cli.units.resolve_service", return_value=None):
            with patch("dystemctl.cli.app.find_similar_services", return_value=[]):
                result = runner.invoke(app, ["revert", "nonexistent"])
                assert "not found" in result.output


class TestTryReloadOrRestart:
    def test_try_reload_or_restart_not_running(
        self, temp_dir: Path, mock_stopped_status
    ):
        service_info = ServiceInfo(
            label="com.example.test",
            plist_path=temp_dir / "test.plist",
            program_arguments=["/usr/bin/test"],
        )

        with patch("dystemctl.cli.control.resolve_service", return_value=service_info):
            with patch(
                "dystemctl.cli.control.get_service_status",
                return_value=mock_stopped_status,
            ):
                result = runner.invoke(app, ["try-reload-or-restart", "test"])
                assert result.exit_code == 0
                assert "Skipped" in result.stdout

    def test_try_reload_or_restart_running(self, temp_dir: Path, mock_running_status):
        service_info = ServiceInfo(
            label="com.example.test",
            plist_path=temp_dir / "test.plist",
            program_arguments=["/usr/bin/test"],
        )

        with patch("dystemctl.cli.control.resolve_service", return_value=service_info):
            with patch(
                "dystemctl.cli.control.get_service_status",
                return_value=mock_running_status,
            ):
                with patch("os.kill"):
                    result = runner.invoke(app, ["try-reload-or-restart", "test"])
                    assert result.exit_code == 0
                    assert "Reloaded" in result.stdout


class TestReenableCommand:
    def test_reenable_success(self, temp_dir: Path):
        service_info = ServiceInfo(
            label="com.example.test",
            plist_path=temp_dir / "test.plist",
            program_arguments=["/usr/bin/test"],
        )

        with patch("dystemctl.cli.control.resolve_service", return_value=service_info):
            with patch("dystemctl.cli.control.launchctl_disable", return_value=True):
                with patch("dystemctl.cli.control.launchctl_enable", return_value=True):
                    result = runner.invoke(app, ["reenable", "test"])
                    assert result.exit_code == 0
                    assert "Reenabled" in result.stdout


class TestWhoamiCommand:
    def test_whoami_own_pid(self):
        with patch("dystemctl.cli.control.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {}
            with patch("dystemctl.cli.control.build_registry", return_value={}):
                result = runner.invoke(app, ["whoami"])
                assert result.exit_code == 0
                assert "not part of any tracked service" in result.stdout

    def test_whoami_service_pid(self):
        with patch("dystemctl.cli.control.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {"com.example.test": (12345, 0)}
            with patch("dystemctl.cli.control.build_registry", return_value={}):
                result = runner.invoke(app, ["whoami", "12345"])
                assert result.exit_code == 0
                assert "com.example.test" in result.stdout


class TestListPathsCommand:
    def test_list_paths_empty(self):
        with patch("dystemctl.cli.info.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {}
            with patch("dystemctl.cli.info.get_all_services", return_value=[]):
                result = runner.invoke(app, ["list-paths"])
                assert result.exit_code == 0
                assert "No path-triggered services found" in result.stdout

    def test_list_paths_with_service(self, temp_dir: Path, mock_running_status):
        service_info = ServiceInfo(
            label="com.example.watcher",
            plist_path=temp_dir / "test.plist",
            program_arguments=["/usr/bin/test"],
            watch_paths=["/var/log/test"],
        )

        with patch("dystemctl.cli.info.get_all_loaded_services") as mock_loaded:
            mock_loaded.cache_clear = MagicMock()
            mock_loaded.return_value = {"com.example.watcher": (1234, 0)}
            with (
                patch(
                    "dystemctl.cli.info.get_all_services", return_value=[service_info]
                ),
                patch(
                    "dystemctl.cli.info.get_service_status",
                    return_value=mock_running_status,
                ),
            ):
                result = runner.invoke(app, ["list-paths"])
                assert result.exit_code == 0
                assert "com.example.watcher" in result.stdout
                assert "watch" in result.stdout


class TestCommandSeparation:
    def test_systemctl_hides_journalctl_commands(self):
        from dystemctl.cli import (
            JOURNALCTL_COMMANDS,
            app,
            get_command_name,
            hide_commands_for_mode,
        )

        # Reset hidden state
        for cmd in app.registered_commands:
            cmd.hidden = False

        hide_commands_for_mode("systemctl")

        hidden_names = set()
        for cmd in app.registered_commands:
            if cmd.hidden:
                hidden_names.add(get_command_name(cmd))

        for jctl_cmd in JOURNALCTL_COMMANDS:
            assert jctl_cmd in hidden_names, (
                f"{jctl_cmd} should be hidden for systemctl"
            )

    def test_journalctl_hides_systemctl_commands(self):
        from dystemctl.cli import (
            SYSTEMCTL_COMMANDS,
            app,
            get_command_name,
            hide_commands_for_mode,
        )

        # Reset hidden state
        for cmd in app.registered_commands:
            cmd.hidden = False

        hide_commands_for_mode("journalctl")

        hidden_names = set()
        for cmd in app.registered_commands:
            if cmd.hidden:
                hidden_names.add(get_command_name(cmd))

        for sctl_cmd in SYSTEMCTL_COMMANDS:
            assert sctl_cmd in hidden_names, (
                f"{sctl_cmd} should be hidden for journalctl"
            )


class TestVacuumCommands:
    def test_vacuum_time_dry_run(self, temp_dir: Path):
        log_dir = temp_dir / "Library" / "Logs" / "dystemctl"
        log_dir.mkdir(parents=True)

        old_log = log_dir / "old.log"
        old_log.write_text("old log content")
        import os

        os.utime(old_log, (0, 0))

        new_log = log_dir / "new.log"
        new_log.write_text("new log content")

        with patch("dystemctl.cli.units.Path.home", return_value=temp_dir):
            result = runner.invoke(app, ["vacuum-time", "1d", "--dry-run"])
            assert result.exit_code == 0
            assert "Would delete" in result.stdout
            assert old_log.exists()

    def test_vacuum_time_delete(self, temp_dir: Path):
        log_dir = temp_dir / "Library" / "Logs" / "dystemctl"
        log_dir.mkdir(parents=True)

        old_log = log_dir / "old.log"
        old_log.write_text("old log content")
        import os

        os.utime(old_log, (0, 0))

        with patch("dystemctl.cli.units.Path.home", return_value=temp_dir):
            result = runner.invoke(app, ["vacuum-time", "1d"])
            assert result.exit_code == 0
            assert "Deleted" in result.stdout
            assert not old_log.exists()

    def test_vacuum_time_invalid_spec(self):
        result = runner.invoke(app, ["vacuum-time", "invalid"])
        assert result.exit_code == 1
        assert "Invalid time spec" in result.output

    def test_vacuum_size_within_limit(self, temp_dir: Path):
        log_dir = temp_dir / "Library" / "Logs" / "dystemctl"
        log_dir.mkdir(parents=True)

        small_log = log_dir / "small.log"
        small_log.write_text("x" * 100)

        with patch("dystemctl.cli.units.Path.home", return_value=temp_dir):
            result = runner.invoke(app, ["vacuum-size", "1M"])
            assert result.exit_code == 0
            assert "within limit" in result.stdout

    def test_vacuum_size_dry_run(self, temp_dir: Path):
        log_dir = temp_dir / "Library" / "Logs" / "dystemctl"
        log_dir.mkdir(parents=True)

        big_log = log_dir / "big.log"
        big_log.write_text("x" * 10000)

        with patch("dystemctl.cli.units.Path.home", return_value=temp_dir):
            result = runner.invoke(app, ["vacuum-size", "1K", "--dry-run"])
            assert result.exit_code == 0
            assert "Would delete" in result.stdout

    def test_vacuum_size_invalid_spec(self):
        result = runner.invoke(app, ["vacuum-size", "invalid"])
        assert result.exit_code == 1
        assert "Invalid size spec" in result.output
