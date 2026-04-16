"""HTTPS/TLS server with WebSocket upgrade support.

Handles both HTTPS requests for the web frontend and WebSocket
connections for real-time video streaming and HID control.
"""

import hashlib
import base64
import logging
import os
import ssl
import socket
import struct
import threading

from .http_handler import HttpHandler
from .server import Server
from . import ws_handler

logger = logging.getLogger(__name__)


def _is_websocket_upgrade(request: bytes) -> bool:
    """Check if an HTTP request is a WebSocket upgrade request.

    Args:
        request: Raw HTTP request bytes.

    Returns:
        True if this is a WebSocket upgrade request.
    """
    try:
        text = request.decode("utf-8", errors="replace")
    except Exception:
        return False

    has_upgrade = False
    has_connection_upgrade = False
    has_ws_key = False

    lines = text.split("\r\n")
    for line in lines[1:]:  # Skip request line
        if not line:
            break
        if ":" in line:
            name, value = line.split(":", 1)
            name = name.strip().lower()
            value = value.strip()

            if name == "upgrade" and value.lower() == "websocket":
                has_upgrade = True
            elif name == "connection" and "upgrade" in value.lower():
                has_connection_upgrade = True
            elif name == "sec-websocket-key" and len(value) > 0:
                has_ws_key = True

    return has_upgrade and has_connection_upgrade and has_ws_key


def _extract_ws_key(request: bytes) -> str:
    """Extract Sec-WebSocket-Key from request headers."""
    text = request.decode("utf-8", errors="replace")
    for line in text.split("\r\n"):
        if ":" in line:
            name, value = line.split(":", 1)
            if name.strip().lower() == "sec-websocket-key":
                return value.strip()
    return ""


def _make_ws_accept_key(key: str) -> str:
    """Compute Sec-WebSocket-Accept value.

    Args:
        key: Sec-WebSocket-Key from client.

    Returns:
        Base64-encoded SHA-1 hash for Sec-WebSocket-Accept.
    """
    magic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    combined = (key + magic).encode("utf-8")
    sha1 = hashlib.sha1(combined).digest()
    return base64.b64encode(sha1).decode("utf-8")


def _parse_request_path(request: bytes) -> str:
    """Extract the request path from an HTTP request line.

    Args:
        request: Raw HTTP request bytes.

    Returns:
        Request path string.
    """
    try:
        text = request.decode("utf-8", errors="replace")
        first_line = text.split("\r\n")[0]
        parts = first_line.split(" ")
        if len(parts) >= 2:
            return parts[1]
    except Exception:
        pass
    return "/"


# ============================================================================
# WebSocket Frame Handling
# ============================================================================


def _read_ws_frame(conn: ssl.SSLSocket) -> tuple[int, bytes] | None:
    """Read a WebSocket frame from the connection.

    Args:
        conn: SSL socket connection.

    Returns:
        Tuple of (opcode, payload) or None if connection closed.
    """
    try:
        header = _recv_exact(conn, 2)
        if header is None:
            return None

        opcode = header[0] & 0x0F
        masked = bool(header[1] & 0x80)
        payload_len = header[1] & 0x7F

        if payload_len == 126:
            ext = _recv_exact(conn, 2)
            if ext is None:
                return None
            payload_len = struct.unpack(">H", ext)[0]
        elif payload_len == 127:
            ext = _recv_exact(conn, 8)
            if ext is None:
                return None
            payload_len = struct.unpack(">Q", ext)[0]

        mask_key = b""
        if masked:
            mask_key = _recv_exact(conn, 4)
            if mask_key is None:
                return None

        payload = _recv_exact(conn, payload_len)
        if payload is None:
            return None

        if masked:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

        return opcode, payload
    except (ConnectionError, OSError):
        return None


def _send_ws_frame(conn: ssl.SSLSocket, opcode: int, data: bytes) -> None:
    """Send a WebSocket frame.

    Args:
        conn: SSL socket connection.
        opcode: WebSocket opcode.
        data: Payload data.
    """
    frame = bytearray()
    frame.append(0x80 | opcode)  # FIN + opcode

    length = len(data)
    if length < 126:
        frame.append(length)
    elif length < 65536:
        frame.append(126)
        frame.extend(struct.pack(">H", length))
    else:
        frame.append(127)
        frame.extend(struct.pack(">Q", length))

    frame.extend(data)
    conn.sendall(bytes(frame))


def _recv_exact(conn: ssl.SSLSocket, n: int) -> bytes | None:
    """Receive exactly n bytes from the connection.

    Args:
        conn: SSL socket connection.
        n: Number of bytes to receive.

    Returns:
        Received bytes or None if connection closed.
    """
    if n == 0:
        return b""
    data = bytearray()
    while len(data) < n:
        try:
            chunk = conn.recv(n - len(data))
            if not chunk:
                return None
            data.extend(chunk)
        except (ConnectionError, OSError):
            return None
    return bytes(data)


# ============================================================================
# WebSocket Connection Wrapper (for server.broadcast compatibility)
# ============================================================================


class WebSocketConnection:
    """Wrapper around SSL socket with WebSocket frame sending.

    Used by Server.broadcast() to send binary frames to clients.
    """

    def __init__(self, conn: ssl.SSLSocket):
        self._conn = conn
        self._lock = threading.Lock()

    def send(self, data: bytes) -> None:
        """Send binary data as a WebSocket frame.

        Args:
            data: Binary data to send.

        Raises:
            ConnectionError: If sending fails.
        """
        with self._lock:
            _send_ws_frame(self._conn, 0x02, data)  # Binary frame


# ============================================================================
# Connection Handler
# ============================================================================


def _handle_websocket(conn: ssl.SSLSocket, server: Server) -> None:
    """Handle a WebSocket connection.

    Args:
        conn: SSL socket connection (after handshake).
        server: Server instance for client management.
    """
    ws_conn = WebSocketConnection(conn)
    server.add_client(ws_conn)

    try:
        while True:
            frame = _read_ws_frame(conn)
            if frame is None:
                break

            opcode, payload = frame

            if opcode == 0x01:  # Text frame
                ws_handler.handle_message(server, payload)
            elif opcode == 0x02:  # Binary frame
                ws_handler.handle_message(server, payload)
            elif opcode == 0x08:  # Close frame
                try:
                    _send_ws_frame(conn, 0x08, b"")
                except Exception:
                    pass
                break
            elif opcode == 0x09:  # Ping
                try:
                    _send_ws_frame(conn, 0x0A, payload)  # Pong
                except Exception:
                    pass
    finally:
        server.remove_client(ws_conn)


def _handle_connection(conn: ssl.SSLSocket, addr, server: Server,
                        http_handler: HttpHandler) -> None:
    """Handle a single HTTPS connection.

    Args:
        conn: SSL socket connection.
        addr: Client address.
        server: Server instance.
        http_handler: HTTP handler for static files.
    """
    try:
        # Set TCP_NODELAY
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        # Read initial request
        request = conn.recv(8192)
        if not request:
            return

        if _is_websocket_upgrade(request):
            # Perform WebSocket handshake
            ws_key = _extract_ws_key(request)
            accept_key = _make_ws_accept_key(ws_key)

            response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept_key}\r\n"
                "\r\n"
            ).encode()
            conn.sendall(response)

            _handle_websocket(conn, server)
        else:
            # Handle regular HTTP request
            request_path = _parse_request_path(request)
            status, content_type, body = http_handler.handle_request(request_path)
            response = http_handler.format_response(status, content_type, body)
            conn.sendall(response)

    except Exception as e:
        logger.debug("Connection error from %s: %s", addr, e)
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ============================================================================
# HTTPS Server
# ============================================================================


def run(server: Server, listen_addr: str, port: int,
        cert_path: str, key_path: str,
        http_handler: HttpHandler) -> None:
    """Run the HTTPS server.

    This function blocks and runs the server loop in the current thread.

    Args:
        server: Server instance for WebSocket client management.
        listen_addr: Address to listen on.
        port: Port to listen on.
        cert_path: Path to TLS certificate file.
        key_path: Path to TLS private key file.
        http_handler: HTTP handler for serving static files.
    """
    # Create SSL context
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(cert_path, key_path)
    # Prefer ChaCha20-Poly1305 for better performance on devices without AES hardware
    try:
        ssl_context.set_ciphers("CHACHA20")
    except ssl.SSLError:
        # Fall back to default ciphers if ChaCha20 is not available
        logger.warning("ChaCha20 cipher not available, using default ciphers")

    # Create and bind TCP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((listen_addr, port))
    sock.listen(128)

    logger.info("HTTPS server listening on %s:%d", listen_addr, port)

    ssl_sock = ssl_context.wrap_socket(sock, server_side=True)

    try:
        while True:
            try:
                conn, addr = ssl_sock.accept()
            except ssl.SSLError as e:
                logger.debug("TLS handshake failed: %s", e)
                continue
            except OSError as e:
                logger.error("Accept error: %s", e)
                continue

            # Handle each connection in a new thread
            thread = threading.Thread(
                target=_handle_connection,
                args=(conn, addr, server, http_handler),
                daemon=True,
            )
            thread.start()
    finally:
        ssl_sock.close()
