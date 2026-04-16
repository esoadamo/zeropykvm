"""Tests for EDID module."""

import os
from pathlib import Path

import pytest

from mykvm.edid import EdidPreset, SignalInfo, _load_edid_data


class TestEdidPresets:
    """Test EDID preset definitions."""

    def test_preset_values(self):
        assert EdidPreset.P720_60.value == "720p60"
        assert EdidPreset.P1080_25.value == "1080p25"
        assert EdidPreset.P1080_30.value == "1080p30"


class TestLoadEdidData:
    """Test EDID data loading from files."""

    def test_load_720p60(self):
        data = _load_edid_data(EdidPreset.P720_60)
        assert isinstance(data, bytes)
        # Standard EDID header
        assert data[0] == 0x00
        assert data[1] == 0xFF
        assert data[2] == 0xFF
        assert data[3] == 0xFF
        assert data[4] == 0xFF
        assert data[5] == 0xFF
        assert data[6] == 0xFF
        assert data[7] == 0x00
        # Should be a multiple of 128 bytes (EDID blocks)
        assert len(data) % 128 == 0

    def test_load_1080p25(self):
        data = _load_edid_data(EdidPreset.P1080_25)
        assert isinstance(data, bytes)
        assert data[:8] == b'\x00\xff\xff\xff\xff\xff\xff\x00'
        assert len(data) % 128 == 0

    def test_load_1080p30(self):
        data = _load_edid_data(EdidPreset.P1080_30)
        assert isinstance(data, bytes)
        assert data[:8] == b'\x00\xff\xff\xff\xff\xff\xff\x00'
        assert len(data) % 128 == 0

    def test_edid_files_exist(self):
        edid_dir = Path(__file__).parent.parent / "mykvm" / "edid_data"
        assert (edid_dir / "720p60edid").exists()
        assert (edid_dir / "1080p25edid").exists()
        assert (edid_dir / "1080p30edid").exists()

    def test_edid_block_count(self):
        """Test EDID data has at least 2 blocks (256 bytes)."""
        for preset in EdidPreset:
            data = _load_edid_data(preset)
            blocks = len(data) // 128
            assert blocks >= 2, f"{preset.value} has only {blocks} block(s)"


class TestSignalInfo:
    """Test SignalInfo dataclass."""

    def test_creation(self):
        info = SignalInfo(width=1920, height=1080, fps=30)
        assert info.width == 1920
        assert info.height == 1080
        assert info.fps == 30

    def test_720p(self):
        info = SignalInfo(width=1280, height=720, fps=60)
        assert info.width == 1280
        assert info.height == 720
        assert info.fps == 60
