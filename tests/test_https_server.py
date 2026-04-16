"""Tests for HTTPS server module."""

import hashlib
import base64

from mykvm.https_server import (
    _is_websocket_upgrade,
    _extract_ws_key,
    _make_ws_accept_key,
    _parse_request_path,
)


class TestIsWebSocketUpgrade:
    """Test WebSocket upgrade detection."""

    def test_valid_upgrade(self):
        request = (
            b"GET / HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n"
            b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            b"Sec-WebSocket-Version: 13\r\n"
            b"\r\n"
        )
        assert _is_websocket_upgrade(request) is True

    def test_no_upgrade_header(self):
        request = (
            b"GET / HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"Connection: Upgrade\r\n"
            b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            b"\r\n"
        )
        assert _is_websocket_upgrade(request) is False

    def test_no_connection_upgrade(self):
        request = (
            b"GET / HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"Upgrade: websocket\r\n"
            b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            b"\r\n"
        )
        assert _is_websocket_upgrade(request) is False

    def test_no_ws_key(self):
        request = (
            b"GET / HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n"
            b"\r\n"
        )
        assert _is_websocket_upgrade(request) is False

    def test_regular_http(self):
        request = (
            b"GET /index.html HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"\r\n"
        )
        assert _is_websocket_upgrade(request) is False

    def test_case_insensitive_headers(self):
        request = (
            b"GET / HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"upgrade: WebSocket\r\n"
            b"connection: Upgrade\r\n"
            b"sec-websocket-key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            b"\r\n"
        )
        assert _is_websocket_upgrade(request) is True

    def test_empty_request(self):
        assert _is_websocket_upgrade(b"") is False


class TestExtractWsKey:
    """Test WebSocket key extraction."""

    def test_extract_key(self):
        request = (
            b"GET / HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            b"\r\n"
        )
        assert _extract_ws_key(request) == "dGhlIHNhbXBsZSBub25jZQ=="

    def test_no_key(self):
        request = b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n"
        assert _extract_ws_key(request) == ""


class TestMakeWsAcceptKey:
    """Test WebSocket accept key generation."""

    def test_rfc_example(self):
        """Test with the example from RFC 6455."""
        key = "dGhlIHNhbXBsZSBub25jZQ=="
        expected = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
        assert _make_ws_accept_key(key) == expected

    def test_deterministic(self):
        """Test that the same key always produces the same result."""
        key = "x3JJHMbDL1EzLkh9GBhXDw=="
        result1 = _make_ws_accept_key(key)
        result2 = _make_ws_accept_key(key)
        assert result1 == result2

    def test_different_keys(self):
        """Test that different keys produce different results."""
        result1 = _make_ws_accept_key("key1")
        result2 = _make_ws_accept_key("key2")
        assert result1 != result2


class TestParseRequestPath:
    """Test HTTP request path parsing."""

    def test_root(self):
        request = b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n"
        assert _parse_request_path(request) == "/"

    def test_index(self):
        request = b"GET /index.html HTTP/1.1\r\nHost: example.com\r\n\r\n"
        assert _parse_request_path(request) == "/index.html"

    def test_nested_path(self):
        request = b"GET /assets/style.css HTTP/1.1\r\nHost: example.com\r\n\r\n"
        assert _parse_request_path(request) == "/assets/style.css"

    def test_empty(self):
        assert _parse_request_path(b"") == "/"

    def test_malformed(self):
        assert _parse_request_path(b"invalid") == "/"
