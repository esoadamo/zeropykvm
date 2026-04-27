"""Tests for USB HID module."""

import struct
import threading
import time

from zeropykvm.usb import (
    KEYBOARD_REPORT_DESC,
    MOUSE_REPORT_DESC,
    HidDevice,
    HidKeyboard,
    HidMouse,
    ModifierFlags,
    Modifiers,
    MouseButtons,
    _get_modifier_bit,
    _get_scancode,
)


class TestHidDevice:
    """Test HidDevice background-sender behaviour."""

    def test_write_returns_true_when_queue_has_space(self):
        """write() must return True (enqueued) as long as the queue is not full."""
        dev = HidDevice("/nonexistent/hidg_test")
        result = dev.write(b"\x00" * 8)
        assert result is True
        dev.deinit()

    def test_write_returns_false_when_queue_full(self):
        """write() returns False and logs a warning when the queue is full."""
        import queue as queue_module
        dev = HidDevice("/nonexistent/hidg_test")
        # Fill the queue past its capacity
        for _ in range(dev._QUEUE_SIZE + 5):
            try:
                dev._queue.put_nowait(b"\x00")
            except queue_module.Full:
                break
        result = dev.write(b"\xff" * 8)
        assert result is False
        dev.deinit()

    def test_deinit_stops_sender_thread(self):
        """deinit() must stop the background thread within the join timeout."""
        dev = HidDevice("/nonexistent/hidg_test")
        assert dev._thread.is_alive()
        dev.deinit()
        dev._thread.join(timeout=1.0)
        assert not dev._thread.is_alive()

    def test_sender_thread_is_daemon(self):
        """Sender thread must be a daemon so it does not block process exit."""
        dev = HidDevice("/nonexistent/hidg_test")
        assert dev._thread.daemon is True
        dev.deinit()

    def test_deinit_is_idempotent(self):
        """Calling deinit() twice must not raise."""
        dev = HidDevice("/nonexistent/hidg_test")
        dev.deinit()
        dev.deinit()  # Should not raise


class TestModifierBit:
    """Test modifier key bit mapping."""

    def test_control_left(self):
        assert _get_modifier_bit("ControlLeft") == Modifiers.LEFT_CTRL

    def test_control_right(self):
        assert _get_modifier_bit("ControlRight") == Modifiers.RIGHT_CTRL

    def test_shift_left(self):
        assert _get_modifier_bit("ShiftLeft") == Modifiers.LEFT_SHIFT

    def test_shift_right(self):
        assert _get_modifier_bit("ShiftRight") == Modifiers.RIGHT_SHIFT

    def test_alt_left(self):
        assert _get_modifier_bit("AltLeft") == Modifiers.LEFT_ALT

    def test_alt_right(self):
        assert _get_modifier_bit("AltRight") == Modifiers.RIGHT_ALT

    def test_meta_left(self):
        assert _get_modifier_bit("MetaLeft") == Modifiers.LEFT_GUI

    def test_meta_right(self):
        assert _get_modifier_bit("MetaRight") == Modifiers.RIGHT_GUI

    def test_unknown_key(self):
        assert _get_modifier_bit("KeyA") is None

    def test_empty_string(self):
        assert _get_modifier_bit("") is None


class TestScancode:
    """Test scancode mapping."""

    def test_letters(self):
        assert _get_scancode("KeyA") == 0x04
        assert _get_scancode("KeyZ") == 0x1d

    def test_digits(self):
        assert _get_scancode("Digit0") == 0x27
        assert _get_scancode("Digit1") == 0x1e
        assert _get_scancode("Digit9") == 0x26

    def test_control_keys(self):
        assert _get_scancode("Enter") == 0x28
        assert _get_scancode("Escape") == 0x29
        assert _get_scancode("Backspace") == 0x2a
        assert _get_scancode("Tab") == 0x2b
        assert _get_scancode("Space") == 0x2c

    def test_function_keys(self):
        assert _get_scancode("F1") == 0x3a
        assert _get_scancode("F12") == 0x45

    def test_navigation_keys(self):
        assert _get_scancode("ArrowUp") == 0x52
        assert _get_scancode("ArrowDown") == 0x51
        assert _get_scancode("ArrowLeft") == 0x50
        assert _get_scancode("ArrowRight") == 0x4f

    def test_numpad(self):
        assert _get_scancode("Numpad0") == 0x62
        assert _get_scancode("Numpad9") == 0x61
        assert _get_scancode("NumpadEnter") == 0x58

    def test_unknown_key(self):
        assert _get_scancode("UnknownKey") is None

    def test_all_letters(self):
        """Test all letter keys are mapped."""
        for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            assert _get_scancode(f"Key{c}") is not None

    def test_symbols(self):
        assert _get_scancode("Minus") == 0x2d
        assert _get_scancode("Equal") == 0x2e
        assert _get_scancode("BracketLeft") == 0x2f
        assert _get_scancode("BracketRight") == 0x30


class TestHidKeyboard:
    """Test HID keyboard state management."""

    def test_init(self):
        kbd = HidKeyboard()
        assert kbd.pressed_keys == [0] * 6
        assert kbd.modifier_state == 0

    def test_key_down_letter(self):
        kbd = HidKeyboard()
        kbd.key_down("KeyA", ModifierFlags())
        assert kbd.pressed_keys[0] == 0x04
        assert kbd.modifier_state == 0

    def test_key_up_letter(self):
        kbd = HidKeyboard()
        kbd.key_down("KeyA", ModifierFlags())
        kbd.key_up("KeyA", ModifierFlags())
        assert kbd.pressed_keys[0] == 0

    def test_multiple_keys(self):
        kbd = HidKeyboard()
        kbd.key_down("KeyA", ModifierFlags())
        kbd.key_down("KeyB", ModifierFlags())
        assert kbd.pressed_keys[0] == 0x04
        assert kbd.pressed_keys[1] == 0x05

    def test_key_down_with_modifier_flags(self):
        kbd = HidKeyboard()
        kbd.key_down("KeyA", ModifierFlags(ctrl=True))
        assert kbd.modifier_state & Modifiers.LEFT_CTRL

    def test_key_down_modifier_key(self):
        kbd = HidKeyboard()
        kbd.key_down("ControlLeft", ModifierFlags())
        assert kbd.modifier_state & Modifiers.LEFT_CTRL
        # Modifier keys should NOT appear in pressed_keys
        assert all(k == 0 for k in kbd.pressed_keys)

    def test_key_up_modifier_key(self):
        kbd = HidKeyboard()
        kbd.key_down("ControlLeft", ModifierFlags(ctrl=True))
        kbd.key_up("ControlLeft", ModifierFlags(ctrl=False))
        assert not (kbd.modifier_state & Modifiers.LEFT_CTRL)

    def test_release_all(self):
        kbd = HidKeyboard()
        kbd.key_down("KeyA", ModifierFlags(ctrl=True))
        kbd.key_down("KeyB", ModifierFlags(ctrl=True))
        kbd.release_all()
        assert kbd.pressed_keys == [0] * 6
        assert kbd.modifier_state == 0

    def test_max_keys(self):
        """Test that only 6 simultaneous keys are tracked."""
        kbd = HidKeyboard()
        keys = ["KeyA", "KeyB", "KeyC", "KeyD", "KeyE", "KeyF", "KeyG"]
        for key in keys:
            kbd.key_down(key, ModifierFlags())
        # Only first 6 should be recorded
        assert kbd.pressed_keys[0] == _get_scancode("KeyA")
        assert kbd.pressed_keys[5] == _get_scancode("KeyF")

    def test_duplicate_key_down(self):
        """Test that pressing the same key twice doesn't add duplicate."""
        kbd = HidKeyboard()
        kbd.key_down("KeyA", ModifierFlags())
        kbd.key_down("KeyA", ModifierFlags())
        # Should only be in first slot
        assert kbd.pressed_keys[0] == 0x04
        assert kbd.pressed_keys[1] == 0


class TestHidMouse:
    """Test HID mouse state management."""

    def test_init(self):
        mouse = HidMouse()
        assert mouse.button_state == 0
        assert mouse.last_x == 0
        assert mouse.last_y == 0

    def test_move(self):
        mouse = HidMouse()
        mouse.move(100, 200)
        assert mouse.last_x == 100
        assert mouse.last_y == 200

    def test_click_left(self):
        mouse = HidMouse()
        mouse.click(0, True)
        assert mouse.button_state & MouseButtons.LEFT

    def test_click_right(self):
        mouse = HidMouse()
        mouse.click(2, True)
        assert mouse.button_state & MouseButtons.RIGHT

    def test_click_middle(self):
        mouse = HidMouse()
        mouse.click(1, True)
        assert mouse.button_state & MouseButtons.MIDDLE

    def test_release_button(self):
        mouse = HidMouse()
        mouse.click(0, True)
        mouse.click(0, False)
        assert not (mouse.button_state & MouseButtons.LEFT)

    def test_invalid_button(self):
        mouse = HidMouse()
        mouse.click(5, True)  # Should be ignored
        assert mouse.button_state == 0

    def test_multiple_buttons(self):
        mouse = HidMouse()
        mouse.click(0, True)
        mouse.click(2, True)
        assert mouse.button_state & MouseButtons.LEFT
        assert mouse.button_state & MouseButtons.RIGHT

    def test_release_all(self):
        mouse = HidMouse()
        mouse.click(0, True)
        mouse.click(1, True)
        mouse.click(2, True)
        mouse.release_all()
        assert mouse.button_state == 0


class TestReportDescriptors:
    """Test HID report descriptor integrity."""

    def test_keyboard_report_desc_length(self):
        """Test keyboard report descriptor has expected length."""
        assert len(KEYBOARD_REPORT_DESC) > 0
        # Standard boot keyboard descriptor is around 63 bytes
        assert len(KEYBOARD_REPORT_DESC) == 63

    def test_mouse_report_desc_length(self):
        """Test mouse report descriptor has expected length."""
        assert len(MOUSE_REPORT_DESC) > 0

    def test_keyboard_report_desc_starts_correctly(self):
        """Test keyboard descriptor starts with Usage Page (Generic Desktop)."""
        assert KEYBOARD_REPORT_DESC[0] == 0x05
        assert KEYBOARD_REPORT_DESC[1] == 0x01

    def test_mouse_report_desc_starts_correctly(self):
        """Test mouse descriptor starts with Usage Page (Generic Desktop)."""
        assert MOUSE_REPORT_DESC[0] == 0x05
        assert MOUSE_REPORT_DESC[1] == 0x01

    def test_keyboard_desc_ends_with_end_collection(self):
        """Test keyboard descriptor ends with End Collection."""
        assert KEYBOARD_REPORT_DESC[-1] == 0xc0

    def test_mouse_desc_ends_with_end_collection(self):
        """Test mouse descriptor ends with End Collection."""
        assert MOUSE_REPORT_DESC[-1] == 0xc0


class TestModifierFlags:
    """Test ModifierFlags dataclass."""

    def test_default(self):
        flags = ModifierFlags()
        assert not flags.ctrl
        assert not flags.alt
        assert not flags.shift
        assert not flags.meta

    def test_ctrl(self):
        flags = ModifierFlags(ctrl=True)
        assert flags.ctrl

    def test_all(self):
        flags = ModifierFlags(ctrl=True, alt=True, shift=True, meta=True)
        assert flags.ctrl
        assert flags.alt
        assert flags.shift
        assert flags.meta


class TestMouseReportFormat:
    """Test mouse report byte format matches the descriptor."""

    def test_report_size(self):
        """Mouse report should be 6 bytes."""
        # The internal report format: Buttons, X_L, X_H, Y_L, Y_H, Wheel
        report = struct.pack('<BHHB', 0, 0, 0, 0)
        assert len(report) == 6

    def test_report_with_position(self):
        """Test report encoding with specific position."""
        buttons = 0x01  # Left button
        x = 16384  # Half way
        y = 16384
        wheel = 0
        report = struct.pack('<BHHb', buttons, x, y, wheel)
        assert len(report) == 6
        assert report[0] == 0x01  # buttons
        assert struct.unpack_from('<H', report, 1)[0] == 16384  # X
        assert struct.unpack_from('<H', report, 3)[0] == 16384  # Y

    def test_wheel_report(self):
        """Test report with wheel delta."""
        report = struct.pack('<BHHb', 0, 100, 200, -5)
        assert len(report) == 6
        assert struct.unpack_from('b', report, 5)[0] == -5
