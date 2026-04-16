"""Tests for server module."""

import threading

from mykvm.server import Server


class MockKeyboard:
    pass


class MockMouse:
    pass


class MockWebSocket:
    """Mock WebSocket connection for testing."""

    def __init__(self, should_fail=False):
        self.sent_data = []
        self.should_fail = should_fail

    def send(self, data):
        if self.should_fail:
            raise ConnectionError("Mock connection error")
        self.sent_data.append(data)


class TestServer:
    """Test Server client management and broadcasting."""

    def test_init(self):
        server = Server(MockKeyboard(), MockMouse())
        assert len(server.clients) == 0

    def test_add_client(self):
        server = Server(MockKeyboard(), MockMouse())
        ws = MockWebSocket()
        server.add_client(ws)
        assert len(server.clients) == 1

    def test_add_multiple_clients(self):
        server = Server(MockKeyboard(), MockMouse())
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        server.add_client(ws1)
        server.add_client(ws2)
        assert len(server.clients) == 2

    def test_remove_client(self):
        server = Server(MockKeyboard(), MockMouse())
        ws = MockWebSocket()
        server.add_client(ws)
        server.remove_client(ws)
        assert len(server.clients) == 0

    def test_remove_nonexistent_client(self):
        """Removing a non-existent client should not raise."""
        server = Server(MockKeyboard(), MockMouse())
        ws = MockWebSocket()
        server.remove_client(ws)  # Should not raise
        assert len(server.clients) == 0

    def test_broadcast(self):
        server = Server(MockKeyboard(), MockMouse())
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        server.add_client(ws1)
        server.add_client(ws2)

        data = b"test data"
        server.broadcast(data)

        assert ws1.sent_data == [data]
        assert ws2.sent_data == [data]

    def test_broadcast_removes_failed_clients(self):
        server = Server(MockKeyboard(), MockMouse())
        ws_ok = MockWebSocket()
        ws_fail = MockWebSocket(should_fail=True)
        server.add_client(ws_ok)
        server.add_client(ws_fail)

        server.broadcast(b"test data")

        assert len(server.clients) == 1
        assert ws_ok.sent_data == [b"test data"]

    def test_broadcast_empty_clients(self):
        server = Server(MockKeyboard(), MockMouse())
        server.broadcast(b"test data")  # Should not raise

    def test_broadcast_multiple(self):
        server = Server(MockKeyboard(), MockMouse())
        ws = MockWebSocket()
        server.add_client(ws)

        server.broadcast(b"data1")
        server.broadcast(b"data2")

        assert ws.sent_data == [b"data1", b"data2"]

    def test_thread_safety(self):
        """Test concurrent access to server."""
        server = Server(MockKeyboard(), MockMouse())
        errors = []

        def add_clients():
            try:
                for _ in range(100):
                    server.add_client(MockWebSocket())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_clients) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(server.clients) == 400

    def test_deinit(self):
        server = Server(MockKeyboard(), MockMouse())
        server.add_client(MockWebSocket())
        server.add_client(MockWebSocket())
        server.deinit()
        assert len(server.clients) == 0
