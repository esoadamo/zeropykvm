"""Tests for utils module."""

from zeropykvm.utils import fourcc_to_string, get_local_ip


class TestFourccToString:
    """Test FourCC conversion."""

    def test_yuyv(self):
        fourcc = ord('Y') | (ord('U') << 8) | (ord('Y') << 16) | (ord('V') << 24)
        assert fourcc_to_string(fourcc) == "YUYV"

    def test_uyvy(self):
        fourcc = ord('U') | (ord('Y') << 8) | (ord('V') << 16) | (ord('Y') << 24)
        assert fourcc_to_string(fourcc) == "UYVY"

    def test_h264(self):
        fourcc = ord('H') | (ord('2') << 8) | (ord('6') << 16) | (ord('4') << 24)
        assert fourcc_to_string(fourcc) == "H264"

    def test_rgb3(self):
        fourcc = ord('R') | (ord('G') << 8) | (ord('B') << 16) | (ord('3') << 24)
        assert fourcc_to_string(fourcc) == "RGB3"

    def test_zero(self):
        result = fourcc_to_string(0)
        assert result == "\x00\x00\x00\x00"


class TestGetLocalIp:
    """Test local IP detection."""

    def test_returns_string_or_none(self):
        """Test that get_local_ip returns a string or None."""
        result = get_local_ip()
        assert result is None or isinstance(result, str)

    def test_ip_format(self):
        """Test that the returned IP has valid format."""
        result = get_local_ip()
        if result is not None:
            parts = result.split(".")
            assert len(parts) == 4
            for part in parts:
                val = int(part)
                assert 0 <= val <= 255
