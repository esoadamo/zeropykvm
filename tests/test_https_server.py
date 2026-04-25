"""Tests for HTTPS server module.

WebSocket protocol handling (framing, handshake, masking, etc.) is
delegated to the well-tested websockets library. These tests verify
our routing and integration logic.
"""

from zeropykvm.https_server import _make_process_request
from zeropykvm.http_handler import HttpHandler


class MockRequest:
    """Mock HTTP request for testing process_request routing."""

    def __init__(self, path="/", headers=None):
        self.path = path
        self.headers = headers or {}


class TestProcessRequest:
    """Test process_request callback routing logic."""

    def test_websocket_upgrade_returns_none(self):
        """WebSocket upgrade requests should return None to proceed."""
        handler = HttpHandler()
        process_request = _make_process_request(handler)
        request = MockRequest(
            path="/",
            headers={"Upgrade": "websocket"},
        )
        assert process_request(None, request) is None

    def test_websocket_upgrade_case_insensitive(self):
        """WebSocket upgrade detection should be case-insensitive."""
        handler = HttpHandler()
        process_request = _make_process_request(handler)
        request = MockRequest(
            path="/",
            headers={"Upgrade": "WebSocket"},
        )
        assert process_request(None, request) is None

    def test_http_request_returns_response(self):
        """Regular HTTP requests should return a Response."""
        handler = HttpHandler()
        process_request = _make_process_request(handler)
        request = MockRequest(path="/index.html")
        response = process_request(None, request)
        assert response is not None
        assert response.status_code == 404  # No files loaded
        assert response.body == b"404 Not Found"

    def test_http_root_returns_response(self):
        """Root path should be handled."""
        handler = HttpHandler()
        process_request = _make_process_request(handler)
        request = MockRequest(path="/")
        response = process_request(None, request)
        assert response is not None

    def test_no_upgrade_header_serves_http(self):
        """Requests without Upgrade header should be served as HTTP."""
        handler = HttpHandler()
        process_request = _make_process_request(handler)
        request = MockRequest(
            path="/",
            headers={"Host": "example.com"},
        )
        response = process_request(None, request)
        assert response is not None

    def test_empty_upgrade_header_serves_http(self):
        """Requests with empty Upgrade header should be served as HTTP."""
        handler = HttpHandler()
        process_request = _make_process_request(handler)
        request = MockRequest(
            path="/",
            headers={"Upgrade": ""},
        )
        response = process_request(None, request)
        assert response is not None

    def test_non_websocket_upgrade_serves_http(self):
        """Non-WebSocket Upgrade requests should be served as HTTP."""
        handler = HttpHandler()
        process_request = _make_process_request(handler)
        request = MockRequest(
            path="/",
            headers={"Upgrade": "h2c"},
        )
        response = process_request(None, request)
        assert response is not None

    def test_response_reason_phrase(self):
        """Response should have correct reason phrase."""
        handler = HttpHandler()
        process_request = _make_process_request(handler)
        request = MockRequest(path="/nonexistent")
        response = process_request(None, request)
        assert response.reason_phrase == "Not Found"
