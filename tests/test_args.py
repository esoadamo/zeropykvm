"""Tests for args module - CLI argument parsing."""

import os
import tempfile

import pytest

from zeropykvm.args import Config, parse


class TestParse:
    """Test argument parsing."""

    def _create_temp_files(self):
        """Create temporary cert and key files for testing."""
        cert_fd, cert_path = tempfile.mkstemp(suffix=".pem")
        key_fd, key_path = tempfile.mkstemp(suffix=".pem")
        os.write(cert_fd, b"fake cert")
        os.write(key_fd, b"fake key")
        os.close(cert_fd)
        os.close(key_fd)
        return cert_path, key_path

    def test_required_args(self):
        """Test that --cert and --key are required."""
        with pytest.raises(SystemExit):
            parse([])

    def test_missing_cert(self):
        """Test that --cert alone fails."""
        with pytest.raises(SystemExit):
            parse(["--cert", "cert.pem"])

    def test_missing_key(self):
        """Test that --key alone fails."""
        with pytest.raises(SystemExit):
            parse(["--key", "key.pem"])

    def test_basic_args(self):
        """Test basic required arguments."""
        cert_path, key_path = self._create_temp_files()
        try:
            config = parse(["--cert", cert_path, "--key", key_path])
            assert config.tls_cert_path == os.path.realpath(cert_path)
            assert config.tls_key_path == os.path.realpath(key_path)
            assert config.port == 8443
            assert config.listen == "0.0.0.0"
            assert config.device == "/dev/video0"
            assert config.encoder == "/dev/video11"
            assert config.bitrate == 1_000_000
            assert config.no_epaper is False
        finally:
            os.unlink(cert_path)
            os.unlink(key_path)

    def test_short_args(self):
        """Test short argument forms."""
        cert_path, key_path = self._create_temp_files()
        try:
            config = parse(["-c", cert_path, "-k", key_path])
            assert config.tls_cert_path == os.path.realpath(cert_path)
            assert config.tls_key_path == os.path.realpath(key_path)
        finally:
            os.unlink(cert_path)
            os.unlink(key_path)

    def test_custom_port(self):
        """Test custom port."""
        cert_path, key_path = self._create_temp_files()
        try:
            config = parse(["--cert", cert_path, "--key", key_path, "--port", "443"])
            assert config.port == 443
        finally:
            os.unlink(cert_path)
            os.unlink(key_path)

    def test_custom_listen(self):
        """Test custom listen address."""
        cert_path, key_path = self._create_temp_files()
        try:
            config = parse(["--cert", cert_path, "--key", key_path,
                           "--listen", "127.0.0.1"])
            assert config.listen == "127.0.0.1"
        finally:
            os.unlink(cert_path)
            os.unlink(key_path)

    def test_custom_device(self):
        """Test custom device path."""
        cert_path, key_path = self._create_temp_files()
        try:
            config = parse(["--cert", cert_path, "--key", key_path,
                           "--device", "/dev/video1"])
            assert config.device == "/dev/video1"
        finally:
            os.unlink(cert_path)
            os.unlink(key_path)

    def test_custom_encoder(self):
        """Test custom encoder path."""
        cert_path, key_path = self._create_temp_files()
        try:
            config = parse(["--cert", cert_path, "--key", key_path,
                           "--encoder", "/dev/video12"])
            assert config.encoder == "/dev/video12"
        finally:
            os.unlink(cert_path)
            os.unlink(key_path)

    def test_custom_bitrate(self):
        """Test custom bitrate."""
        cert_path, key_path = self._create_temp_files()
        try:
            config = parse(["--cert", cert_path, "--key", key_path,
                           "--bitrate", "2000000"])
            assert config.bitrate == 2_000_000
        finally:
            os.unlink(cert_path)
            os.unlink(key_path)

    def test_no_epaper(self):
        """Test --no-epaper flag."""
        cert_path, key_path = self._create_temp_files()
        try:
            config = parse(["--cert", cert_path, "--key", key_path, "--no-epaper"])
            assert config.no_epaper is True
        finally:
            os.unlink(cert_path)
            os.unlink(key_path)

    def test_all_args(self):
        """Test all arguments together."""
        cert_path, key_path = self._create_temp_files()
        try:
            config = parse([
                "--cert", cert_path,
                "--key", key_path,
                "--port", "9443",
                "--listen", "192.168.1.1",
                "--device", "/dev/video1",
                "--encoder", "/dev/video12",
                "--bitrate", "3000000",
                "--no-epaper",
            ])
            assert config.port == 9443
            assert config.listen == "192.168.1.1"
            assert config.device == "/dev/video1"
            assert config.encoder == "/dev/video12"
            assert config.bitrate == 3_000_000
            assert config.no_epaper is True
        finally:
            os.unlink(cert_path)
            os.unlink(key_path)

    def test_help(self):
        """Test --help shows usage and exits."""
        with pytest.raises(SystemExit) as exc_info:
            parse(["--help"])
        assert exc_info.value.code == 0

    def test_config_defaults(self):
        """Test Config dataclass defaults."""
        config = Config()
        assert config.port == 8443
        assert config.listen == "0.0.0.0"
        assert config.device == "/dev/video0"
        assert config.encoder == "/dev/video11"
        assert config.bitrate == 1_000_000
        assert config.no_epaper is False
        assert config.tls_cert_path == ""
        assert config.tls_key_path == ""
