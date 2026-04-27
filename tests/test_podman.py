"""Tests for Containerfile and podman-compose.yml."""

import os

import pytest

# Paths to the files being tested (relative to the repository root)
REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
CONTAINERFILE_PATH = os.path.join(REPO_ROOT, "Containerfile")
COMPOSE_PATH = os.path.join(REPO_ROOT, "podman-compose.yml")

EXPECTED_IMAGE = "docker.io/esoadamo/zeropykvm"


class TestContainerfile:
    """Tests for the Containerfile (Podmanfile)."""

    def _read(self):
        with open(CONTAINERFILE_PATH) as f:
            return f.read()

    def test_containerfile_exists(self):
        assert os.path.isfile(CONTAINERFILE_PATH), "Containerfile not found"

    def test_from_uses_esoadamo_image(self):
        content = self._read()
        assert EXPECTED_IMAGE in content

    def test_exposes_8443(self):
        content = self._read()
        assert "EXPOSE 8443" in content

    def test_volume_etc_zeropykvm(self):
        content = self._read()
        assert "/etc/zeropykvm" in content

    def test_entrypoint_zeropykvm(self):
        content = self._read()
        assert "zeropykvm" in content

    def test_no_epaper_flag(self):
        content = self._read()
        assert "--no-epaper" in content

    def test_cert_path_in_etc_zeropykvm(self):
        content = self._read()
        assert "/etc/zeropykvm/cert.pem" in content

    def test_key_path_in_etc_zeropykvm(self):
        content = self._read()
        assert "/etc/zeropykvm/key.pem" in content


class TestPodmanCompose:
    """Tests for podman-compose.yml."""

    def _read(self):
        with open(COMPOSE_PATH) as f:
            return f.read()

    def _parse(self):
        """Parse the compose file as YAML."""
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")
        with open(COMPOSE_PATH) as f:
            return yaml.safe_load(f)

    def test_compose_file_exists(self):
        assert os.path.isfile(COMPOSE_PATH), "podman-compose.yml not found"

    def test_compose_file_is_valid_yaml(self):
        data = self._parse()
        assert data is not None

    def test_compose_has_services(self):
        data = self._parse()
        assert "services" in data

    def test_compose_has_zeropykvm_service(self):
        data = self._parse()
        assert "zeropykvm" in data["services"]

    def test_compose_uses_esoadamo_image(self):
        data = self._parse()
        image = data["services"]["zeropykvm"]["image"]
        assert EXPECTED_IMAGE in image

    def test_compose_exposes_8443(self):
        data = self._parse()
        ports = data["services"]["zeropykvm"].get("ports", [])
        assert any("8443" in str(p) for p in ports)

    def test_compose_mounts_etc_zeropykvm(self):
        data = self._parse()
        volumes = data["services"]["zeropykvm"].get("volumes", [])
        assert any("/etc/zeropykvm" in str(v) for v in volumes)

    def test_compose_has_restart_policy(self):
        data = self._parse()
        restart = data["services"]["zeropykvm"].get("restart", "")
        assert restart != ""

    def test_compose_command_contains_cert(self):
        data = self._parse()
        command = data["services"]["zeropykvm"].get("command", [])
        cmd_str = " ".join(str(c) for c in command)
        assert "/etc/zeropykvm/cert.pem" in cmd_str

    def test_compose_command_contains_key(self):
        data = self._parse()
        command = data["services"]["zeropykvm"].get("command", [])
        cmd_str = " ".join(str(c) for c in command)
        assert "/etc/zeropykvm/key.pem" in cmd_str

    def test_compose_command_contains_no_epaper(self):
        data = self._parse()
        command = data["services"]["zeropykvm"].get("command", [])
        assert "--no-epaper" in command

    def test_compose_raw_contains_esoadamo_image(self):
        """Raw text check – does not require PyYAML."""
        content = self._read()
        assert EXPECTED_IMAGE in content
