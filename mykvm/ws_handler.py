"""WebSocket message handler for keyboard and mouse events."""

import json
import logging

from .usb import ModifierFlags

logger = logging.getLogger(__name__)


def handle_message(server, data: str | bytes) -> None:
    """Handle a WebSocket message from the client.

    Dispatches keyboard and mouse events to the appropriate HID device.

    Args:
        server: Server instance with keyboard and mouse.
        data: Raw message data (JSON string).
    """
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")

    try:
        msg = json.loads(data)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse JSON: %s", e)
        return

    event_type = msg.get("type")
    if event_type == "keyboard":
        _handle_keyboard_event(server, msg)
    elif event_type == "mouse":
        _handle_mouse_event(server, msg)
    else:
        logger.warning("Unknown event type: %s", event_type)


def _handle_keyboard_event(server, msg: dict) -> None:
    """Handle a keyboard event.

    Args:
        server: Server instance with keyboard.
        msg: Parsed keyboard event message.
    """
    event = msg.get("event", "")
    code = msg.get("code", "")
    mods = msg.get("modifiers", {})

    modifiers = ModifierFlags(
        ctrl=mods.get("ctrl", False),
        alt=mods.get("alt", False),
        shift=mods.get("shift", False),
        meta=mods.get("meta", False),
    )

    if event == "keydown":
        server.keyboard.key_down(code, modifiers)
    elif event == "keyup":
        server.keyboard.key_up(code, modifiers)


def _handle_mouse_event(server, msg: dict) -> None:
    """Handle a mouse event.

    Args:
        server: Server instance with mouse.
        msg: Parsed mouse event message.
    """
    event = msg.get("event", "")

    if event == "move":
        x = msg.get("x", 0)
        y = msg.get("y", 0)
        server.mouse.move(x, y)
    elif event == "down":
        button = msg.get("button", 0)
        server.mouse.click(button, True)
    elif event == "up":
        button = msg.get("button", 0)
        server.mouse.click(button, False)
    elif event == "wheel":
        delta = msg.get("delta", 0)
        delta = max(-127, min(127, delta))
        server.mouse.wheel(delta)
