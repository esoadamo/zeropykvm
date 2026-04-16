"""WebSocket server managing clients and broadcasting H.264 data."""

import logging
import threading

logger = logging.getLogger(__name__)


class Server:
    """Manages WebSocket client connections and broadcasts video data.

    Thread-safe client management with automatic cleanup of disconnected clients.
    """

    def __init__(self, keyboard, mouse):
        """Initialize the server.

        Args:
            keyboard: HidKeyboard instance.
            mouse: HidMouse instance.
        """
        self.keyboard = keyboard
        self.mouse = mouse
        self.clients: list = []
        self._lock = threading.Lock()

    def add_client(self, ws) -> None:
        """Add a WebSocket client.

        Args:
            ws: WebSocket connection object.
        """
        with self._lock:
            self.clients.append(ws)
            logger.info("Client connected. Total clients: %d", len(self.clients))

    def remove_client(self, ws) -> None:
        """Remove a WebSocket client.

        Args:
            ws: WebSocket connection object to remove.
        """
        with self._lock:
            try:
                self.clients.remove(ws)
                logger.info("Client disconnected. Total clients: %d", len(self.clients))
            except ValueError:
                pass

    def broadcast(self, data: bytes) -> None:
        """Broadcast binary data to all connected clients.

        Automatically removes clients that fail to receive data.

        Args:
            data: Binary data to broadcast.
        """
        with self._lock:
            failed_indices = []
            for i, client in enumerate(self.clients):
                try:
                    client.send(data)
                except Exception:
                    failed_indices.append(i)

            # Remove failed clients in reverse order
            for i in reversed(failed_indices):
                self.clients.pop(i)

            if failed_indices:
                logger.info("Removed %d disconnected clients", len(failed_indices))

    def deinit(self) -> None:
        """Clean up resources."""
        with self._lock:
            self.clients.clear()
