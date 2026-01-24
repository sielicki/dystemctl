"""Tests for dystemctl.systemd module."""

from __future__ import annotations

import os
from pathlib import Path

from dystemctl.models import ServiceInfo
from dystemctl.systemd import (
    expand_specifiers,
    parse_exec_start,
    parse_systemd_unit,
    translate_plist_to_unit,
    translate_to_plist,
)


class TestParseSystemdUnit:
    def test_parse_basic_unit(self, sample_systemd_unit: Path):
        unit = parse_systemd_unit(sample_systemd_unit)
        assert unit.name == "testservice"
        assert unit.source_path == sample_systemd_unit
        assert "Description" in unit.unit
        assert unit.unit["Description"] == "Test Service"

    def test_parse_service_section(self, sample_systemd_unit: Path):
        unit = parse_systemd_unit(sample_systemd_unit)
        assert "ExecStart" in unit.service
        assert "/usr/bin/testservice" in unit.service["ExecStart"]
        assert unit.service.get("Restart") == "always"
        assert unit.service.get("User") == "testuser"

    def test_parse_install_section(self, sample_systemd_unit: Path):
        unit = parse_systemd_unit(sample_systemd_unit)
        assert "WantedBy" in unit.install
        assert unit.install["WantedBy"] == "multi-user.target"

    def test_parse_complex_unit(self, complex_systemd_unit: Path):
        unit = parse_systemd_unit(complex_systemd_unit)
        assert unit.name == "complex"
        assert "Documentation" in unit.unit
        assert "Environment" in unit.service
        assert "FOO=bar" in unit.service["Environment"]

    def test_parse_line_continuation(self, complex_systemd_unit: Path):
        unit = parse_systemd_unit(complex_systemd_unit)
        # The ExecStart with line continuation should be joined
        exec_start = unit.service.get("ExecStart", "")
        assert "--config" in exec_start
        assert "--port" in exec_start

    def test_parse_comments_ignored(self, temp_dir: Path):
        unit_path = temp_dir / "commented.service"
        unit_path.write_text("""[Unit]
Description=Test
# This is a comment
; This is also a comment

[Service]
ExecStart=/usr/bin/test
""")
        unit = parse_systemd_unit(unit_path)
        assert "Description" in unit.unit
        assert unit.unit["Description"] == "Test"

    def test_parse_unknown_section_warning(self, temp_dir: Path):
        unit_path = temp_dir / "unknown.service"
        unit_path.write_text("""[Unit]
Description=Test

[Custom]
Foo=Bar

[Service]
ExecStart=/usr/bin/test
""")
        unit = parse_systemd_unit(unit_path)
        assert len(unit.warnings) > 0
        assert any("Unknown section" in w for w in unit.warnings)


class TestExpandSpecifiers:
    def test_expand_percent_n(self):
        result = expand_specifiers("test-%n", "myservice")
        assert result == "test-myservice"

    def test_expand_percent_p(self):
        result = expand_specifiers("test-%p", "myservice@instance")
        assert result == "test-myservice"

    def test_expand_percent_p_no_instance(self):
        result = expand_specifiers("test-%p", "myservice")
        assert result == "test-myservice"

    def test_expand_percent_i(self):
        result = expand_specifiers("test-%i", "myservice@myinstance.service")
        assert result == "test-myinstance"

    def test_expand_percent_i_no_instance(self):
        result = expand_specifiers("test-%i", "myservice")
        assert result == "test-"

    def test_expand_percent_u(self):
        result = expand_specifiers("user-%u", "test")
        assert result == f"user-{os.environ.get('USER', '')}"

    def test_expand_percent_U(self):
        result = expand_specifiers("uid-%U", "test")
        assert result == f"uid-{os.getuid()}"

    def test_expand_percent_h(self):
        result = expand_specifiers("home-%h", "test")
        assert result == f"home-{Path.home()}"

    def test_expand_percent_t(self):
        result = expand_specifiers("tmp-%t", "test")
        expected = os.environ.get("TMPDIR", "/tmp")
        assert result == f"tmp-{expected}"

    def test_expand_percent_S(self):
        result = expand_specifiers("state-%S", "test")
        expected = Path.home() / "Library" / "Application Support"
        assert result == f"state-{expected}"

    def test_expand_percent_C(self):
        result = expand_specifiers("cache-%C", "test")
        expected = Path.home() / "Library" / "Caches"
        assert result == f"cache-{expected}"

    def test_expand_percent_L(self):
        result = expand_specifiers("logs-%L", "test")
        expected = Path.home() / "Library" / "Logs"
        assert result == f"logs-{expected}"

    def test_expand_double_percent(self):
        result = expand_specifiers("100%% complete", "test")
        assert result == "100% complete"

    def test_expand_multiple_specifiers(self):
        result = expand_specifiers("%n in %h", "myservice")
        assert "myservice" in result
        assert str(Path.home()) in result


class TestParseExecStart:
    def test_parse_simple(self):
        args, warnings = parse_exec_start("/usr/bin/test --arg value")
        assert args == ["/usr/bin/test", "--arg", "value"]
        assert len(warnings) == 0

    def test_parse_with_quotes(self):
        args, warnings = parse_exec_start('/usr/bin/test --arg "value with spaces"')
        assert args == ["/usr/bin/test", "--arg", "value with spaces"]

    def test_parse_dash_prefix(self):
        args, warnings = parse_exec_start("-/usr/bin/test")
        assert args == ["/usr/bin/test"]
        assert len(warnings) == 1
        assert "ignore exit code" in warnings[0].lower()

    def test_parse_at_prefix(self):
        args, warnings = parse_exec_start("@/usr/bin/test")
        assert args == ["/usr/bin/test"]
        assert len(warnings) == 1
        assert "argv[0]" in warnings[0]

    def test_parse_plus_prefix(self):
        args, warnings = parse_exec_start("+/usr/bin/test")
        assert args == ["/usr/bin/test"]
        assert len(warnings) == 1
        assert "elevated" in warnings[0].lower()

    def test_parse_multiple_prefixes(self):
        args, warnings = parse_exec_start("-+/usr/bin/test")
        assert args == ["/usr/bin/test"]
        assert len(warnings) == 2


class TestTranslateToPlist:
    def test_translate_basic(self, sample_systemd_unit: Path):
        unit = parse_systemd_unit(sample_systemd_unit)
        plist, warnings = translate_to_plist(unit)

        assert "Label" in plist
        assert "dystemctl" in plist["Label"]
        assert "testservice" in plist["Label"]
        assert "ProgramArguments" in plist
        assert "/usr/bin/testservice" in plist["ProgramArguments"][0]

    def test_translate_working_directory(self, sample_systemd_unit: Path):
        unit = parse_systemd_unit(sample_systemd_unit)
        plist, warnings = translate_to_plist(unit)

        assert plist.get("WorkingDirectory") == "/var/lib/test"

    def test_translate_user(self, sample_systemd_unit: Path):
        unit = parse_systemd_unit(sample_systemd_unit)
        plist, warnings = translate_to_plist(unit)

        assert plist.get("UserName") == "testuser"

    def test_translate_restart_always(self, sample_systemd_unit: Path):
        unit = parse_systemd_unit(sample_systemd_unit)
        plist, warnings = translate_to_plist(unit)

        assert plist.get("KeepAlive") is True

    def test_translate_restart_on_failure(self, temp_dir: Path):
        unit_path = temp_dir / "onfailure.service"
        unit_path.write_text("""[Service]
ExecStart=/usr/bin/test
Restart=on-failure
""")
        unit = parse_systemd_unit(unit_path)
        plist, warnings = translate_to_plist(unit)

        assert plist.get("KeepAlive") == {"SuccessfulExit": False}

    def test_translate_restart_sec(self, temp_dir: Path):
        unit_path = temp_dir / "throttle.service"
        unit_path.write_text("""[Service]
ExecStart=/usr/bin/test
RestartSec=10
""")
        unit = parse_systemd_unit(unit_path)
        plist, warnings = translate_to_plist(unit)

        assert plist.get("ThrottleInterval") == 10

    def test_translate_environment(self, complex_systemd_unit: Path):
        unit = parse_systemd_unit(complex_systemd_unit)
        plist, warnings = translate_to_plist(unit)

        env = plist.get("EnvironmentVariables", {})
        assert "FOO" in env
        assert env["FOO"] == "bar"

    def test_translate_stdout(self, temp_dir: Path):
        unit_path = temp_dir / "stdout.service"
        unit_path.write_text("""[Service]
ExecStart=/usr/bin/test
StandardOutput=file:/var/log/test.log
""")
        unit = parse_systemd_unit(unit_path)
        plist, warnings = translate_to_plist(unit)

        assert plist.get("StandardOutPath") == "/var/log/test.log"

    def test_translate_stdout_null(self, temp_dir: Path):
        unit_path = temp_dir / "null.service"
        unit_path.write_text("""[Service]
ExecStart=/usr/bin/test
StandardOutput=null
""")
        unit = parse_systemd_unit(unit_path)
        plist, warnings = translate_to_plist(unit)

        assert plist.get("StandardOutPath") == "/dev/null"

    def test_translate_run_at_load(self, temp_dir: Path):
        unit_path = temp_dir / "runatload.service"
        unit_path.write_text("""[Service]
ExecStart=/usr/bin/test

[Install]
WantedBy=default.target
""")
        unit = parse_systemd_unit(unit_path)
        plist, warnings = translate_to_plist(unit)

        assert plist.get("RunAtLoad") is True

    def test_translate_unsupported_type(self, temp_dir: Path):
        unit_path = temp_dir / "forking.service"
        unit_path.write_text("""[Service]
Type=forking
ExecStart=/usr/bin/test
""")
        unit = parse_systemd_unit(unit_path)
        plist, warnings = translate_to_plist(unit)

        assert any("Type=forking" in w for w in warnings)

    def test_translate_unsupported_after(self, temp_dir: Path):
        unit_path = temp_dir / "after.service"
        unit_path.write_text("""[Unit]
After=network.target

[Service]
ExecStart=/usr/bin/test
""")
        unit = parse_systemd_unit(unit_path)
        plist, warnings = translate_to_plist(unit)

        assert any("After=" in w for w in warnings)

    def test_translate_resource_limits(self, temp_dir: Path):
        unit_path = temp_dir / "limits.service"
        unit_path.write_text("""[Service]
ExecStart=/usr/bin/test
LimitNOFILE=65536
LimitNPROC=4096
""")
        unit = parse_systemd_unit(unit_path)
        plist, warnings = translate_to_plist(unit)

        assert "SoftResourceLimits" in plist
        assert plist["SoftResourceLimits"]["NumberOfFiles"] == 65536
        assert plist["SoftResourceLimits"]["NumberOfProcesses"] == 4096

    def test_translate_limit_nofile_infinity(self, temp_dir: Path):
        unit_path = temp_dir / "infinity.service"
        unit_path.write_text("""[Service]
ExecStart=/usr/bin/test
LimitNOFILE=infinity
""")
        unit = parse_systemd_unit(unit_path)
        plist, warnings = translate_to_plist(unit)

        assert "SoftResourceLimits" in plist
        assert plist["SoftResourceLimits"]["NumberOfFiles"] == 10240

    def test_translate_limit_core(self, temp_dir: Path):
        unit_path = temp_dir / "core.service"
        unit_path.write_text("""[Service]
ExecStart=/usr/bin/test
LimitCORE=infinity
""")
        unit = parse_systemd_unit(unit_path)
        plist, warnings = translate_to_plist(unit)

        assert "SoftResourceLimits" in plist
        assert plist["SoftResourceLimits"]["CoreFileSize"] == -1

    def test_translate_umask(self, temp_dir: Path):
        unit_path = temp_dir / "umask.service"
        unit_path.write_text("""[Service]
ExecStart=/usr/bin/test
UMask=0077
""")
        unit = parse_systemd_unit(unit_path)
        plist, warnings = translate_to_plist(unit)

        assert plist.get("Umask") == 0o077

    def test_translate_type_notify_warning(self, temp_dir: Path):
        unit_path = temp_dir / "notify.service"
        unit_path.write_text("""[Service]
Type=notify
ExecStart=/usr/bin/test
""")
        unit = parse_systemd_unit(unit_path)
        plist, warnings = translate_to_plist(unit)

        assert any("Type=notify" in w and "sd_notify" in w for w in warnings)

    def test_translate_type_oneshot_ok(self, temp_dir: Path):
        unit_path = temp_dir / "oneshot.service"
        unit_path.write_text("""[Service]
Type=oneshot
ExecStart=/usr/bin/test
""")
        unit = parse_systemd_unit(unit_path)
        plist, warnings = translate_to_plist(unit)

        assert not any("Type=oneshot" in w for w in warnings)


class TestTranslatePlistToUnit:
    def test_translate_basic(self, sample_service_info: ServiceInfo):
        content, warnings = translate_plist_to_unit(sample_service_info)

        assert "[Unit]" in content
        assert "[Service]" in content
        assert "[Install]" in content
        assert "ExecStart" in content
        assert "testprogram" in content

    def test_translate_description(self, sample_service_info: ServiceInfo):
        content, warnings = translate_plist_to_unit(sample_service_info)

        assert f"Description={sample_service_info.display_name}" in content

    def test_translate_working_directory(self, temp_dir: Path):
        info = ServiceInfo(
            label="test",
            plist_path=temp_dir / "test.plist",
            program_arguments=["/usr/bin/test"],
            working_directory=Path("/var/lib/test"),
        )
        content, warnings = translate_plist_to_unit(info)

        assert "WorkingDirectory=/var/lib/test" in content

    def test_translate_user(self, temp_dir: Path):
        info = ServiceInfo(
            label="test",
            plist_path=temp_dir / "test.plist",
            program_arguments=["/usr/bin/test"],
            user_name="testuser",
        )
        content, warnings = translate_plist_to_unit(info)

        assert "User=testuser" in content

    def test_translate_keep_alive(self, temp_dir: Path):
        info = ServiceInfo(
            label="test",
            plist_path=temp_dir / "test.plist",
            program_arguments=["/usr/bin/test"],
            keep_alive=True,
        )
        content, warnings = translate_plist_to_unit(info)

        assert "Restart=always" in content

    def test_translate_stdout(self, temp_dir: Path):
        info = ServiceInfo(
            label="test",
            plist_path=temp_dir / "test.plist",
            program_arguments=["/usr/bin/test"],
            standard_out_path=Path("/var/log/test.log"),
        )
        content, warnings = translate_plist_to_unit(info)

        assert "StandardOutput=file:/var/log/test.log" in content

    def test_translate_run_at_load(self, temp_dir: Path):
        info = ServiceInfo(
            label="test",
            plist_path=temp_dir / "test.plist",
            program_arguments=["/usr/bin/test"],
            run_at_load=True,
        )
        content, warnings = translate_plist_to_unit(info)

        assert "WantedBy=default.target" in content

    def test_translate_timer_warning(self, timer_service_info: ServiceInfo):
        content, warnings = translate_plist_to_unit(timer_service_info)

        assert any(".timer unit" in w for w in warnings)

    def test_translate_socket_warning(self, socket_service_info: ServiceInfo):
        content, warnings = translate_plist_to_unit(socket_service_info)

        assert any(".socket unit" in w for w in warnings)

    def test_translate_program_only(self, temp_dir: Path):
        info = ServiceInfo(
            label="test",
            plist_path=temp_dir / "test.plist",
            program="/usr/bin/myprogram",
        )
        content, warnings = translate_plist_to_unit(info)

        assert "ExecStart=/usr/bin/myprogram" in content
