"""Tests for WebSocket message handler."""

import json

import pytest

from mykvm.usb import Modifiers
from mykvm.ws_handler import handle_message


class MockKeyboard:
    """Mock keyboard for testing."""

    def __init__(self):
        self.events = []

    def key_down(self, code, modifiers):
        self.events.append(("keydown", code, modifiers))

    def key_up(self, code, modifiers):
        self.events.append(("keyup", code, modifiers))


class MockMouse:
    """Mock mouse for testing."""

    def __init__(self):
        self.events = []

    def move(self, x, y):
        self.events.append(("move", x, y))

    def click(self, button, pressed):
        self.events.append(("click", button, pressed))

    def wheel(self, delta):
        self.events.append(("wheel", delta))


class MockServer:
    """Mock server with keyboard and mouse."""

    def __init__(self):
        self.keyboard = MockKeyboard()
        self.mouse = MockMouse()


class TestHandleKeyboardEvents:
    """Test keyboard event handling."""

    def test_keydown(self):
        server = MockServer()
        msg = json.dumps({
            "type": "keyboard",
            "event": "keydown",
            "code": "KeyA",
            "modifiers": {"ctrl": False, "alt": False, "shift": False, "meta": False},
        })
        handle_message(server, msg)
        assert len(server.keyboard.events) == 1
        event_type, code, mods = server.keyboard.events[0]
        assert event_type == "keydown"
        assert code == "KeyA"
        assert not mods.ctrl

    def test_keyup(self):
        server = MockServer()
        msg = json.dumps({
            "type": "keyboard",
            "event": "keyup",
            "code": "KeyA",
            "modifiers": {"ctrl": False, "alt": False, "shift": False, "meta": False},
        })
        handle_message(server, msg)
        assert len(server.keyboard.events) == 1
        assert server.keyboard.events[0][0] == "keyup"

    def test_keydown_with_modifiers(self):
        server = MockServer()
        msg = json.dumps({
            "type": "keyboard",
            "event": "keydown",
            "code": "KeyC",
            "modifiers": {"ctrl": True, "alt": False, "shift": False, "meta": False},
        })
        handle_message(server, msg)
        _, _, mods = server.keyboard.events[0]
        assert mods.ctrl
        assert not mods.alt

    def test_keydown_bytes_input(self):
        """Test handling binary input (bytes)."""
        server = MockServer()
        msg = json.dumps({
            "type": "keyboard",
            "event": "keydown",
            "code": "KeyA",
            "modifiers": {},
        }).encode()
        handle_message(server, msg)
        assert len(server.keyboard.events) == 1


class TestHandleMouseEvents:
    """Test mouse event handling."""

    def test_move(self):
        server = MockServer()
        msg = json.dumps({
            "type": "mouse",
            "event": "move",
            "x": 100,
            "y": 200,
        })
        handle_message(server, msg)
        assert len(server.mouse.events) == 1
        assert server.mouse.events[0] == ("move", 100, 200)

    def test_button_down(self):
        server = MockServer()
        msg = json.dumps({
            "type": "mouse",
            "event": "down",
            "button": 0,
        })
        handle_message(server, msg)
        assert server.mouse.events[0] == ("click", 0, True)

    def test_button_up(self):
        server = MockServer()
        msg = json.dumps({
            "type": "mouse",
            "event": "up",
            "button": 0,
        })
        handle_message(server, msg)
        assert server.mouse.events[0] == ("click", 0, False)

    def test_wheel(self):
        server = MockServer()
        msg = json.dumps({
            "type": "mouse",
            "event": "wheel",
            "delta": -3,
        })
        handle_message(server, msg)
        assert server.mouse.events[0] == ("wheel", -3)

    def test_wheel_clamped(self):
        server = MockServer()
        msg = json.dumps({
            "type": "mouse",
            "event": "wheel",
            "delta": 500,
        })
        handle_message(server, msg)
        assert server.mouse.events[0] == ("wheel", 127)

    def test_right_click(self):
        server = MockServer()
        msg = json.dumps({
            "type": "mouse",
            "event": "down",
            "button": 2,
        })
        handle_message(server, msg)
        assert server.mouse.events[0] == ("click", 2, True)


class TestInvalidMessages:
    """Test handling of invalid messages."""

    def test_invalid_json(self):
        server = MockServer()
        handle_message(server, "not json")
        assert len(server.keyboard.events) == 0
        assert len(server.mouse.events) == 0

    def test_unknown_type(self):
        server = MockServer()
        msg = json.dumps({"type": "unknown"})
        handle_message(server, msg)
        assert len(server.keyboard.events) == 0
        assert len(server.mouse.events) == 0

    def test_missing_type(self):
        server = MockServer()
        msg = json.dumps({"event": "keydown"})
        handle_message(server, msg)
        # Should not crash, type defaults to None which doesn't match

    def test_empty_string(self):
        server = MockServer()
        handle_message(server, "")
        # Should not crash
