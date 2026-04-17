"""Tests for HTTP handler module."""

import os
import tarfile
import tempfile

from mykvm.http_handler import HttpHandler, _get_content_type


class TestGetContentType:
    """Test content type detection."""

    def test_html(self):
        assert _get_content_type("index.html") == "text/html; charset=utf-8"

    def test_css(self):
        assert _get_content_type("style.css") == "text/css; charset=utf-8"

    def test_js(self):
        assert _get_content_type("app.js") == "application/javascript; charset=utf-8"

    def test_json(self):
        assert _get_content_type("data.json") == "application/json; charset=utf-8"

    def test_svg(self):
        assert _get_content_type("icon.svg") == "image/svg+xml"

    def test_png(self):
        assert _get_content_type("image.png") == "image/png"

    def test_ico(self):
        assert _get_content_type("favicon.ico") == "image/x-icon"

    def test_woff(self):
        assert _get_content_type("font.woff") == "font/woff"

    def test_woff2(self):
        assert _get_content_type("font.woff2") == "font/woff2"

    def test_unknown(self):
        assert _get_content_type("file.xyz") == "application/octet-stream"


class TestHttpHandler:
    """Test HTTP handler file serving."""

    def _create_test_tar(self):
        """Create a test tar file with some content."""
        tmpdir = tempfile.mkdtemp()
        tar_path = os.path.join(tmpdir, "test.tar")

        with tarfile.open(tar_path, "w") as tf:
            # Add index.html
            import io
            html_content = b"<html><body>Hello</body></html>"
            info = tarfile.TarInfo(name="index.html")
            info.size = len(html_content)
            tf.addfile(info, io.BytesIO(html_content))

            # Add style.css
            css_content = b"body { color: red; }"
            info = tarfile.TarInfo(name="style.css")
            info.size = len(css_content)
            tf.addfile(info, io.BytesIO(css_content))

            # Add file with ./ prefix
            js_content = b"console.log('hello');"
            info = tarfile.TarInfo(name="./app.js")
            info.size = len(js_content)
            tf.addfile(info, io.BytesIO(js_content))

        return tar_path, tmpdir

    def _create_test_dir(self):
        """Create a test directory with some content."""
        tmpdir = tempfile.mkdtemp()

        with open(os.path.join(tmpdir, "index.html"), "wb") as f:
            f.write(b"<html><body>Test</body></html>")
        with open(os.path.join(tmpdir, "style.css"), "wb") as f:
            f.write(b"body { margin: 0; }")

        return tmpdir

    def test_no_web_dist(self):
        """Test handler with no web dist returns 404."""
        handler = HttpHandler(None)
        status, content_type, body = handler.handle_request("/")
        assert status == 404

    def test_load_from_tar(self):
        """Test loading files from tar archive."""
        tar_path, tmpdir = self._create_test_tar()
        try:
            handler = HttpHandler(tar_path)
            status, content_type, body = handler.handle_request("/")
            assert status == 200
            assert content_type == "text/html; charset=utf-8"
            assert body == b"<html><body>Hello</body></html>"
        finally:
            os.unlink(tar_path)
            os.rmdir(tmpdir)

    def test_load_from_directory(self):
        """Test loading files from directory."""
        tmpdir = self._create_test_dir()
        try:
            handler = HttpHandler(tmpdir)
            status, content_type, body = handler.handle_request("/")
            assert status == 200
            assert b"<html>" in body
        finally:
            for f in os.listdir(tmpdir):
                os.unlink(os.path.join(tmpdir, f))
            os.rmdir(tmpdir)

    def test_css_file(self):
        """Test serving CSS file."""
        tar_path, tmpdir = self._create_test_tar()
        try:
            handler = HttpHandler(tar_path)
            status, content_type, body = handler.handle_request("/style.css")
            assert status == 200
            assert content_type == "text/css; charset=utf-8"
        finally:
            os.unlink(tar_path)
            os.rmdir(tmpdir)

    def test_js_with_dot_prefix(self):
        """Test that files with ./ prefix are handled correctly."""
        tar_path, tmpdir = self._create_test_tar()
        try:
            handler = HttpHandler(tar_path)
            status, content_type, body = handler.handle_request("/app.js")
            assert status == 200
            assert body == b"console.log('hello');"
        finally:
            os.unlink(tar_path)
            os.rmdir(tmpdir)

    def test_404(self):
        """Test 404 for nonexistent file."""
        tar_path, tmpdir = self._create_test_tar()
        try:
            handler = HttpHandler(tar_path)
            status, content_type, body = handler.handle_request("/nonexistent.html")
            assert status == 404
        finally:
            os.unlink(tar_path)
            os.rmdir(tmpdir)

    def test_format_response(self):
        """Test HTTP response formatting."""
        handler = HttpHandler(None)
        response = handler.format_response(200, "text/plain", b"Hello")
        assert response.startswith(b"HTTP/1.1 200 OK\r\n")
        assert b"Content-Type: text/plain\r\n" in response
        assert b"Content-Length: 5\r\n" in response
        assert response.endswith(b"Hello")

    def test_format_404_response(self):
        """Test 404 response formatting."""
        handler = HttpHandler(None)
        response = handler.format_response(404, "text/plain", b"Not Found")
        assert response.startswith(b"HTTP/1.1 404 Not Found\r\n")

    def test_root_path_maps_to_index(self):
        """Test that / maps to index.html."""
        tar_path, tmpdir = self._create_test_tar()
        try:
            handler = HttpHandler(tar_path)
            status1, _, body1 = handler.handle_request("/")
            status2, _, body2 = handler.handle_request("/index.html")
            assert status1 == 200
            assert status2 == 200
            assert body1 == body2
        finally:
            os.unlink(tar_path)
            os.rmdir(tmpdir)
