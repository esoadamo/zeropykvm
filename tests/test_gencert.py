"""Tests for gencert module."""

import os
import stat
import tempfile

from zeropykvm.gencert import generate_cert


class TestGenerateCert:
    """Tests for generate_cert()."""

    def test_creates_key_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, "cert.pem")
            key_path = os.path.join(tmpdir, "key.pem")
            generate_cert(cert_path=cert_path, key_path=key_path)
            assert os.path.isfile(key_path)

    def test_creates_cert_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, "cert.pem")
            key_path = os.path.join(tmpdir, "key.pem")
            generate_cert(cert_path=cert_path, key_path=key_path)
            assert os.path.isfile(cert_path)

    def test_key_file_mode_is_600(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, "cert.pem")
            key_path = os.path.join(tmpdir, "key.pem")
            generate_cert(cert_path=cert_path, key_path=key_path)
            mode = stat.S_IMODE(os.stat(key_path).st_mode)
            assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"

    def test_key_file_is_pem(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, "cert.pem")
            key_path = os.path.join(tmpdir, "key.pem")
            generate_cert(cert_path=cert_path, key_path=key_path)
            with open(key_path, "rb") as f:
                content = f.read()
            assert content.startswith(b"-----BEGIN")

    def test_cert_file_is_pem(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cert_path = os.path.join(tmpdir, "cert.pem")
            key_path = os.path.join(tmpdir, "key.pem")
            generate_cert(cert_path=cert_path, key_path=key_path)
            with open(cert_path, "rb") as f:
                content = f.read()
            assert content.startswith(b"-----BEGIN CERTIFICATE-----")
