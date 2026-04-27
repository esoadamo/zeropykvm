"""WebSocket message handler for keyboard and mouse events."""

import json
import logging

from .usb import ModifierFlags

logger = logging.getLogger(__name__)


def handle_message(server, websocket, data: str | bytes) -> None:
    """Handle a WebSocket message from the client.

    Dispatches keyboard, mouse, and ping events to the appropriate handler.

    Args:
        server: Server instance with keyboard and mouse.
        websocket: The WebSocket connection to send replies on.
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
    elif event_type == "ping":
        _handle_ping(websocket, msg)
    elif event_type == "frameskip":
        _handle_frameskip(server, msg)
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
        # Signal the video thread to send a frame immediately so the user
        # sees the result of their key press even while frameskip is active.
        server.input_event_pending.set()
    elif event == "keyup":
        server.keyboard.key_up(code, modifiers)


def _handle_ping(websocket, msg: dict) -> None:
    """Handle a ping message by sending a pong reply.

    Args:
        websocket: The WebSocket connection to send the pong on.
        msg: Parsed ping message containing a 'ts' timestamp.
    """
    pong = json.dumps({"type": "pong", "ts": msg.get("ts")})
    try:
        websocket.send(pong)
    except Exception as e:
        logger.warning("Failed to send pong: %s", e)


def _handle_frameskip(server, msg: dict) -> None:
    """Handle a frameskip message from the client.

    When ``skip`` is True the client is falling behind (decoder backlog) and
    the video thread should throttle its send rate to ``fps`` frames-per-second
    so the network pipe can drain.  When False (or fps==0) the client has
    caught up and full-rate streaming can resume.

    Args:
        server: Server instance with set_skip method.
        msg: Parsed frameskip message with boolean ``skip`` and optional
             integer ``fps`` (target send rate while skipping, default 2).
    """
    if msg.get("skip"):
        fps = int(msg.get("fps", 2))
        fps = max(1, fps)  # never go below 1 fps
        server.set_skip(fps)
        logger.debug("Frame-skip requested by client at %d fps", fps)
    else:
        server.set_skip(0)
        logger.debug("Frame-skip cleared by client")


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
        # Signal the video thread: user clicked → send a frame immediately
        # so pointer/UI feedback is visible without waiting for the skip timer.
        server.input_event_pending.set()
    elif event == "up":
        button = msg.get("button", 0)
        server.mouse.click(button, False)
    elif event == "wheel":
        delta = msg.get("delta", 0)
        delta = max(-127, min(127, delta))
        server.mouse.wheel(delta)
