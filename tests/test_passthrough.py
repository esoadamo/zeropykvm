"""Tests for the HDMI passthrough module."""

import ctypes
import mmap
import os
import struct
import tempfile
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from zeropykvm import v4l2
from zeropykvm.passthrough import (
    HdmiPassthrough,
    _FbFixScreenInfo,
    _FbVarScreenInfo,
    _clamp,
    _yuv_to_rgb565,
    _yuv_to_rgb888,
    convert_uyvy_to_argb8888,
    convert_uyvy_to_rgb565,
    convert_yuyv_to_argb8888,
    convert_yuyv_to_rgb565,
)


# ── Pure-function unit tests ──────────────────────────────────────────────────

class TestClamp:
    def test_clamp_in_range(self):
        assert _clamp(128) == 128

    def test_clamp_below_zero(self):
        assert _clamp(-5) == 0

    def test_clamp_above_255(self):
        assert _clamp(300) == 255

    def test_clamp_boundaries(self):
        assert _clamp(0) == 0
        assert _clamp(255) == 255


class TestYuvToRgb565:
    def test_pure_black(self):
        """Y=16 U=128 V=128 is black in BT.601 limited range."""
        px = _yuv_to_rgb565(16, 128, 128)
        r5 = (px >> 11) & 0x1F
        g6 = (px >> 5) & 0x3F
        b5 = px & 0x1F
        assert r5 == 0
        assert g6 == 0
        assert b5 == 0

    def test_pure_white(self):
        """Y=235 U=128 V=128 is white in BT.601 limited range."""
        px = _yuv_to_rgb565(235, 128, 128)
        r5 = (px >> 11) & 0x1F
        g6 = (px >> 5) & 0x3F
        b5 = px & 0x1F
        # White: all channels should be near maximum
        assert r5 > 28
        assert g6 > 58
        assert b5 > 28

    def test_returns_16bit(self):
        px = _yuv_to_rgb565(128, 128, 128)
        assert 0 <= px <= 0xFFFF

    def test_no_negative(self):
        """Clamping must prevent negative colour components."""
        px = _yuv_to_rgb565(0, 0, 0)
        assert 0 <= px <= 0xFFFF


class TestYuvToRgb888:
    def test_pure_black(self):
        r, g, b = _yuv_to_rgb888(16, 128, 128)
        assert r == 0 and g == 0 and b == 0

    def test_pure_white(self):
        r, g, b = _yuv_to_rgb888(235, 128, 128)
        assert r > 240 and g > 240 and b > 240

    def test_range(self):
        for y in (0, 16, 128, 235, 255):
            for u in (0, 128, 255):
                for vv in (0, 128, 255):
                    r, g, b = _yuv_to_rgb888(y, u, vv)
                    assert 0 <= r <= 255
                    assert 0 <= g <= 255
                    assert 0 <= b <= 255


# ── Conversion function tests ─────────────────────────────────────────────────

def _make_yuyv_frame(width: int, height: int,
                     y: int = 16, u: int = 128, v: int = 128) -> bytearray:
    """Create a YUYV frame filled with a single YUV colour."""
    frame = bytearray(width * height * 2)
    for i in range(0, len(frame), 4):
        frame[i] = y       # Y0
        frame[i + 1] = u   # U
        frame[i + 2] = y   # Y1
        frame[i + 3] = v   # V
    return frame


def _make_uyvy_frame(width: int, height: int,
                     y: int = 16, u: int = 128, v: int = 128) -> bytearray:
    """Create a UYVY frame filled with a single YUV colour."""
    frame = bytearray(width * height * 2)
    for i in range(0, len(frame), 4):
        frame[i] = u       # U
        frame[i + 1] = y   # Y0
        frame[i + 2] = v   # V
        frame[i + 3] = y   # Y1
    return frame


class TestConvertYuyvToRgb565:
    def test_output_size(self):
        w, h = 4, 2
        data = _make_yuyv_frame(w, h)
        out = convert_yuyv_to_rgb565(data, w, h, w * 2)
        assert len(out) == w * h * 2

    def test_black_frame(self):
        """A black YUYV frame should produce (near) zero RGB565 values."""
        w, h = 4, 2
        data = _make_yuyv_frame(w, h, y=16, u=128, v=128)
        out = convert_yuyv_to_rgb565(data, w, h, w * 2)
        for i in range(0, len(out), 2):
            px = out[i] | (out[i + 1] << 8)
            assert px == 0, f"Pixel at byte {i} is not black: {px:#06x}"

    def test_type_is_bytearray(self):
        data = _make_yuyv_frame(2, 2)
        out = convert_yuyv_to_rgb565(data, 2, 2, 4)
        assert isinstance(out, bytearray)

    def test_stride_larger_than_width(self):
        """Extra padding bytes in source stride must be ignored."""
        w, h = 2, 2
        stride = w * 2 + 8  # 8 extra bytes of padding per row
        frame = bytearray(stride * h)
        # Write YUYV for first row
        frame[0] = 16; frame[1] = 128; frame[2] = 16; frame[3] = 128
        # Second row at stride offset
        frame[stride] = 16; frame[stride + 1] = 128
        frame[stride + 2] = 16; frame[stride + 3] = 128
        out = convert_yuyv_to_rgb565(frame, w, h, stride)
        assert len(out) == w * h * 2


class TestConvertUyvyToRgb565:
    def test_output_size(self):
        w, h = 4, 2
        data = _make_uyvy_frame(w, h)
        out = convert_uyvy_to_rgb565(data, w, h, w * 2)
        assert len(out) == w * h * 2

    def test_black_frame(self):
        w, h = 4, 2
        data = _make_uyvy_frame(w, h, y=16, u=128, v=128)
        out = convert_uyvy_to_rgb565(data, w, h, w * 2)
        for i in range(0, len(out), 2):
            px = out[i] | (out[i + 1] << 8)
            assert px == 0

    def test_same_result_as_yuyv_for_same_colour(self):
        """YUYV and UYVY of the same colour should produce the same output."""
        w, h = 2, 2
        yuyv = _make_yuyv_frame(w, h, y=100, u=200, v=50)
        uyvy = _make_uyvy_frame(w, h, y=100, u=200, v=50)
        out_yuyv = convert_yuyv_to_rgb565(yuyv, w, h, w * 2)
        out_uyvy = convert_uyvy_to_rgb565(uyvy, w, h, w * 2)
        assert out_yuyv == out_uyvy


class TestConvertYuyvToArgb8888:
    def test_output_size(self):
        w, h = 4, 2
        data = _make_yuyv_frame(w, h)
        out = convert_yuyv_to_argb8888(data, w, h, w * 2)
        assert len(out) == w * h * 4

    def test_alpha_channel_is_ff(self):
        w, h = 2, 2
        data = _make_yuyv_frame(w, h, y=100, u=128, v=128)
        out = convert_yuyv_to_argb8888(data, w, h, w * 2)
        # Alpha is the 4th byte of each pixel (BGRA layout)
        for i in range(3, len(out), 4):
            assert out[i] == 0xFF

    def test_black_frame(self):
        w, h = 2, 2
        data = _make_yuyv_frame(w, h, y=16, u=128, v=128)
        out = convert_yuyv_to_argb8888(data, w, h, w * 2)
        # B G R = 0 0 0, A = 0xFF
        for i in range(0, len(out), 4):
            assert out[i] == 0      # B
            assert out[i + 1] == 0  # G
            assert out[i + 2] == 0  # R
            assert out[i + 3] == 0xFF  # A


class TestConvertUyvyToArgb8888:
    def test_output_size(self):
        w, h = 4, 2
        data = _make_uyvy_frame(w, h)
        out = convert_uyvy_to_argb8888(data, w, h, w * 2)
        assert len(out) == w * h * 4

    def test_same_result_as_yuyv_for_same_colour(self):
        w, h = 2, 2
        yuyv = _make_yuyv_frame(w, h, y=100, u=200, v=50)
        uyvy = _make_uyvy_frame(w, h, y=100, u=200, v=50)
        out_yuyv = convert_yuyv_to_argb8888(yuyv, w, h, w * 2)
        out_uyvy = convert_uyvy_to_argb8888(uyvy, w, h, w * 2)
        assert out_yuyv == out_uyvy


# ── HdmiPassthrough class tests (with mocked hardware) ───────────────────────

def _build_vscreeninfo(xres: int, yres: int, bpp: int) -> bytearray:
    """Build a fake fb_var_screeninfo buffer."""
    info = _FbVarScreenInfo()
    info.xres = xres
    info.yres = yres
    info.bits_per_pixel = bpp
    return bytearray(info)


def _build_fscreeninfo(line_length: int, smem_len: int) -> bytearray:
    """Build a fake fb_fix_screeninfo buffer."""
    info = _FbFixScreenInfo()
    info.line_length = line_length
    info.smem_len = smem_len
    return bytearray(info)


class TestHdmiPassthroughInit:
    def test_default_device(self):
        pt = HdmiPassthrough()
        assert pt.device == "/dev/fb0"

    def test_custom_device(self):
        pt = HdmiPassthrough("/dev/fb1")
        assert pt.device == "/dev/fb1"

    def test_initial_state(self):
        pt = HdmiPassthrough()
        assert pt.fd == -1
        assert pt._mm is None
        assert pt.fb_width == 0
        assert pt.fb_height == 0


class TestHdmiPassthroughOpen:
    """Test open() with mocked OS calls."""

    def _open_mocked(self, bpp: int = 16, width: int = 1920, height: int = 1080,
                     smem_len: int = 1920 * 1080 * 2):
        """Open a passthrough instance using mocked ioctl and mmap.

        Returns (pt, fake_mm) where pt.fd is -1 (safe for GC) and
        pt._mm is None; the caller receives fake_mm directly and is
        responsible for closing it.
        """
        line_length = width * (bpp // 8)
        pt = HdmiPassthrough("/dev/fb0")

        def fake_ioctl(fd, request, buf):
            from zeropykvm.passthrough import FBIOGET_VSCREENINFO, FBIOGET_FSCREENINFO
            if request == FBIOGET_VSCREENINFO:
                vinfo = _FbVarScreenInfo.from_buffer(buf)
                vinfo.xres = width
                vinfo.yres = height
                vinfo.bits_per_pixel = bpp
            elif request == FBIOGET_FSCREENINFO:
                finfo = _FbFixScreenInfo.from_buffer(buf)
                finfo.line_length = line_length
                finfo.smem_len = smem_len

        fake_mm = mmap.mmap(-1, smem_len)

        with patch("os.open", return_value=5), \
             patch("os.close"), \
             patch("fcntl.ioctl", side_effect=fake_ioctl), \
             patch("mmap.mmap", return_value=fake_mm):
            pt.open()

        # Detach the fake fd so __del__ does not try os.close(5).
        pt.fd = -1
        # Detach the mmap from pt so the caller controls its lifetime.
        pt._mm = None

        return pt, fake_mm

    def test_open_sets_dimensions_16bpp(self):
        pt, mm = self._open_mocked(bpp=16, width=1920, height=1080)
        try:
            assert pt.fb_width == 1920
            assert pt.fb_height == 1080
            assert pt.fb_bpp == 16
        finally:
            mm.close()

    def test_open_sets_dimensions_32bpp(self):
        pt, mm = self._open_mocked(bpp=32, width=1280, height=720,
                                   smem_len=1280 * 720 * 4)
        try:
            assert pt.fb_width == 1280
            assert pt.fb_height == 720
            assert pt.fb_bpp == 32
        finally:
            mm.close()

    def test_open_raises_for_unsupported_bpp(self):
        pt = HdmiPassthrough("/dev/fb0")

        def fake_ioctl(fd, request, buf):
            from zeropykvm.passthrough import FBIOGET_VSCREENINFO, FBIOGET_FSCREENINFO
            if request == FBIOGET_VSCREENINFO:
                vinfo = _FbVarScreenInfo.from_buffer(buf)
                vinfo.xres = 1920
                vinfo.yres = 1080
                vinfo.bits_per_pixel = 24  # unsupported
            elif request == FBIOGET_FSCREENINFO:
                finfo = _FbFixScreenInfo.from_buffer(buf)
                finfo.line_length = 1920 * 3
                finfo.smem_len = 1920 * 1080 * 3

        fake_mm = mmap.mmap(-1, 4096)
        try:
            with patch("os.open", return_value=5), \
                 patch("os.close"), \
                 patch("fcntl.ioctl", side_effect=fake_ioctl), \
                 patch("mmap.mmap", return_value=fake_mm):
                with pytest.raises(RuntimeError, match="colour depth"):
                    pt.open()
        finally:
            fake_mm.close()


class TestHdmiPassthroughWriteFrame:
    """Test write_frame() with a pre-opened passthrough instance."""

    def _make_pt(self, bpp: int, width: int, height: int) -> tuple["HdmiPassthrough", mmap.mmap]:
        """Return an HdmiPassthrough with a fake mmap backing store.

        fd is left at -1 so __del__ does not attempt os.close on a
        non-existent descriptor.  The caller owns fake_mm and must
        detach it from pt (set pt._mm = None) before closing.
        """
        smem_len = width * height * (bpp // 8)
        line_length = width * (bpp // 8)
        fake_mm = mmap.mmap(-1, smem_len)

        pt = HdmiPassthrough("/dev/fb0")
        pt.fd = -1  # keep invalid to avoid os.close in __del__
        pt._mm = fake_mm
        pt.fb_width = width
        pt.fb_height = height
        pt.fb_bpp = bpp
        pt.fb_line_length = line_length
        pt.fb_size = smem_len
        return pt, fake_mm

    def _cleanup(self, pt: "HdmiPassthrough", mm: mmap.mmap) -> None:
        """Detach mmap from pt before closing to avoid double-close."""
        pt._mm = None
        mm.close()

    def test_write_yuyv_16bpp(self):
        w, h = 4, 2
        pt, mm = self._make_pt(16, w, h)
        try:
            frame = _make_yuyv_frame(w, h, y=235, u=128, v=128)  # white
            pt.write_frame(frame, w, h, v4l2.V4L2_PIX_FMT_YUYV, w * 2)
            mm.seek(0)
            data = mm.read(w * h * 2)
            assert any(b != 0 for b in data)
        finally:
            self._cleanup(pt, mm)

    def test_write_uyvy_16bpp(self):
        w, h = 4, 2
        pt, mm = self._make_pt(16, w, h)
        try:
            frame = _make_uyvy_frame(w, h, y=235, u=128, v=128)  # white
            pt.write_frame(frame, w, h, v4l2.V4L2_PIX_FMT_UYVY, w * 2)
            mm.seek(0)
            data = mm.read(w * h * 2)
            assert any(b != 0 for b in data)
        finally:
            self._cleanup(pt, mm)

    def test_write_yuyv_32bpp(self):
        w, h = 4, 2
        pt, mm = self._make_pt(32, w, h)
        try:
            frame = _make_yuyv_frame(w, h, y=235, u=128, v=128)  # white
            pt.write_frame(frame, w, h, v4l2.V4L2_PIX_FMT_YUYV, w * 2)
            mm.seek(0)
            data = mm.read(w * h * 4)
            assert any(b != 0 for b in data)
        finally:
            self._cleanup(pt, mm)

    def test_write_unknown_format_does_not_raise(self):
        w, h = 4, 2
        pt, mm = self._make_pt(16, w, h)
        try:
            frame = bytearray(w * h * 2)
            pt.write_frame(frame, w, h, 0xDEADBEEF, w * 2)
        finally:
            self._cleanup(pt, mm)

    def test_write_clipped_to_framebuffer_size(self):
        """Frame larger than framebuffer must be clipped, not crash."""
        fb_w, fb_h = 4, 2
        frame_w, frame_h = 8, 4  # larger than fb
        pt, mm = self._make_pt(16, fb_w, fb_h)
        try:
            frame = _make_yuyv_frame(frame_w, frame_h)
            pt.write_frame(frame, frame_w, frame_h, v4l2.V4L2_PIX_FMT_YUYV, frame_w * 2)
        finally:
            self._cleanup(pt, mm)

    def test_write_frame_when_closed_does_not_raise(self):
        """write_frame() must be a no-op when no mmap is open."""
        pt = HdmiPassthrough("/dev/fb0")
        # _mm is None, fd is -1
        frame = _make_yuyv_frame(4, 2)
        pt.write_frame(frame, 4, 2, v4l2.V4L2_PIX_FMT_YUYV, 8)  # should not raise

    def test_black_yuyv_produces_zero_pixels_16bpp(self):
        w, h = 2, 2
        pt, mm = self._make_pt(16, w, h)
        try:
            frame = _make_yuyv_frame(w, h, y=16, u=128, v=128)
            pt.write_frame(frame, w, h, v4l2.V4L2_PIX_FMT_YUYV, w * 2)
            mm.seek(0)
            data = mm.read(w * h * 2)
            assert all(b == 0 for b in data)
        finally:
            self._cleanup(pt, mm)


class TestHdmiPassthroughClear:
    def test_clear_fills_with_zeros(self):
        smem_len = 64
        fake_mm = mmap.mmap(-1, smem_len)
        fake_mm.write(b'\xFF' * smem_len)
        fake_mm.seek(0)

        pt = HdmiPassthrough()
        pt.fd = -1  # keep invalid to avoid os.close in __del__
        pt._mm = fake_mm
        pt.fb_size = smem_len

        try:
            pt.clear()
            fake_mm.seek(0)
            assert fake_mm.read(smem_len) == b'\x00' * smem_len
        finally:
            pt._mm = None
            fake_mm.close()


class TestHdmiPassthroughStructureSizes:
    """Verify ctypes struct sizes match known Linux values."""

    def test_fb_var_screeninfo_size(self):
        # struct fb_var_screeninfo is 160 bytes (all uint32 fields)
        assert ctypes.sizeof(_FbVarScreenInfo) == 160

    def test_fb_fix_screeninfo_size_is_reasonable(self):
        # 68 bytes on 32-bit, 80 bytes on 64-bit
        size = ctypes.sizeof(_FbFixScreenInfo)
        assert size in (68, 80), f"Unexpected _FbFixScreenInfo size: {size}"
