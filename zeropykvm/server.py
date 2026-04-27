"""WebSocket server managing clients and broadcasting H.264 data."""

import logging
import threading

logger = logging.getLogger(__name__)

# NAL unit types
_NAL_IDR = 5
_NAL_SPS = 7
_NAL_PPS = 8


def _contains_nal_type(data: bytes, nal_type: int) -> bool:
    """Return True if Annex-B data contains a NAL unit of the given type."""
    i = 0
    while i + 4 < len(data):
        if data[i:i+4] == b'\x00\x00\x00\x01' and (data[i+4] & 0x1f) == nal_type:
            return True
        i += 1
    return False


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
        # Last complete keyframe (SPS+PPS+IDR) for late-joining clients
        self._last_keyframe: bytes | None = None
        self._kf_lock = threading.Lock()
        # Event to request a forced keyframe from the video thread
        self.keyframe_requested = threading.Event()
        # Event set by clients when they are falling behind (decoder backlog);
        # the video thread will skip capture frames while this is set, subject
        # to the minimum frame-rate floor.
        self.skip_frames_requested = threading.Event()

    def add_client(self, ws) -> None:
        """Add a WebSocket client and send the last keyframe if available.

        Args:
            ws: WebSocket connection object.
        """
        with self._lock:
            self.clients.append(ws)
            logger.info("Client connected. Total clients: %d", len(self.clients))

        # Request the video thread to force a new keyframe for this client
        self.keyframe_requested.set()

        # Immediately send the last cached keyframe so the client doesn't wait
        with self._kf_lock:
            kf = self._last_keyframe
        if kf is not None:
            try:
                ws.send(kf)
            except Exception:
                pass

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

    def update_keyframe(self, data: bytes) -> None:
        """Cache a complete keyframe (SPS+PPS+IDR) for late-joining clients.

        Args:
            data: Encoded H.264 Annex-B data containing an IDR frame.
        """
        with self._kf_lock:
            self._last_keyframe = data

    def broadcast(self, data: bytes) -> None:
        """Broadcast binary data to all connected clients.

        Automatically removes clients that fail to receive data.
        Copies client list under lock, then sends without holding
        the lock to avoid blocking other operations.

        Args:
            data: Binary data to broadcast.
        """
        with self._lock:
            clients = list(self.clients)

        failed_clients = []
        for client in clients:
            try:
                client.send(data)
            except Exception:
                failed_clients.append(client)

        if failed_clients:
            removed_count = 0
            with self._lock:
                for client in failed_clients:
                    try:
                        self.clients.remove(client)
                        removed_count += 1
                    except ValueError:
                        pass

            if removed_count:
                logger.info(
                    "Removed %d disconnected clients", removed_count
                )

    def deinit(self) -> None:
        """Clean up resources."""
        with self._lock:
            self.clients.clear()
