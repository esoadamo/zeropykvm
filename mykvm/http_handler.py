"""HTTP request handler for serving static web frontend files.

Serves files from a tar archive (web/dist.tar) or a directory.
"""

import io
import logging
import os
import tarfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Content-Type mapping
CONTENT_TYPE_MAP = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


def _get_content_type(path: str) -> str:
    """Get Content-Type for a file path based on extension."""
    for ext, content_type in CONTENT_TYPE_MAP.items():
        if path.endswith(ext):
            return content_type
    return "application/octet-stream"


class HttpHandler:
    """HTTP handler that serves static files from a tar archive or directory.

    In the original Zig version, the web frontend is embedded as a tar archive.
    In Python, we load the tar into memory at startup.
    """

    def __init__(self, web_dist_path: str | None = None):
        """Initialize the HTTP handler.

        Args:
            web_dist_path: Path to the web dist tar file or directory.
                          If None, returns 404 for all requests.
        """
        self._files: dict[str, tuple[str, bytes]] = {}  # path -> (content_type, data)

        if web_dist_path is None:
            logger.warning("No web dist path provided, all HTTP requests will return 404")
            return

        if os.path.isdir(web_dist_path):
            self._load_from_directory(web_dist_path)
        elif os.path.isfile(web_dist_path):
            self._load_from_tar(web_dist_path)
        else:
            logger.warning("Web dist path not found: %s", web_dist_path)

    def _load_from_tar(self, tar_path: str) -> None:
        """Load files from a tar archive into memory."""
        try:
            with tarfile.open(tar_path, "r") as tf:
                for member in tf.getmembers():
                    if member.isfile():
                        name = member.name
                        if name.startswith("./"):
                            name = name[2:]
                        f = tf.extractfile(member)
                        if f is not None:
                            data = f.read()
                            content_type = _get_content_type(name)
                            self._files[name] = (content_type, data)
            logger.info("Loaded %d files from tar archive", len(self._files))
        except Exception as e:
            logger.error("Failed to load tar archive %s: %s", tar_path, e)

    def _load_from_directory(self, dir_path: str) -> None:
        """Load files from a directory into memory."""
        base = Path(dir_path)
        for path in base.rglob("*"):
            if path.is_file():
                rel_path = str(path.relative_to(base))
                data = path.read_bytes()
                content_type = _get_content_type(rel_path)
                self._files[rel_path] = (content_type, data)
        logger.info("Loaded %d files from directory", len(self._files))

    def handle_request(self, request_path: str) -> tuple[int, str, bytes]:
        """Handle an HTTP request and return status, content-type, and body.

        Args:
            request_path: URL path (e.g., "/" or "/index.html").

        Returns:
            Tuple of (status_code, content_type, body_bytes).
        """
        # Default to index.html for root path
        if request_path == "/":
            file_path = "index.html"
        else:
            file_path = request_path.lstrip("/")

        if file_path in self._files:
            content_type, data = self._files[file_path]
            return 200, content_type, data
        else:
            return 404, "text/plain", b"404 Not Found"

    def format_response(self, status_code: int, content_type: str, body: bytes) -> bytes:
        """Format an HTTP response.

        Args:
            status_code: HTTP status code.
            content_type: Content-Type header value.
            body: Response body bytes.

        Returns:
            Complete HTTP response as bytes.
        """
        status_text = {200: "OK", 404: "Not Found", 500: "Internal Server Error"}.get(
            status_code, "Unknown"
        )
        header = (
            f"HTTP/1.1 {status_code} {status_text}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode()
        return header + body
