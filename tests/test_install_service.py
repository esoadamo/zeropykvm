"""Tests for the install-service subcommand."""

import os
import sys
import tempfile
import unittest.mock as mock

import pytest

from zeropykvm.install_service import (
    DATA_DIR,
    SERVICE_FILE,
    SERVICE_NAME,
    build_service_unit,
    install_service,
    main,
)


class TestBuildServiceUnit:
    """Tests for build_service_unit()."""

    def test_contains_exec_path(self):
        unit = build_service_unit("/usr/bin/zeropykvm", "/etc/zeropykvm", 8443)
        assert "/usr/bin/zeropykvm" in unit

    def test_contains_cert_path(self):
        unit = build_service_unit("/usr/bin/zeropykvm", "/etc/zeropykvm", 8443)
        assert "--cert /etc/zeropykvm/cert.pem" in unit

    def test_contains_key_path(self):
        unit = build_service_unit("/usr/bin/zeropykvm", "/etc/zeropykvm", 8443)
        assert "--key /etc/zeropykvm/key.pem" in unit

    def test_contains_port(self):
        unit = build_service_unit("/usr/bin/zeropykvm", "/etc/zeropykvm", 9000)
        assert "--port 9000" in unit

    def test_does_not_contain_user_directive(self):
        unit = build_service_unit("/usr/bin/zeropykvm", "/etc/zeropykvm", 8443)
        assert "User=" not in unit

    def test_contains_working_directory(self):
        unit = build_service_unit("/usr/bin/zeropykvm", "/var/lib/kvm", 8443)
        assert "WorkingDirectory=/var/lib/kvm" in unit

    def test_contains_restart_policy(self):
        unit = build_service_unit("/usr/bin/zeropykvm", "/etc/zeropykvm", 8443)
        assert "Restart=on-failure" in unit

    def test_contains_wanted_by(self):
        unit = build_service_unit("/usr/bin/zeropykvm", "/etc/zeropykvm", 8443)
        assert "WantedBy=multi-user.target" in unit

    def test_contains_epaper(self):
        unit = build_service_unit("/usr/bin/zeropykvm", "/etc/zeropykvm", 8443)
        assert "--no-epaper" not in unit

    def test_has_unit_section(self):
        unit = build_service_unit("/usr/bin/zeropykvm", "/etc/zeropykvm", 8443)
        assert "[Unit]" in unit

    def test_has_service_section(self):
        unit = build_service_unit("/usr/bin/zeropykvm", "/etc/zeropykvm", 8443)
        assert "[Service]" in unit

    def test_has_install_section(self):
        unit = build_service_unit("/usr/bin/zeropykvm", "/etc/zeropykvm", 8443)
        assert "[Install]" in unit

    def test_custom_data_dir(self):
        unit = build_service_unit("/usr/bin/zeropykvm", "/tmp/mykvm", 8443)
        assert "/tmp/mykvm/cert.pem" in unit
        assert "/tmp/mykvm/key.pem" in unit


class TestInstallService:
    """Tests for install_service()."""

    def _mock_subprocess(self):
        """Return a patcher for subprocess.run that always succeeds."""
        return mock.patch("zeropykvm.install_service.subprocess.run")

    def test_creates_data_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "zeropykvm")
            service_file = os.path.join(tmpdir, "zeropykvm.service")
            with self._mock_subprocess():
                install_service(
                    data_dir=data_dir,
                    service_file=service_file,
                    enable=False,
                    start=False,
                )
            assert os.path.isdir(data_dir)

    def test_creates_service_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "zeropykvm")
            service_file = os.path.join(tmpdir, "zeropykvm.service")
            with self._mock_subprocess():
                install_service(
                    data_dir=data_dir,
                    service_file=service_file,
                    enable=False,
                    start=False,
                )
            assert os.path.isfile(service_file)

    def test_service_file_contains_unit_sections(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "zeropykvm")
            service_file = os.path.join(tmpdir, "zeropykvm.service")
            with self._mock_subprocess():
                install_service(
                    data_dir=data_dir,
                    service_file=service_file,
                    enable=False,
                    start=False,
                )
            with open(service_file) as f:
                content = f.read()
            assert "[Unit]" in content
            assert "[Service]" in content
            assert "[Install]" in content

    def test_service_file_has_no_user_directive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "zeropykvm")
            service_file = os.path.join(tmpdir, "zeropykvm.service")
            with self._mock_subprocess():
                install_service(
                    data_dir=data_dir,
                    service_file=service_file,
                    enable=False,
                    start=False,
                )
            with open(service_file) as f:
                content = f.read()
            assert "User=" not in content

    def test_service_file_contains_port(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "zeropykvm")
            service_file = os.path.join(tmpdir, "zeropykvm.service")
            with self._mock_subprocess():
                install_service(
                    data_dir=data_dir,
                    port=9443,
                    service_file=service_file,
                    enable=False,
                    start=False,
                )
            with open(service_file) as f:
                content = f.read()
            assert "--port 9443" in content

    def test_generates_tls_cert_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "zeropykvm")
            service_file = os.path.join(tmpdir, "zeropykvm.service")
            with self._mock_subprocess():
                install_service(
                    data_dir=data_dir,
                    service_file=service_file,
                    enable=False,
                    start=False,
                )
            assert os.path.isfile(os.path.join(data_dir, "cert.pem"))
            assert os.path.isfile(os.path.join(data_dir, "key.pem"))

    def test_key_chmod_600_enforced_after_generation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "zeropykvm")
            service_file = os.path.join(tmpdir, "zeropykvm.service")
            with self._mock_subprocess():
                with mock.patch("zeropykvm.install_service.os.chmod") as mock_chmod:
                    install_service(
                        data_dir=data_dir,
                        service_file=service_file,
                        enable=False,
                        start=False,
                    )
            key_path = os.path.join(data_dir, "key.pem")
            # os.chmod must have been called with the key path and mode 0o600
            chmod_calls = [c for c in mock_chmod.call_args_list if c.args[0] == key_path]
            assert any(c.args[1] == 0o600 for c in chmod_calls), (
                f"Expected chmod 600 on key; calls: {mock_chmod.call_args_list}"
            )

    def test_does_not_overwrite_existing_cert(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "zeropykvm")
            os.makedirs(data_dir)
            cert_path = os.path.join(data_dir, "cert.pem")
            key_path = os.path.join(data_dir, "key.pem")
            with open(cert_path, "w") as f:
                f.write("existing cert")
            with open(key_path, "w") as f:
                f.write("existing key")
            service_file = os.path.join(tmpdir, "zeropykvm.service")
            with self._mock_subprocess():
                install_service(
                    data_dir=data_dir,
                    service_file=service_file,
                    enable=False,
                    start=False,
                )
            with open(cert_path) as f:
                assert f.read() == "existing cert"
            with open(key_path) as f:
                assert f.read() == "existing key"

    def test_does_not_create_system_user(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "zeropykvm")
            service_file = os.path.join(tmpdir, "zeropykvm.service")
            with self._mock_subprocess() as mock_run:
                install_service(
                    data_dir=data_dir,
                    service_file=service_file,
                    enable=False,
                    start=False,
                )
            useradd_calls = [
                c for c in mock_run.call_args_list
                if c.args and c.args[0] and c.args[0][0] == "useradd"
            ]
            assert not useradd_calls, "useradd must not be called; service runs as root"

    def test_calls_daemon_reload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "zeropykvm")
            service_file = os.path.join(tmpdir, "zeropykvm.service")
            with self._mock_subprocess() as mock_run:
                install_service(
                    data_dir=data_dir,
                    service_file=service_file,
                    enable=False,
                    start=False,
                )
            calls = [str(c) for c in mock_run.call_args_list]
            assert any("daemon-reload" in c for c in calls)

    def test_enable_calls_systemctl_enable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "zeropykvm")
            service_file = os.path.join(tmpdir, "zeropykvm.service")
            with self._mock_subprocess() as mock_run:
                install_service(
                    data_dir=data_dir,
                    service_file=service_file,
                    enable=True,
                    start=False,
                )
            calls = [str(c) for c in mock_run.call_args_list]
            assert any("enable" in c for c in calls)

    def test_no_enable_skips_systemctl_enable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "zeropykvm")
            service_file = os.path.join(tmpdir, "zeropykvm.service")
            with self._mock_subprocess() as mock_run:
                install_service(
                    data_dir=data_dir,
                    service_file=service_file,
                    enable=False,
                    start=False,
                )
            calls = [str(c) for c in mock_run.call_args_list]
            assert not any("enable" in c for c in calls)

    def test_start_calls_systemctl_start(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "zeropykvm")
            service_file = os.path.join(tmpdir, "zeropykvm.service")
            with self._mock_subprocess() as mock_run:
                install_service(
                    data_dir=data_dir,
                    service_file=service_file,
                    enable=False,
                    start=True,
                )
            calls = [str(c) for c in mock_run.call_args_list]
            assert any("start" in c for c in calls)

    def test_no_start_skips_systemctl_start(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "zeropykvm")
            service_file = os.path.join(tmpdir, "zeropykvm.service")
            with self._mock_subprocess() as mock_run:
                install_service(
                    data_dir=data_dir,
                    service_file=service_file,
                    enable=False,
                    start=False,
                )
            calls = [str(c) for c in mock_run.call_args_list]
            assert not any("start" in c for c in calls)


class TestInstallServiceMain:
    """Tests for the main() CLI entry point."""

    def _run_main(self, args, tmpdir):
        """Helper: patch sys.argv, subprocess, and run main()."""
        data_dir = os.path.join(tmpdir, "zeropykvm")
        service_file = os.path.join(tmpdir, "zeropykvm.service")
        with (
            mock.patch("sys.argv", ["zeropykvm install-service"] + args),
            mock.patch("zeropykvm.install_service.subprocess.run"),
            mock.patch(
                "zeropykvm.install_service.DATA_DIR", data_dir
            ),
            mock.patch(
                "zeropykvm.install_service.SERVICE_FILE", service_file
            ),
        ):
            main()
        return data_dir, service_file

    def test_main_default_args(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir, service_file = self._run_main(
                ["--no-enable", "--no-start"], tmpdir
            )
            assert os.path.isdir(data_dir)
            assert os.path.isfile(service_file)

    def test_main_custom_port(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir, service_file = self._run_main(
                ["--port", "9000", "--no-enable", "--no-start"], tmpdir
            )
            with open(service_file) as f:
                content = f.read()
            assert "--port 9000" in content

    def test_main_no_user_arg(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                mock.patch("sys.argv", ["zeropykvm install-service", "--help"]),
                pytest.raises(SystemExit),
            ):
                main()

    def test_main_help_exits_zero(self):
        with pytest.raises(SystemExit) as exc_info:
            with mock.patch("sys.argv", ["zeropykvm install-service", "--help"]):
                main()
        assert exc_info.value.code == 0

    def test_main_permission_error_exits_nonzero(self):
        with (
            mock.patch("sys.argv", ["zeropykvm install-service", "--no-enable", "--no-start"]),
            mock.patch(
                "zeropykvm.install_service.install_service",
                side_effect=PermissionError("Permission denied"),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code != 0


class TestConstants:
    """Tests for module-level defaults."""

    def test_default_data_dir(self):
        assert DATA_DIR == "/etc/zeropykvm"

    def test_default_service_name(self):
        assert SERVICE_NAME == "zeropykvm"

    def test_default_service_file(self):
        assert SERVICE_FILE == "/etc/systemd/system/zeropykvm.service"
