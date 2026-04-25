"""Tests for e-Paper display module."""

from zeropykvm.epaper import Display


class TestDisplay:
    """Test e-Paper display controller."""

    def test_disabled_display(self):
        """Test disabled display accepts all operations silently."""
        display = Display(enabled=False)
        display.update_edid_status(True)
        display.update_hdmi_status(True)
        display.update_hid_status(True)
        display.show_status("192.168.1.1", 8443)
        display.sleep()
        display.shutdown()
        display.deinit()

    def test_enabled_display_on_non_rpi(self):
        """Test enabled display falls back gracefully on non-RPi."""
        display = Display(enabled=True)
        # On non-RPi, should fall back to disabled
        assert not display.enabled

    def test_status_updates(self):
        """Test status update methods don't crash."""
        display = Display(enabled=False)
        display.update_edid_status(True)
        display.update_edid_status(False)
        display.update_hdmi_status(True)
        display.update_hdmi_status(False)
        display.update_hid_status(True)
        display.update_hid_status(False)

    def test_show_status(self):
        """Test show_status with various inputs."""
        display = Display(enabled=False)
        display.show_status("0.0.0.0", 8443)
        display.show_status("192.168.1.100", 443)
        display.show_status("10.0.0.1", 9443)

    def test_partial_refresh_count(self):
        """Test that disabled display doesn't increment count."""
        display = Display(enabled=False)
        display.update_edid_status(True)
        assert display.partial_refresh_count == 0
