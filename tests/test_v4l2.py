"""Tests for V4L2 constants module."""

from zeropykvm.v4l2 import (
    V4L2_BUF_TYPE_VIDEO_CAPTURE,
    V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,
    V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE,
    V4L2_CAP_STREAMING,
    V4L2_CAP_VIDEO_CAPTURE,
    V4L2_CAP_VIDEO_M2M_MPLANE,
    V4L2_CID_MPEG_VIDEO_BITRATE,
    V4L2_MEMORY_DMABUF,
    V4L2_MEMORY_MMAP,
    V4L2_PIX_FMT_H264,
    V4L2_PIX_FMT_UYVY,
    V4L2_PIX_FMT_YUYV,
    VIDIOC_DQBUF,
    VIDIOC_G_FMT,
    VIDIOC_QBUF,
    VIDIOC_QUERYCAP,
    VIDIOC_REQBUFS,
    VIDIOC_S_FMT,
    VIDIOC_STREAMON,
    VIDIOC_STREAMOFF,
    v4l2_fourcc,
    v4l2_buffer,
    v4l2_capability,
    v4l2_control,
    v4l2_dv_timings,
    v4l2_edid,
    v4l2_format,
    v4l2_plane,
    v4l2_requestbuffers,
    dma_buf_sync,
    dma_heap_allocation_data,
)
import ctypes


class TestFourCC:
    """Test FourCC creation."""

    def test_yuyv(self):
        assert v4l2_fourcc('Y', 'U', 'Y', 'V') == V4L2_PIX_FMT_YUYV

    def test_uyvy(self):
        assert v4l2_fourcc('U', 'Y', 'V', 'Y') == V4L2_PIX_FMT_UYVY

    def test_h264(self):
        assert v4l2_fourcc('H', '2', '6', '4') == V4L2_PIX_FMT_H264


class TestConstants:
    """Test V4L2 constant values."""

    def test_buf_types(self):
        assert V4L2_BUF_TYPE_VIDEO_CAPTURE == 1
        assert V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE == 9
        assert V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE == 10

    def test_memory_types(self):
        assert V4L2_MEMORY_MMAP == 1
        assert V4L2_MEMORY_DMABUF == 4

    def test_capabilities(self):
        assert V4L2_CAP_VIDEO_CAPTURE == 0x00000001
        assert V4L2_CAP_VIDEO_M2M_MPLANE == 0x00004000
        assert V4L2_CAP_STREAMING == 0x04000000


class TestIoctlNumbers:
    """Test ioctl request number generation."""

    def test_querycap_nonzero(self):
        assert VIDIOC_QUERYCAP != 0

    def test_g_fmt_nonzero(self):
        assert VIDIOC_G_FMT != 0

    def test_s_fmt_nonzero(self):
        assert VIDIOC_S_FMT != 0

    def test_reqbufs_nonzero(self):
        assert VIDIOC_REQBUFS != 0

    def test_qbuf_nonzero(self):
        assert VIDIOC_QBUF != 0

    def test_dqbuf_nonzero(self):
        assert VIDIOC_DQBUF != 0

    def test_streamon_nonzero(self):
        assert VIDIOC_STREAMON != 0

    def test_different_ioctl_numbers(self):
        """Test that different ioctls have different numbers."""
        assert VIDIOC_QUERYCAP != VIDIOC_G_FMT
        assert VIDIOC_G_FMT != VIDIOC_S_FMT
        assert VIDIOC_QBUF != VIDIOC_DQBUF
        assert VIDIOC_STREAMON != VIDIOC_STREAMOFF


class TestStructures:
    """Test ctypes structure sizes and field access."""

    def test_v4l2_capability_fields(self):
        cap = v4l2_capability()
        cap.capabilities = V4L2_CAP_VIDEO_CAPTURE | V4L2_CAP_STREAMING
        assert cap.capabilities & V4L2_CAP_VIDEO_CAPTURE
        assert cap.capabilities & V4L2_CAP_STREAMING

    def test_v4l2_format_access(self):
        fmt = v4l2_format()
        ctypes.memset(ctypes.byref(fmt), 0, ctypes.sizeof(fmt))
        fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
        fmt.fmt.pix.width = 1920
        fmt.fmt.pix.height = 1080
        fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_UYVY
        assert fmt.type == V4L2_BUF_TYPE_VIDEO_CAPTURE
        assert fmt.fmt.pix.width == 1920
        assert fmt.fmt.pix.height == 1080
        assert fmt.fmt.pix.pixelformat == V4L2_PIX_FMT_UYVY

    def test_v4l2_format_mplane(self):
        fmt = v4l2_format()
        ctypes.memset(ctypes.byref(fmt), 0, ctypes.sizeof(fmt))
        fmt.type = V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE
        fmt.fmt.pix_mp.width = 1280
        fmt.fmt.pix_mp.height = 720
        fmt.fmt.pix_mp.num_planes = 1
        fmt.fmt.pix_mp.plane_fmt[0].sizeimage = 1843200
        assert fmt.fmt.pix_mp.width == 1280
        assert fmt.fmt.pix_mp.plane_fmt[0].sizeimage == 1843200

    def test_v4l2_requestbuffers(self):
        reqbuf = v4l2_requestbuffers()
        ctypes.memset(ctypes.byref(reqbuf), 0, ctypes.sizeof(reqbuf))
        reqbuf.count = 6
        reqbuf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
        reqbuf.memory = V4L2_MEMORY_DMABUF
        assert reqbuf.count == 6
        assert reqbuf.type == V4L2_BUF_TYPE_VIDEO_CAPTURE
        assert reqbuf.memory == V4L2_MEMORY_DMABUF

    def test_v4l2_buffer_fields(self):
        buf = v4l2_buffer()
        ctypes.memset(ctypes.byref(buf), 0, ctypes.sizeof(buf))
        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
        buf.memory = V4L2_MEMORY_DMABUF
        buf.index = 3
        buf.m.fd = 42
        assert buf.index == 3
        assert buf.m.fd == 42

    def test_v4l2_control(self):
        ctrl = v4l2_control()
        ctrl.id = V4L2_CID_MPEG_VIDEO_BITRATE
        ctrl.value = 1_000_000
        assert ctrl.id == V4L2_CID_MPEG_VIDEO_BITRATE
        assert ctrl.value == 1_000_000

    def test_v4l2_plane(self):
        plane = v4l2_plane()
        ctypes.memset(ctypes.byref(plane), 0, ctypes.sizeof(plane))
        plane.bytesused = 12345
        plane.length = 65536
        plane.m.fd = 10
        assert plane.bytesused == 12345
        assert plane.length == 65536
        assert plane.m.fd == 10

    def test_v4l2_dv_timings(self):
        timings = v4l2_dv_timings()
        ctypes.memset(ctypes.byref(timings), 0, ctypes.sizeof(timings))
        timings.u.bt.width = 1920
        timings.u.bt.height = 1080
        timings.u.bt.pixelclock = 148500000
        assert timings.u.bt.width == 1920
        assert timings.u.bt.height == 1080

    def test_v4l2_edid(self):
        edid = v4l2_edid()
        ctypes.memset(ctypes.byref(edid), 0, ctypes.sizeof(edid))
        edid.pad = 0
        edid.start_block = 0
        edid.blocks = 2
        assert edid.blocks == 2

    def test_dma_heap_allocation_data(self):
        alloc = dma_heap_allocation_data()
        alloc.len = 1843200
        alloc.fd_flags = 0o2000002  # O_CLOEXEC | O_RDWR
        assert alloc.len == 1843200

    def test_dma_buf_sync(self):
        sync = dma_buf_sync()
        sync.flags = 5  # SYNC_READ | SYNC_END
        assert sync.flags == 5
