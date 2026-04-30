"""HDMI passthrough — display captured frames on the RPi HDMI output via /dev/fb0.

Reads raw YUV frames from the V4L2 capture DMA buffers and converts them
to the framebuffer's native pixel format (RGB565 or ARGB8888), writing the
result to the Linux framebuffer device.

This feature is optional and CPU-intensive.  At 1080p the software colour
conversion can limit throughput; lower-resolution sources (720p) work better.
"""

import ctypes
import fcntl
import logging
import mmap
import os

from . import v4l2

logger = logging.getLogger(__name__)

# Framebuffer ioctl request codes (linux/fb.h)
FBIOGET_VSCREENINFO = 0x4600
FBIOPUT_VSCREENINFO = 0x4601
FBIOGET_FSCREENINFO = 0x4602


# ── ctypes structures that mirror the Linux fb.h definitions ────────────────

class _FbBitfield(ctypes.Structure):
    _fields_ = [
        ("offset", ctypes.c_uint32),
        ("length", ctypes.c_uint32),
        ("msb_right", ctypes.c_uint32),
    ]


class _FbVarScreenInfo(ctypes.Structure):
    """Maps to struct fb_var_screeninfo (linux/fb.h)."""
    _fields_ = [
        ("xres", ctypes.c_uint32),
        ("yres", ctypes.c_uint32),
        ("xres_virtual", ctypes.c_uint32),
        ("yres_virtual", ctypes.c_uint32),
        ("xoffset", ctypes.c_uint32),
        ("yoffset", ctypes.c_uint32),
        ("bits_per_pixel", ctypes.c_uint32),
        ("grayscale", ctypes.c_uint32),
        ("red", _FbBitfield),
        ("green", _FbBitfield),
        ("blue", _FbBitfield),
        ("transp", _FbBitfield),
        ("nonstd", ctypes.c_uint32),
        ("activate", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("width", ctypes.c_uint32),
        ("accel_flags", ctypes.c_uint32),
        ("pixclock", ctypes.c_uint32),
        ("left_margin", ctypes.c_uint32),
        ("right_margin", ctypes.c_uint32),
        ("upper_margin", ctypes.c_uint32),
        ("lower_margin", ctypes.c_uint32),
        ("hsync_len", ctypes.c_uint32),
        ("vsync_len", ctypes.c_uint32),
        ("sync", ctypes.c_uint32),
        ("vmode", ctypes.c_uint32),
        ("rotate", ctypes.c_uint32),
        ("colorspace", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 4),
    ]


class _FbFixScreenInfo(ctypes.Structure):
    """Maps to struct fb_fix_screeninfo (linux/fb.h).

    ``smem_start`` and ``mmio_start`` are ``unsigned long`` — 4 bytes on a
    32-bit kernel / userspace, 8 bytes on a 64-bit one.  Using ``c_ulong``
    lets ctypes handle this automatically.
    """
    _fields_ = [
        ("id", ctypes.c_char * 16),
        ("smem_start", ctypes.c_ulong),
        ("smem_len", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("type_aux", ctypes.c_uint32),
        ("visual", ctypes.c_uint32),
        ("xpanstep", ctypes.c_uint16),
        ("ypanstep", ctypes.c_uint16),
        ("ywrapstep", ctypes.c_uint16),
        # ctypes inserts 2 bytes of natural padding here so that
        # line_length (uint32) is 4-byte aligned — same as the C compiler.
        ("line_length", ctypes.c_uint32),
        ("mmio_start", ctypes.c_ulong),
        ("mmio_len", ctypes.c_uint32),
        ("accel", ctypes.c_uint32),
        ("capabilities", ctypes.c_uint16),
        ("reserved", ctypes.c_uint16 * 2),
    ]


# ── Pure pixel-conversion helpers ────────────────────────────────────────────

def _clamp(v: int) -> int:
    """Clamp an integer to the 0-255 range."""
    return 0 if v < 0 else (255 if v > 255 else v)


def _yuv_to_rgb565(y: int, u: int, v: int) -> int:
    """Convert a single YUV sample to a packed RGB565 value.

    Uses the BT.601 limited-range formula (same as V4L2 driver convention).

    Returns:
        16-bit little-endian RGB565 value.
    """
    c = y - 16
    d = u - 128
    e = v - 128

    r = _clamp((298 * c + 409 * e + 128) >> 8)
    g = _clamp((298 * c - 100 * d - 208 * e + 128) >> 8)
    b = _clamp((298 * c + 516 * d + 128) >> 8)

    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def _yuv_to_rgb888(y: int, u: int, v: int) -> tuple[int, int, int]:
    """Convert a single YUV sample to an (R, G, B) triple (0-255 each)."""
    c = y - 16
    d = u - 128
    e = v - 128

    r = _clamp((298 * c + 409 * e + 128) >> 8)
    g = _clamp((298 * c - 100 * d - 208 * e + 128) >> 8)
    b = _clamp((298 * c + 516 * d + 128) >> 8)
    return r, g, b


def convert_yuyv_to_rgb565(src: bytes | bytearray | memoryview,
                            width: int, height: int,
                            src_stride: int) -> bytearray:
    """Convert a YUYV (YUY2) frame to a packed RGB565 frame.

    Args:
        src: Source frame data (YUYV packed, 2 bytes per pixel).
        width: Frame width in pixels (must be even).
        height: Frame height in pixels.
        src_stride: Source bytes per row (may be > width*2 for padding).

    Returns:
        bytearray of size ``width * height * 2`` in RGB565 little-endian.
    """
    out = bytearray(width * height * 2)
    dst_i = 0
    for row in range(height):
        row_base = row * src_stride
        for col in range(0, width, 2):
            base = row_base + col * 2
            y0 = src[base]
            u = src[base + 1]
            y1 = src[base + 2]
            v = src[base + 3]

            px0 = _yuv_to_rgb565(y0, u, v)
            px1 = _yuv_to_rgb565(y1, u, v)

            out[dst_i] = px0 & 0xFF
            out[dst_i + 1] = (px0 >> 8) & 0xFF
            out[dst_i + 2] = px1 & 0xFF
            out[dst_i + 3] = (px1 >> 8) & 0xFF
            dst_i += 4
    return out


def convert_uyvy_to_rgb565(src: bytes | bytearray | memoryview,
                            width: int, height: int,
                            src_stride: int) -> bytearray:
    """Convert a UYVY frame to a packed RGB565 frame.

    Args:
        src: Source frame data (UYVY packed, 2 bytes per pixel).
        width: Frame width in pixels (must be even).
        height: Frame height in pixels.
        src_stride: Source bytes per row.

    Returns:
        bytearray of size ``width * height * 2`` in RGB565 little-endian.
    """
    out = bytearray(width * height * 2)
    dst_i = 0
    for row in range(height):
        row_base = row * src_stride
        for col in range(0, width, 2):
            base = row_base + col * 2
            u = src[base]
            y0 = src[base + 1]
            v = src[base + 2]
            y1 = src[base + 3]

            px0 = _yuv_to_rgb565(y0, u, v)
            px1 = _yuv_to_rgb565(y1, u, v)

            out[dst_i] = px0 & 0xFF
            out[dst_i + 1] = (px0 >> 8) & 0xFF
            out[dst_i + 2] = px1 & 0xFF
            out[dst_i + 3] = (px1 >> 8) & 0xFF
            dst_i += 4
    return out


def convert_yuyv_to_argb8888(src: bytes | bytearray | memoryview,
                              width: int, height: int,
                              src_stride: int) -> bytearray:
    """Convert a YUYV frame to ARGB8888 (stored as B G R A in memory).

    Args:
        src: Source frame data (YUYV packed, 2 bytes per pixel).
        width: Frame width in pixels (must be even).
        height: Frame height in pixels.
        src_stride: Source bytes per row.

    Returns:
        bytearray of size ``width * height * 4`` in BGRA byte order
        (which produces ARGB when interpreted as a 32-bit little-endian word).
    """
    out = bytearray(width * height * 4)
    dst_i = 0
    for row in range(height):
        row_base = row * src_stride
        for col in range(0, width, 2):
            base = row_base + col * 2
            y0 = src[base]
            u = src[base + 1]
            y1 = src[base + 2]
            v = src[base + 3]

            r0, g0, b0 = _yuv_to_rgb888(y0, u, v)
            r1, g1, b1 = _yuv_to_rgb888(y1, u, v)

            out[dst_i] = b0
            out[dst_i + 1] = g0
            out[dst_i + 2] = r0
            out[dst_i + 3] = 0xFF
            out[dst_i + 4] = b1
            out[dst_i + 5] = g1
            out[dst_i + 6] = r1
            out[dst_i + 7] = 0xFF
            dst_i += 8
    return out


def convert_uyvy_to_argb8888(src: bytes | bytearray | memoryview,
                              width: int, height: int,
                              src_stride: int) -> bytearray:
    """Convert a UYVY frame to ARGB8888 (stored as B G R A in memory).

    Args:
        src: Source frame data (UYVY packed, 2 bytes per pixel).
        width: Frame width in pixels (must be even).
        height: Frame height in pixels.
        src_stride: Source bytes per row.

    Returns:
        bytearray of size ``width * height * 4`` in BGRA byte order.
    """
    out = bytearray(width * height * 4)
    dst_i = 0
    for row in range(height):
        row_base = row * src_stride
        for col in range(0, width, 2):
            base = row_base + col * 2
            u = src[base]
            y0 = src[base + 1]
            v = src[base + 2]
            y1 = src[base + 3]

            r0, g0, b0 = _yuv_to_rgb888(y0, u, v)
            r1, g1, b1 = _yuv_to_rgb888(y1, u, v)

            out[dst_i] = b0
            out[dst_i + 1] = g0
            out[dst_i + 2] = r0
            out[dst_i + 3] = 0xFF
            out[dst_i + 4] = b1
            out[dst_i + 5] = g1
            out[dst_i + 6] = r1
            out[dst_i + 7] = 0xFF
            dst_i += 8
    return out


# ── Main class ────────────────────────────────────────────────────────────────

class HdmiPassthrough:
    """HDMI passthrough via the Linux framebuffer device.

    Opens the given framebuffer device (default ``/dev/fb0``), queries its
    dimensions and colour depth, and provides a :meth:`write_frame` method
    that converts a raw V4L2-captured YUV frame to the framebuffer's native
    format and copies it into the display memory.

    Supported source pixel formats: YUYV (YUY2) and UYVY.
    Supported framebuffer depths: 16-bit (RGB565) and 32-bit (ARGB8888).
    """

    def __init__(self, device: str = "/dev/fb0") -> None:
        self.device = device
        self.fd: int = -1
        self._mm: mmap.mmap | None = None
        self.fb_width: int = 0
        self.fb_height: int = 0
        self.fb_bpp: int = 0
        self.fb_line_length: int = 0
        self.fb_size: int = 0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def open(self) -> None:
        """Open the framebuffer device and memory-map its display memory.

        Raises:
            OSError: If the device cannot be opened or mapped.
            RuntimeError: If the framebuffer colour depth is unsupported.
        """
        logger.info("Opening framebuffer device %s", self.device)
        self.fd = os.open(self.device, os.O_RDWR)
        try:
            vinfo = _FbVarScreenInfo()
            fcntl.ioctl(self.fd, FBIOGET_VSCREENINFO, vinfo)

            finfo = _FbFixScreenInfo()
            fcntl.ioctl(self.fd, FBIOGET_FSCREENINFO, finfo)

            self.fb_width = vinfo.xres
            self.fb_height = vinfo.yres
            self.fb_bpp = vinfo.bits_per_pixel
            self.fb_line_length = finfo.line_length
            self.fb_size = finfo.smem_len

            logger.info(
                "Framebuffer: %dx%d %dbpp line_length=%d size=%d",
                self.fb_width, self.fb_height,
                self.fb_bpp, self.fb_line_length, self.fb_size,
            )

            if self.fb_bpp not in (16, 32):
                raise RuntimeError(
                    f"Unsupported framebuffer colour depth: {self.fb_bpp}bpp "
                    "(only 16 and 32 are supported)"
                )

            self._mm = mmap.mmap(
                self.fd, self.fb_size,
                mmap.MAP_SHARED,
                mmap.PROT_READ | mmap.PROT_WRITE,
            )
        except Exception:
            os.close(self.fd)
            self.fd = -1
            raise

    def close(self) -> None:
        """Clear the framebuffer to black and release all resources."""
        if self._mm is not None:
            try:
                self.clear()
                self._mm.close()
            except Exception:
                pass
            self._mm = None
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1
            logger.info("Framebuffer closed")

    def __enter__(self) -> "HdmiPassthrough":
        """Support use as a context manager — opens the framebuffer on entry."""
        self.open()
        return self

    def __exit__(self, *_) -> None:
        """Support use as a context manager — closes the framebuffer on exit."""
        self.close()

    def __del__(self) -> None:
        if self.fd >= 0:
            self.close()

    # ── Display helpers ───────────────────────────────────────────────────────

    def clear(self) -> None:
        """Fill the framebuffer with black pixels."""
        if self._mm is not None:
            self._mm.seek(0)
            self._mm.write(b"\x00" * self.fb_size)

    # ── Frame writing ─────────────────────────────────────────────────────────

    def write_frame(
        self,
        data: bytes | bytearray | memoryview,
        width: int,
        height: int,
        pixelformat: int,
        bytesperline: int,
    ) -> None:
        """Convert and write a captured video frame to the framebuffer.

        The frame is clipped to fit within the framebuffer dimensions.

        Args:
            data: Raw frame data from the V4L2 capture device.
            width: Frame width in pixels.
            height: Frame height in pixels.
            pixelformat: V4L2 FourCC pixel format
                         (``V4L2_PIX_FMT_YUYV`` or ``V4L2_PIX_FMT_UYVY``).
            bytesperline: Source bytes per row (stride).
        """
        if self._mm is None:
            return

        out_w = min(width, self.fb_width)
        out_h = min(height, self.fb_height)

        mv = memoryview(data) if not isinstance(data, memoryview) else data

        if pixelformat == v4l2.V4L2_PIX_FMT_YUYV:
            self._write_yuv_frame(mv, out_w, out_h, bytesperline, is_uyvy=False)
        elif pixelformat == v4l2.V4L2_PIX_FMT_UYVY:
            self._write_yuv_frame(mv, out_w, out_h, bytesperline, is_uyvy=True)
        else:
            logger.warning(
                "HDMI passthrough: unsupported pixel format 0x%08x — frame skipped",
                pixelformat,
            )

    def _write_yuv_frame(
        self,
        src: memoryview,
        width: int,
        height: int,
        src_stride: int,
        is_uyvy: bool,
    ) -> None:
        """Internal: convert and write one YUV frame to the framebuffer."""
        mm = self._mm
        if mm is None:
            return

        fb_stride = self.fb_line_length

        if self.fb_bpp == 16:
            if is_uyvy:
                rgb_frame = convert_uyvy_to_rgb565(src, width, height, src_stride)
            else:
                rgb_frame = convert_yuyv_to_rgb565(src, width, height, src_stride)
            row_bytes = width * 2
            for y in range(height):
                fb_off = y * fb_stride
                src_off = y * row_bytes
                mm[fb_off:fb_off + row_bytes] = rgb_frame[src_off:src_off + row_bytes]

        elif self.fb_bpp == 32:
            if is_uyvy:
                rgb_frame = convert_uyvy_to_argb8888(src, width, height, src_stride)
            else:
                rgb_frame = convert_yuyv_to_argb8888(src, width, height, src_stride)
            row_bytes = width * 4
            for y in range(height):
                fb_off = y * fb_stride
                src_off = y * row_bytes
                mm[fb_off:fb_off + row_bytes] = rgb_frame[src_off:src_off + row_bytes]
