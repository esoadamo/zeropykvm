"""USB HID Gadget for keyboard and mouse emulation.

Creates TWO separate HID devices for better BIOS compatibility:
- /dev/hidg0: Keyboard (Boot Protocol, 8-byte report, no Report ID)
- /dev/hidg1: Mouse (Absolute positioning, 6-byte report)

Reference: https://github.com/stjeong/rasp_vusb
"""

import errno as errno_mod
import logging
import os
import queue as queue_module
import struct
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

GADGET_PATH = "/sys/kernel/config/usb_gadget/mykvm"
HIDG_KEYBOARD = "/dev/hidg0"
HIDG_MOUSE = "/dev/hidg1"

# Module-level UDC name storage
_g_udc_name: str = ""

# UDC states as defined in Linux kernel
UDC_STATE_MAP = {
    "not attached": "not_attached",
    "attached": "attached",
    "powered": "powered",
    "reconnecting": "reconnecting",
    "unauthenticated": "unauthenticated",
    "default": "default",
    "addressed": "addressed",
    "configured": "configured",
    "suspended": "suspended",
}


def _read_udc_state() -> str:
    """Read current UDC state from /sys/class/udc/<udc>/state."""
    if not _g_udc_name:
        return "unknown"

    path = f"/sys/class/udc/{_g_udc_name}/state"
    try:
        with open(path, "r", encoding="ascii") as f:
            state_str = f.read().strip()
        return UDC_STATE_MAP.get(state_str, "unknown")
    except OSError:
        return "unknown"


# ============================================================================
# HID Report Descriptors
# ============================================================================

# Boot Protocol Keyboard HID Report Descriptor (no Report ID for BIOS compatibility)
# Report format: [Modifiers, Reserved, Key1, Key2, Key3, Key4, Key5, Key6] = 8 bytes
KEYBOARD_REPORT_DESC = bytes([
    0x05, 0x01,  # Usage Page (Generic Desktop)
    0x09, 0x06,  # Usage (Keyboard)
    0xa1, 0x01,  # Collection (Application)
    0x05, 0x07,  # Usage Page (Key Codes)
    0x19, 0xe0,  # Usage Minimum (224 - Left Control)
    0x29, 0xe7,  # Usage Maximum (231 - Right GUI)
    0x15, 0x00,  # Logical Minimum (0)
    0x25, 0x01,  # Logical Maximum (1)
    0x75, 0x01,  # Report Size (1)
    0x95, 0x08,  # Report Count (8)
    0x81, 0x02,  # Input (Data, Variable, Absolute) - Modifier byte
    0x95, 0x01,  # Report Count (1)
    0x75, 0x08,  # Report Size (8)
    0x81, 0x03,  # Input (Constant) - Reserved byte
    0x95, 0x05,  # Report Count (5)
    0x75, 0x01,  # Report Size (1)
    0x05, 0x08,  # Usage Page (LEDs)
    0x19, 0x01,  # Usage Minimum (1)
    0x29, 0x05,  # Usage Maximum (5)
    0x91, 0x02,  # Output (Data, Variable, Absolute) - LED report
    0x95, 0x01,  # Report Count (1)
    0x75, 0x03,  # Report Size (3)
    0x91, 0x03,  # Output (Constant) - LED padding
    0x95, 0x06,  # Report Count (6)
    0x75, 0x08,  # Report Size (8)
    0x15, 0x00,  # Logical Minimum (0)
    0x25, 0x65,  # Logical Maximum (101)
    0x05, 0x07,  # Usage Page (Key Codes)
    0x19, 0x00,  # Usage Minimum (0)
    0x29, 0x65,  # Usage Maximum (101)
    0x81, 0x00,  # Input (Data, Array) - Key array (6 keys)
    0xc0,        # End Collection
])

# Absolute Mouse HID Report Descriptor (no Report ID)
# Report format: [Buttons, X_L, X_H, Y_L, Y_H, Wheel] = 6 bytes
MOUSE_REPORT_DESC = bytes([
    0x05, 0x01,  # Usage Page (Generic Desktop)
    0x09, 0x02,  # Usage (Mouse)
    0xa1, 0x01,  # Collection (Application)
    0x09, 0x01,  # Usage (Pointer)
    0xa1, 0x00,  # Collection (Physical)
    0x05, 0x09,  # Usage Page (Button)
    0x19, 0x01,  # Usage Minimum (Button 1)
    0x29, 0x03,  # Usage Maximum (Button 3)
    0x15, 0x00,  # Logical Minimum (0)
    0x25, 0x01,  # Logical Maximum (1)
    0x95, 0x03,  # Report Count (3)
    0x75, 0x01,  # Report Size (1)
    0x81, 0x02,  # Input (Data, Variable, Absolute) - 3 buttons
    0x95, 0x01,  # Report Count (1)
    0x75, 0x05,  # Report Size (5)
    0x81, 0x03,  # Input (Constant) - 5 bit padding
    0x05, 0x01,  # Usage Page (Generic Desktop)
    0x09, 0x30,  # Usage (X)
    0x09, 0x31,  # Usage (Y)
    0x15, 0x00,  # Logical Minimum (0)
    0x26, 0xff, 0x7f,  # Logical Maximum (32767)
    0x75, 0x10,  # Report Size (16)
    0x95, 0x02,  # Report Count (2)
    0x81, 0x02,  # Input (Data, Variable, Absolute) - X and Y
    0x09, 0x38,  # Usage (Wheel)
    0x15, 0x81,  # Logical Minimum (-127)
    0x25, 0x7f,  # Logical Maximum (127)
    0x75, 0x08,  # Report Size (8)
    0x95, 0x01,  # Report Count (1)
    0x81, 0x06,  # Input (Data, Variable, Relative) - Wheel
    0xc0,        # End Collection
    0xc0,        # End Collection
])

# ============================================================================
# Modifier key constants
# ============================================================================


class Modifiers:
    """Modifier key bit flags (byte 0 of HID report)."""
    LEFT_CTRL = 0x01
    LEFT_SHIFT = 0x02
    LEFT_ALT = 0x04
    LEFT_GUI = 0x08
    RIGHT_CTRL = 0x10
    RIGHT_SHIFT = 0x20
    RIGHT_ALT = 0x40
    RIGHT_GUI = 0x80


class MouseButtons:
    """Mouse button bit flags."""
    LEFT = 0x01
    RIGHT = 0x02
    MIDDLE = 0x04


@dataclass
class ModifierFlags:
    """Modifier flags from browser event."""
    ctrl: bool = False
    alt: bool = False
    shift: bool = False
    meta: bool = False


# ============================================================================
# Key code mappings
# ============================================================================

# Modifier key name to bit mapping
MODIFIER_BIT_MAP = {
    "ControlLeft": Modifiers.LEFT_CTRL,
    "ControlRight": Modifiers.RIGHT_CTRL,
    "ShiftLeft": Modifiers.LEFT_SHIFT,
    "ShiftRight": Modifiers.RIGHT_SHIFT,
    "AltLeft": Modifiers.LEFT_ALT,
    "AltRight": Modifiers.RIGHT_ALT,
    "MetaLeft": Modifiers.LEFT_GUI,
    "MetaRight": Modifiers.RIGHT_GUI,
}

# KeyboardEvent.code to USB HID scancode mapping
SCANCODE_MAP = {
    # Letters
    "KeyA": 0x04, "KeyB": 0x05, "KeyC": 0x06, "KeyD": 0x07,
    "KeyE": 0x08, "KeyF": 0x09, "KeyG": 0x0a, "KeyH": 0x0b,
    "KeyI": 0x0c, "KeyJ": 0x0d, "KeyK": 0x0e, "KeyL": 0x0f,
    "KeyM": 0x10, "KeyN": 0x11, "KeyO": 0x12, "KeyP": 0x13,
    "KeyQ": 0x14, "KeyR": 0x15, "KeyS": 0x16, "KeyT": 0x17,
    "KeyU": 0x18, "KeyV": 0x19, "KeyW": 0x1a, "KeyX": 0x1b,
    "KeyY": 0x1c, "KeyZ": 0x1d,
    # Numbers
    "Digit1": 0x1e, "Digit2": 0x1f, "Digit3": 0x20, "Digit4": 0x21,
    "Digit5": 0x22, "Digit6": 0x23, "Digit7": 0x24, "Digit8": 0x25,
    "Digit9": 0x26, "Digit0": 0x27,
    # Control keys
    "Enter": 0x28, "Escape": 0x29, "Backspace": 0x2a, "Tab": 0x2b,
    "Space": 0x2c,
    # Symbols
    "Minus": 0x2d, "Equal": 0x2e, "BracketLeft": 0x2f,
    "BracketRight": 0x30, "Backslash": 0x31, "Semicolon": 0x33,
    "Quote": 0x34, "Backquote": 0x35, "Comma": 0x36, "Period": 0x37,
    "Slash": 0x38,
    # Function keys
    "CapsLock": 0x39,
    "F1": 0x3a, "F2": 0x3b, "F3": 0x3c, "F4": 0x3d,
    "F5": 0x3e, "F6": 0x3f, "F7": 0x40, "F8": 0x41,
    "F9": 0x42, "F10": 0x43, "F11": 0x44, "F12": 0x45,
    # Navigation
    "PrintScreen": 0x46, "ScrollLock": 0x47, "Pause": 0x48,
    "Insert": 0x49, "Home": 0x4a, "PageUp": 0x4b,
    "Delete": 0x4c, "End": 0x4d, "PageDown": 0x4e,
    "ArrowRight": 0x4f, "ArrowLeft": 0x50,
    "ArrowDown": 0x51, "ArrowUp": 0x52,
    # Numpad
    "NumLock": 0x53, "NumpadDivide": 0x54, "NumpadMultiply": 0x55,
    "NumpadSubtract": 0x56, "NumpadAdd": 0x57, "NumpadEnter": 0x58,
    "Numpad1": 0x59, "Numpad2": 0x5a, "Numpad3": 0x5b,
    "Numpad4": 0x5c, "Numpad5": 0x5d, "Numpad6": 0x5e,
    "Numpad7": 0x5f, "Numpad8": 0x60, "Numpad9": 0x61,
    "Numpad0": 0x62, "NumpadDecimal": 0x63,
    # Additional keys
    "IntlBackslash": 0x64, "ContextMenu": 0x65,
}


def _get_modifier_bit(code: str) -> int | None:
    """Get modifier bit for modifier keys."""
    return MODIFIER_BIT_MAP.get(code)


def _get_scancode(code: str) -> int | None:
    """Get USB HID scancode for a KeyboardEvent.code value."""
    return SCANCODE_MAP.get(code)


# ============================================================================
# HidDevice - Common HID device handling with lifecycle management
# ============================================================================

class HidDevice:
    """Common HID device structure with lifecycle management.

    Handles open/write/reconnect logic for both keyboard and mouse.

    All writes are delivered asynchronously via a background sender thread so
    that the WebSocket handler thread is never blocked by HID back-pressure.
    Transient ``BlockingIOError`` (HID gadget queue full) is retried for up to
    ``_WRITE_TIMEOUT_S`` seconds — typically one USB polling interval (1–8 ms)
    suffices.  The write is never silently dropped due to a backoff timer, which
    was the cause of missing keyup events and stuck key repeats.
    """

    RECONNECT_INTERVAL_MS = 1000
    # Size of the in-process send queue.  At human typing speed this will
    # never fill, but we cap it to avoid unbounded memory growth if the USB
    # host is disconnected for a long time.
    _QUEUE_SIZE = 256
    # How long to wait between BlockingIOError retries (one USB poll interval).
    _WRITE_RETRY_S = 0.001   # 1 ms
    # Maximum total time to spend retrying a single write before dropping it.
    _WRITE_TIMEOUT_S = 0.050  # 50 ms

    def __init__(self, device_path: str):
        self.device_path = device_path
        self.file: int | None = None  # File descriptor
        self.disconnected = False
        self.last_error_ns = 0
        self._stop = threading.Event()
        self._queue: queue_module.Queue[bytes | None] = queue_module.Queue(
            maxsize=self._QUEUE_SIZE)
        self._thread = threading.Thread(
            target=self._sender_loop,
            name=f"hid-sender-{device_path}",
            daemon=True,
        )
        self._thread.start()

    def open(self) -> None:
        """Open the HID device for writing.

        Raises:
            OSError: If opening fails.
        """
        try:
            self.file = os.open(self.device_path, os.O_WRONLY | os.O_NONBLOCK)
            self.disconnected = False
        except OSError as e:
            logger.error("Failed to open %s: %s", self.device_path, e)
            raise

    def close(self) -> None:
        """Close the HID device."""
        if self.file is not None:
            try:
                os.close(self.file)
            except OSError:
                pass
            self.file = None

    def write(self, report: bytes) -> bool:
        """Enqueue a HID report for asynchronous delivery.

        Returns True if the report was enqueued, False if the queue is full.
        The actual write happens on the background sender thread.
        """
        try:
            self._queue.put_nowait(report)
            return True
        except queue_module.Full:
            logger.warning("HID %s: send queue full, dropping report",
                           self.device_path)
            return False

    # ------------------------------------------------------------------
    # Background sender thread
    # ------------------------------------------------------------------

    def _sender_loop(self) -> None:
        """Background thread: drain the queue and write to the HID device."""
        while not self._stop.is_set():
            try:
                report = self._queue.get(timeout=0.1)
            except queue_module.Empty:
                continue
            if report is None:  # Sentinel: shut down
                break
            self._deliver(report)

    def _deliver(self, report: bytes) -> None:
        """Write one report, retrying on transient BlockingIOError.

        Drops the report if:
        - USB is not in the "configured" state (host not connected).
        - The retry deadline is exceeded.
        - A non-transient OS error occurs.
        """
        # Quick check: USB must be fully enumerated before we try to write.
        if _read_udc_state() != "configured":
            return

        # Reconnect if needed (e.g. after a USB cable re-plug).
        if self.disconnected and not self._try_reconnect():
            return

        if self.file is None:
            return

        deadline = time.monotonic() + self._WRITE_TIMEOUT_S
        while not self._stop.is_set():
            try:
                os.write(self.file, report)
                return  # Success
            except BlockingIOError:
                # HID gadget kernel buffer full: wait one polling interval.
                if time.monotonic() >= deadline:
                    logger.warning(
                        "HID %s: write timed out after %dms — dropping report",
                        self.device_path, int(self._WRITE_TIMEOUT_S * 1000))
                    return
                time.sleep(self._WRITE_RETRY_S)
            except OSError as e:
                self._handle_write_error(e, time.monotonic_ns())
                return

    # ------------------------------------------------------------------
    # Error / reconnect helpers (called from sender thread)
    # ------------------------------------------------------------------

    def _handle_write_error(self, err: OSError, now: int) -> None:
        """Handle write errors with appropriate response."""
        if err.errno in (errno_mod.EBADF, errno_mod.EIO, errno_mod.EPIPE):
            self._mark_disconnected(now)
        else:
            if now - self.last_error_ns >= self.RECONNECT_INTERVAL_MS * 1_000_000:
                self.last_error_ns = now
                logger.error("HID %s write error: %s, marking disconnected",
                             self.device_path, err)
            self._mark_disconnected(now)

    def _mark_disconnected(self, now: int) -> None:
        """Mark device as disconnected."""
        self.close()
        self.disconnected = True

    def _try_reconnect(self) -> bool:
        """Try to reconnect to the HID device."""
        state = _read_udc_state()
        if state != "configured":
            return False

        try:
            self.open()
            logger.info("HID %s reconnected", self.device_path)
            return True
        except OSError:
            return False

    def deinit(self) -> None:
        """Stop the sender thread and clean up resources."""
        self._stop.set()
        # Unblock the thread if it is waiting on queue.get()
        try:
            self._queue.put_nowait(None)
        except queue_module.Full:
            pass
        self._thread.join(timeout=2.0)
        self.close()


# ============================================================================
# HidKeyboard
# ============================================================================


class HidKeyboard:
    """HID keyboard state and device management.

    Modifier keys are tracked individually by key code (left/right)
    to avoid conflicts between aggregate browser flags and specific
    modifier key events.
    """

    def __init__(self):
        self.device = HidDevice(HIDG_KEYBOARD)
        self.pressed_keys = [0] * 6
        self.modifier_state = 0
        self._pressed_modifiers: set[int] = set()

    def open(self) -> None:
        """Open the keyboard HID device."""
        self.device.open()

    def deinit(self) -> None:
        """Clean up resources."""
        self.device.deinit()

    def _rebuild_modifier_state(self) -> None:
        """Rebuild modifier_state from tracked pressed modifier keys."""
        self.modifier_state = 0
        for bit in self._pressed_modifiers:
            self.modifier_state |= bit

    def key_down(self, code: str, modifiers: ModifierFlags) -> None:
        """Handle key down event.

        Args:
            code: KeyboardEvent.code value.
            modifiers: Current modifier key states from the browser.
        """
        mod_bit = _get_modifier_bit(code)
        if mod_bit is not None:
            # Track the specific modifier key press
            self._pressed_modifiers.add(mod_bit)
            self._rebuild_modifier_state()
        else:
            # For non-modifier keys, use browser flags for modifier state
            self._sync_modifiers_from_flags(modifiers)
            scancode = _get_scancode(code)
            if scancode is not None:
                for i in range(6):
                    if self.pressed_keys[i] == 0:
                        self.pressed_keys[i] = scancode
                        break
                    elif self.pressed_keys[i] == scancode:
                        break

        self._send_report()

    def key_up(self, code: str, modifiers: ModifierFlags) -> None:
        """Handle key up event.

        Args:
            code: KeyboardEvent.code value.
            modifiers: Current modifier key states from the browser.
        """
        mod_bit = _get_modifier_bit(code)
        if mod_bit is not None:
            # Remove the specific modifier key
            self._pressed_modifiers.discard(mod_bit)
            self._rebuild_modifier_state()
        else:
            # For non-modifier keys, use browser flags for modifier state
            self._sync_modifiers_from_flags(modifiers)
            scancode = _get_scancode(code)
            if scancode is not None:
                for i in range(6):
                    if self.pressed_keys[i] == scancode:
                        self.pressed_keys[i] = 0
                        break

        self._send_report()

    def _sync_modifiers_from_flags(self, modifiers: ModifierFlags) -> None:
        """Sync modifier state from browser aggregate flags.

        Only used for non-modifier key events where we don't have
        specific left/right key information.
        """
        self.modifier_state = 0
        if modifiers.ctrl:
            self.modifier_state |= Modifiers.LEFT_CTRL
        if modifiers.shift:
            self.modifier_state |= Modifiers.LEFT_SHIFT
        if modifiers.alt:
            self.modifier_state |= Modifiers.LEFT_ALT
        if modifiers.meta:
            self.modifier_state |= Modifiers.LEFT_GUI
        # Merge with explicitly tracked modifier keys
        for bit in self._pressed_modifiers:
            self.modifier_state |= bit

    def _send_report(self) -> None:
        """Send the current keyboard state as a HID report."""
        report = bytes([
            self.modifier_state,
            0,  # Reserved
            self.pressed_keys[0],
            self.pressed_keys[1],
            self.pressed_keys[2],
            self.pressed_keys[3],
            self.pressed_keys[4],
            self.pressed_keys[5],
        ])
        self.device.write(report)

    def release_all(self) -> None:
        """Release all keys."""
        self.pressed_keys = [0] * 6
        self.modifier_state = 0
        self._pressed_modifiers.clear()
        self._send_report()


# ============================================================================
# HidMouse
# ============================================================================


class HidMouse:
    """HID Mouse state for absolute positioning."""

    def __init__(self):
        self.device = HidDevice(HIDG_MOUSE)
        self.button_state = 0
        self.last_x = 0
        self.last_y = 0

    def open(self) -> None:
        """Open the mouse HID device."""
        self.device.open()

    def deinit(self) -> None:
        """Clean up resources."""
        self.device.deinit()

    def move(self, x: int, y: int) -> None:
        """Move mouse to absolute position.

        Args:
            x: X position (0-32767).
            y: Y position (0-32767).
        """
        self.last_x = x & 0xFFFF
        self.last_y = y & 0xFFFF
        self._send_report()

    def click(self, button: int, pressed: bool) -> None:
        """Handle mouse button click.

        Args:
            button: Button number (0=left, 1=middle, 2=right).
            pressed: True if button pressed, False if released.
        """
        bit_map = {
            0: MouseButtons.LEFT,
            1: MouseButtons.MIDDLE,
            2: MouseButtons.RIGHT,
        }
        bit = bit_map.get(button)
        if bit is None:
            return

        if pressed:
            self.button_state |= bit
        else:
            self.button_state &= ~bit
        self._send_report()

    def wheel(self, delta: int) -> None:
        """Handle mouse wheel event.

        Args:
            delta: Wheel delta (-127 to 127).
        """
        delta = max(-127, min(127, delta))
        self._send_wheel_report(delta)

    def _send_report(self) -> None:
        """Send the current mouse state as a HID report."""
        report = struct.pack('<BHHB',
                             self.button_state,
                             self.last_x,
                             self.last_y,
                             0)  # Wheel = 0
        self.device.write(report)

    def _send_wheel_report(self, wheel_delta: int) -> None:
        """Send a mouse report with wheel data."""
        report = struct.pack('<BHHb',
                             self.button_state,
                             self.last_x,
                             self.last_y,
                             wheel_delta)
        self.device.write(report)

    def release_all(self) -> None:
        """Release all buttons."""
        self.button_state = 0
        self._send_report()


# ============================================================================
# ConfigFS Gadget Setup
# ============================================================================


def _write_file(path: str, content: str | bytes) -> None:
    """Write content to a file (sysfs/configfs).

    Args:
        path: Absolute file path.
        content: String or bytes to write.

    Raises:
        OSError: If writing fails.
    """
    try:
        if isinstance(content, bytes):
            with open(path, "wb") as f:
                f.write(content)
        else:
            with open(path, "w", encoding="ascii") as f:
                f.write(content)
    except OSError as e:
        logger.error("Failed to write to %s: %s", path, e)
        raise


def _make_dir_recursive(path: str) -> None:
    """Create directory recursively.

    Args:
        path: Directory path to create.

    Raises:
        OSError: If creation fails.
    """
    os.makedirs(path, exist_ok=True)


def _activate_gadget() -> None:
    """Find UDC and activate the gadget.

    Raises:
        RuntimeError: If no UDC is found.
    """
    global _g_udc_name

    udc_dir = "/sys/class/udc"
    try:
        entries = os.listdir(udc_dir)
    except OSError as e:
        logger.error("Failed to open %s: %s", udc_dir, e)
        raise RuntimeError(f"Failed to open {udc_dir}") from e

    udc_name = None
    for entry in entries:
        entry_path = os.path.join(udc_dir, entry)
        if os.path.isdir(entry_path) or os.path.islink(entry_path):
            udc_name = entry
            break

    if udc_name is None:
        logger.error("No UDC found in %s", udc_dir)
        raise RuntimeError("No UDC found")

    # Save UDC name for later state queries
    _g_udc_name = udc_name

    # Write UDC name to activate gadget
    _write_file(os.path.join(GADGET_PATH, "UDC"), udc_name)
    logger.info("Activated gadget with UDC: %s", udc_name)


def _create_gadget() -> None:
    """Create and configure the USB HID gadget through ConfigFS."""
    # Create gadget directory (exist_ok=True to handle races)
    os.makedirs(GADGET_PATH, exist_ok=True)

    # Write USB descriptor values
    _write_file(os.path.join(GADGET_PATH, "idVendor"), "0x1d6b")  # Linux Foundation
    _write_file(os.path.join(GADGET_PATH, "idProduct"), "0x0104")  # Multifunction Composite
    _write_file(os.path.join(GADGET_PATH, "bcdDevice"), "0x0100")  # v1.0.0
    _write_file(os.path.join(GADGET_PATH, "bcdUSB"), "0x0200")  # USB 2.0

    # Create strings directory (English - 0x409)
    strings_path = os.path.join(GADGET_PATH, "strings", "0x409")
    _make_dir_recursive(strings_path)
    _write_file(os.path.join(strings_path, "serialnumber"), "mykvm001")
    _write_file(os.path.join(strings_path, "manufacturer"), "MYKVM")
    _write_file(os.path.join(strings_path, "product"), "MYKVM USB HID")

    # Create configuration
    config_path = os.path.join(GADGET_PATH, "configs", "c.1")
    config_strings_path = os.path.join(config_path, "strings", "0x409")
    _make_dir_recursive(config_strings_path)
    _write_file(os.path.join(config_strings_path, "configuration"),
                "Config 1: HID Keyboard+Mouse")
    _write_file(os.path.join(config_path, "MaxPower"), "250")

    # Create Keyboard HID function (hid.usb0)
    kbd_path = os.path.join(GADGET_PATH, "functions", "hid.usb0")
    _make_dir_recursive(kbd_path)
    _write_file(os.path.join(kbd_path, "protocol"), "1")  # Keyboard
    _write_file(os.path.join(kbd_path, "subclass"), "1")  # Boot Interface
    _write_file(os.path.join(kbd_path, "report_length"), "8")
    _write_file(os.path.join(kbd_path, "report_desc"), KEYBOARD_REPORT_DESC)

    # Create symlink for keyboard
    try:
        os.symlink(kbd_path, os.path.join(config_path, "hid.usb0"))
    except FileExistsError:
        pass

    # Create Mouse HID function (hid.usb1)
    mouse_path = os.path.join(GADGET_PATH, "functions", "hid.usb1")
    _make_dir_recursive(mouse_path)
    _write_file(os.path.join(mouse_path, "protocol"), "2")  # Mouse
    _write_file(os.path.join(mouse_path, "subclass"), "1")  # Boot Interface
    _write_file(os.path.join(mouse_path, "report_length"), "6")
    _write_file(os.path.join(mouse_path, "report_desc"), MOUSE_REPORT_DESC)

    # Create symlink for mouse
    try:
        os.symlink(mouse_path, os.path.join(config_path, "hid.usb1"))
    except FileExistsError:
        pass

    # Activate gadget
    _activate_gadget()

    logger.info("USB HID Gadget setup complete! (keyboard=%s, mouse=%s)",
                HIDG_KEYBOARD, HIDG_MOUSE)


def setup_gadget() -> None:
    """Setup USB HID Gadget through ConfigFS.

    Requires root privileges.
    """
    logger.info("Setting up USB HID Gadget (keyboard + mouse)...")

    # Check if gadget already exists
    if not os.path.exists(GADGET_PATH):
        _create_gadget()
        return

    # Gadget exists, check if both hidg devices exist
    if not os.path.exists(HIDG_KEYBOARD):
        logger.info("Gadget directory exists but %s not found", HIDG_KEYBOARD)
        logger.info("Trying to activate gadget...")
        _activate_gadget()
        return

    if not os.path.exists(HIDG_MOUSE):
        logger.info("Gadget directory exists but %s not found", HIDG_MOUSE)
        logger.info("Trying to activate gadget...")
        _activate_gadget()
        return

    logger.info("USB HID Gadget already configured, reusing existing setup")


def cleanup_gadget() -> None:
    """Cleanup/remove the USB gadget."""
    if not os.path.exists(GADGET_PATH):
        logger.info("USB HID Gadget not present, skipping cleanup")
        return

    logger.info("Cleaning up USB HID Gadget...")

    # 1. Disable the gadget
    try:
        _write_file(os.path.join(GADGET_PATH, "UDC"), "")
    except OSError:
        pass

    # 2. Remove functions from configurations (symlinks)
    for name in ["hid.usb0", "hid.usb1"]:
        try:
            os.remove(os.path.join(GADGET_PATH, "configs", "c.1", name))
        except OSError:
            pass

    # 3. Remove strings directories in configurations
    try:
        os.rmdir(os.path.join(GADGET_PATH, "configs", "c.1", "strings", "0x409"))
    except OSError:
        pass

    # 4. Remove the configurations
    try:
        os.rmdir(os.path.join(GADGET_PATH, "configs", "c.1"))
    except OSError:
        pass

    # 5. Remove functions
    for name in ["hid.usb0", "hid.usb1"]:
        try:
            os.rmdir(os.path.join(GADGET_PATH, "functions", name))
        except OSError:
            pass

    # 6. Remove strings directories in the gadget
    try:
        os.rmdir(os.path.join(GADGET_PATH, "strings", "0x409"))
    except OSError:
        pass

    # 7. Remove the gadget
    try:
        os.rmdir(GADGET_PATH)
    except OSError:
        pass

    logger.info("USB HID Gadget cleaned up")
