"""HTTPS/TLS server with WebSocket support.

Handles both HTTPS requests for the web frontend and WebSocket
connections for real-time video streaming and HID control.

Uses the websockets library for robust, RFC-compliant WebSocket
protocol handling instead of a hand-rolled implementation.
"""

import logging
import ssl

from websockets.sync.server import serve as ws_serve
from websockets.http11 import Response
from websockets.datastructures import Headers

from .http_handler import HttpHandler
from .server import Server
from . import ws_handler

logger = logging.getLogger(__name__)


def _make_process_request(http_handler: HttpHandler):
    """Create a process_request callback for the WebSocket server.

    The returned callback routes requests: WebSocket upgrade requests
    pass through to the WebSocket handler, while regular HTTP requests
    are served by the HTTP handler.

    Args:
        http_handler: HTTP handler for serving static files.

    Returns:
        Callback compatible with websockets process_request parameter.
    """
    def process_request(connection, request):
        # Let WebSocket upgrade requests proceed to the handshake
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return None

        # Serve static files for regular HTTP requests
        status_code, content_type, body = http_handler.handle_request(
            request.path
        )
        reason = {200: "OK", 404: "Not Found"}.get(status_code, "Error")
        return Response(
            status_code,
            reason,
            Headers([
                ("Content-Type", content_type),
                ("Content-Length", str(len(body))),
                ("Connection", "close"),
            ]),
            body,
        )

    return process_request


def _make_ws_handler(server: Server):
    """Create a WebSocket connection handler.

    Args:
        server: Server instance for client management.

    Returns:
        Handler callable for websockets serve().
    """
    def handle_websocket(websocket):
        server.add_client(websocket)
        try:
            for message in websocket:
                ws_handler.handle_message(server, websocket, message)
        finally:
            server.remove_client(websocket)

    return handle_websocket


def run(server: Server, listen_addr: str, port: int,
        cert_path: str, key_path: str,
        http_handler: HttpHandler) -> None:
    """Run the HTTPS server with WebSocket support.

    Serves both static files over HTTPS and WebSocket connections
    for real-time video streaming and HID control on the same port.

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
    ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
    ssl_context.load_cert_chain(cert_path, key_path)
    # Prefer ChaCha20-Poly1305 for better performance on devices without AES hardware
    try:
        ssl_context.set_ciphers("CHACHA20")
    except ssl.SSLError:
        logger.warning("ChaCha20 cipher not available, using default ciphers")

    logger.info("HTTPS server listening on %s:%d", listen_addr, port)

    with ws_serve(
        _make_ws_handler(server),
        listen_addr,
        port,
        ssl=ssl_context,
        process_request=_make_process_request(http_handler),
        max_size=1 * 1024 * 1024,  # 1 MB max WebSocket message size
        compression=None,  # Disable compression for H.264 data
    ) as ws_server:
        ws_server.serve_forever()
