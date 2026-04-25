"""MyKVM main entry point.

A KVM-over-IP solution running on Raspberry Pi Zero 2 W,
featuring hardware H.264 encoding and a built-in web frontend.
"""

import logging
import os
import signal
import sys
import threading

from .args import parse as parse_args
from .edid import EdidPreset, set_edid_with_retry, wait_for_signal
from .epaper import Display
from .http_handler import HttpHandler
from .https_server import run as run_https_server
from .server import Server
from .usb import HidKeyboard, HidMouse, cleanup_gadget, setup_gadget
from .utils import get_local_ip
from .video import run as run_video

logger = logging.getLogger(__name__)

# Global references for signal handler cleanup
_g_display: Display | None = None
_g_hid_keyboard: HidKeyboard | None = None
_g_hid_mouse: HidMouse | None = None


def _handle_signal(signum, frame):
    """Signal handler for graceful shutdown."""
    logger.info("Received signal %d, shutting down...", signum)

    if _g_hid_keyboard is not None:
        _g_hid_keyboard.deinit()
    if _g_hid_mouse is not None:
        _g_hid_mouse.deinit()

    cleanup_gadget()

    if _g_display is not None:
        _g_display.shutdown()

    sys.exit(0)


def main():
    """Main entry point for MyKVM."""
    global _g_display, _g_hid_keyboard, _g_hid_mouse

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    # Parse command-line arguments
    config = parse_args()

    # Initialize e-Paper display
    display = Display(enabled=not config.no_epaper)
    _g_display = display

    # Set up signal handlers
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Set EDID
    edid_ok = True
    try:
        set_edid_with_retry(config.subdev, EdidPreset.P1080_25)
        # Wait for the source to re-negotiate to the new EDID timings.
        # Without this pause the source may still be at 60fps when we probe.
        import time as _time
        _time.sleep(3)
    except Exception as e:
        logger.warning("Failed to set EDID: %s", e)
        edid_ok = False
    display.update_edid_status(edid_ok)

    # Wait for HDMI signal briefly so we have one on startup if possible
    logger.info("Waiting for HDMI signal...")
    signal_info = None
    try:
        signal_info = wait_for_signal(config.device, config.subdev, 5)
        logger.info(
            "HDMI signal detected: %dx%d @ %dfps",
            signal_info.width, signal_info.height, signal_info.fps,
        )
        display.update_hdmi_status(True)
    except (TimeoutError, OSError) as e:
        logger.warning("No HDMI signal detected on startup: %s", e)
        display.update_hdmi_status(False)

    # Set up USB HID
    hid_keyboard = HidKeyboard()
    _g_hid_keyboard = hid_keyboard
    hid_mouse = HidMouse()
    _g_hid_mouse = hid_mouse

    hid_ok = True
    try:
        setup_gadget()
    except Exception as e:
        logger.warning("Failed to setup USB gadget: %s", e)
        hid_ok = False

    try:
        hid_keyboard.open()
    except Exception as e:
        logger.warning("Failed to open HID keyboard device: %s", e)
        hid_ok = False
    try:
        hid_mouse.open()
    except Exception as e:
        logger.warning("Failed to open HID mouse device: %s", e)
        hid_ok = False
    display.update_hid_status(hid_ok)

    # Create server
    server = Server(hid_keyboard, hid_mouse)

    # Set up HTTP handler
    # Look for web dist in common locations
    web_dist_path = None
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "web", "dist.tar"),
        os.path.join(os.path.dirname(__file__), "..", "web", "dist"),
        "web/dist.tar",
        "web/dist",
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            web_dist_path = candidate
            break

    http_handler = HttpHandler(web_dist_path)

    # Start V4L2 video thread
    v4l2_thread = threading.Thread(
        target=run_video,
        args=(server, config.device, config.encoder, config.bitrate,
              config.subdev, signal_info),
        daemon=True,
    )
    v4l2_thread.start()

    # Show status on e-paper
    local_ip = get_local_ip() or config.listen
    display.show_status(local_ip, config.port)
    display.sleep()

    # Start HTTPS server (blocks)
    logger.info("Server init: https://%s:%d", config.listen, config.port)
    run_https_server(
        server=server,
        listen_addr=config.listen,
        port=config.port,
        cert_path=config.tls_cert_path,
        key_path=config.tls_key_path,
        http_handler=http_handler,
    )


if __name__ == "__main__":
    main()
