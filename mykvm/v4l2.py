"""V4L2 constants and ioctl numbers for Linux Video4Linux2 API.

These constants are derived from the Linux kernel headers:
- linux/videodev2.h
- linux/v4l2-common.h
- linux/v4l2-controls.h
"""

import ctypes
import struct

# ============================================================================
# FourCC pixel formats
# ============================================================================

def v4l2_fourcc(a: str, b: str, c: str, d: str) -> int:
    """Create a V4L2 FourCC code from 4 characters."""
    return (ord(a)) | (ord(b) << 8) | (ord(c) << 16) | (ord(d) << 24)


V4L2_PIX_FMT_YUYV = v4l2_fourcc('Y', 'U', 'Y', 'V')
V4L2_PIX_FMT_UYVY = v4l2_fourcc('U', 'Y', 'V', 'Y')
V4L2_PIX_FMT_RGB24 = v4l2_fourcc('R', 'G', 'B', '3')
V4L2_PIX_FMT_H264 = v4l2_fourcc('H', '2', '6', '4')

# ============================================================================
# Buffer types
# ============================================================================

V4L2_BUF_TYPE_VIDEO_CAPTURE = 1
V4L2_BUF_TYPE_VIDEO_OUTPUT = 2
V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE = 9
V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE = 10

# ============================================================================
# Memory types
# ============================================================================

V4L2_MEMORY_MMAP = 1
V4L2_MEMORY_USERPTR = 2
V4L2_MEMORY_OVERLAY = 3
V4L2_MEMORY_DMABUF = 4

# ============================================================================
# Capabilities
# ============================================================================

V4L2_CAP_VIDEO_CAPTURE = 0x00000001
V4L2_CAP_VIDEO_OUTPUT = 0x00000002
V4L2_CAP_VIDEO_M2M = 0x00008000
V4L2_CAP_VIDEO_M2M_MPLANE = 0x00004000
V4L2_CAP_STREAMING = 0x04000000

# ============================================================================
# Control IDs
# ============================================================================

V4L2_CID_MPEG_VIDEO_BITRATE = 0x009909CF
V4L2_CID_MPEG_VIDEO_GOP_SIZE = 0x009909CB
V4L2_CID_MPEG_VIDEO_B_FRAMES = 0x009909CA
V4L2_CID_MPEG_VIDEO_H264_PROFILE = 0x009909C7
V4L2_CID_MPEG_VIDEO_REPEAT_SEQ_HEADER = 0x009909E2
V4L2_CID_MPEG_VIDEO_FORCE_KEY_FRAME = 0x009909E5

V4L2_MPEG_VIDEO_H264_PROFILE_CONSTRAINED_BASELINE = 1

# ============================================================================
# ioctl request numbers (architecture-dependent, for ARM64/aarch64)
# ============================================================================

# ioctl direction bits
_IOC_NONE = 0
_IOC_WRITE = 1
_IOC_READ = 2

_IOC_NRBITS = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14
_IOC_DIRBITS = 2

_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS
_IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS
_IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS


def _IOC(direction: int, type_: int, nr: int, size: int) -> int:
    return (direction << _IOC_DIRSHIFT) | (type_ << _IOC_TYPESHIFT) | \
           (nr << _IOC_NRSHIFT) | (size << _IOC_SIZESHIFT)


def _IOR(type_: int, nr: int, size: int) -> int:
    return _IOC(_IOC_READ, type_, nr, size)


def _IOW(type_: int, nr: int, size: int) -> int:
    return _IOC(_IOC_WRITE, type_, nr, size)


def _IOWR(type_: int, nr: int, size: int) -> int:
    return _IOC(_IOC_READ | _IOC_WRITE, type_, nr, size)


# V4L2 ioctl codes
_V = ord('V')

VIDIOC_QUERYCAP = _IOR(_V, 0, 104)  # struct v4l2_capability
VIDIOC_G_FMT = _IOWR(_V, 4, 208)  # struct v4l2_format
VIDIOC_S_FMT = _IOWR(_V, 5, 208)  # struct v4l2_format
VIDIOC_REQBUFS = _IOWR(_V, 8, 20)  # struct v4l2_requestbuffers
VIDIOC_QUERYBUF = _IOWR(_V, 9, 88)  # struct v4l2_buffer (single-plane)
VIDIOC_QBUF = _IOWR(_V, 15, 88)  # struct v4l2_buffer
VIDIOC_DQBUF = _IOWR(_V, 17, 88)  # struct v4l2_buffer
VIDIOC_STREAMON = _IOW(_V, 18, 4)  # int
VIDIOC_STREAMOFF = _IOW(_V, 19, 4)  # int
VIDIOC_S_CTRL = _IOWR(_V, 28, 8)  # struct v4l2_control
VIDIOC_QUERY_DV_TIMINGS = _IOR(_V, 99, 136)  # struct v4l2_dv_timings
VIDIOC_S_DV_TIMINGS = _IOWR(_V, 87, 136)  # struct v4l2_dv_timings
VIDIOC_S_EDID = _IOWR(_V, 41, 1032)  # struct v4l2_edid

# ============================================================================
# DMA heap / DMA buf ioctl
# ============================================================================

# struct dma_heap_allocation_data size = 32
DMA_HEAP_IOCTL_ALLOC = _IOWR(ord('H'), 0, 32)

# DMA_BUF_SYNC flags
DMA_BUF_SYNC_READ = 1
DMA_BUF_SYNC_WRITE = 2
DMA_BUF_SYNC_RW = DMA_BUF_SYNC_READ | DMA_BUF_SYNC_WRITE
DMA_BUF_SYNC_START = 0
DMA_BUF_SYNC_END = 4

# struct dma_buf_sync size = 8
DMA_BUF_IOCTL_SYNC = _IOW(ord('b'), 0, 8)

# ============================================================================
# ctypes structures for V4L2
# ============================================================================


class v4l2_capability(ctypes.Structure):
    _fields_ = [
        ('driver', ctypes.c_char * 16),
        ('card', ctypes.c_char * 32),
        ('bus_info', ctypes.c_char * 32),
        ('version', ctypes.c_uint32),
        ('capabilities', ctypes.c_uint32),
        ('device_caps', ctypes.c_uint32),
        ('reserved', ctypes.c_uint32 * 3),
    ]


class v4l2_pix_format(ctypes.Structure):
    _fields_ = [
        ('width', ctypes.c_uint32),
        ('height', ctypes.c_uint32),
        ('pixelformat', ctypes.c_uint32),
        ('field', ctypes.c_uint32),
        ('bytesperline', ctypes.c_uint32),
        ('sizeimage', ctypes.c_uint32),
        ('colorspace', ctypes.c_uint32),
        ('priv', ctypes.c_uint32),
        ('flags', ctypes.c_uint32),
        ('_ycbcr_hsv_enc', ctypes.c_uint32),
        ('quantization', ctypes.c_uint32),
        ('xfer_func', ctypes.c_uint32),
    ]


class v4l2_plane_pix_format(ctypes.Structure):
    _fields_ = [
        ('sizeimage', ctypes.c_uint32),
        ('bytesperline', ctypes.c_uint32),
        ('reserved', ctypes.c_uint16 * 6),
    ]


class v4l2_pix_format_mplane(ctypes.Structure):
    _fields_ = [
        ('width', ctypes.c_uint32),
        ('height', ctypes.c_uint32),
        ('pixelformat', ctypes.c_uint32),
        ('field', ctypes.c_uint32),
        ('colorspace', ctypes.c_uint32),
        ('plane_fmt', v4l2_plane_pix_format * 8),
        ('num_planes', ctypes.c_uint8),
        ('flags', ctypes.c_uint8),
        ('_ycbcr_hsv_enc', ctypes.c_uint8),
        ('quantization', ctypes.c_uint8),
        ('xfer_func', ctypes.c_uint8),
        ('reserved', ctypes.c_uint8 * 7),
    ]


class v4l2_format_fmt(ctypes.Union):
    _fields_ = [
        ('pix', v4l2_pix_format),
        ('pix_mp', v4l2_pix_format_mplane),
        ('raw_data', ctypes.c_uint8 * 200),
    ]


class v4l2_format(ctypes.Structure):
    _fields_ = [
        ('type', ctypes.c_uint32),
        ('fmt', v4l2_format_fmt),
        ('_padding', ctypes.c_uint32),  # Ensure correct size
    ]


class v4l2_requestbuffers(ctypes.Structure):
    _fields_ = [
        ('count', ctypes.c_uint32),
        ('type', ctypes.c_uint32),
        ('memory', ctypes.c_uint32),
        ('capabilities', ctypes.c_uint32),
        ('flags', ctypes.c_uint8),
        ('reserved', ctypes.c_uint8 * 3),
    ]


class v4l2_plane_m(ctypes.Union):
    _fields_ = [
        ('mem_offset', ctypes.c_uint32),
        ('userptr', ctypes.c_ulong),
        ('fd', ctypes.c_int32),
    ]


class v4l2_plane(ctypes.Structure):
    _fields_ = [
        ('bytesused', ctypes.c_uint32),
        ('length', ctypes.c_uint32),
        ('m', v4l2_plane_m),
        ('data_offset', ctypes.c_uint32),
        ('reserved', ctypes.c_uint32 * 11),
    ]


class v4l2_buffer_m(ctypes.Union):
    _fields_ = [
        ('offset', ctypes.c_uint32),
        ('userptr', ctypes.c_ulong),
        ('planes', ctypes.POINTER(v4l2_plane)),
        ('fd', ctypes.c_int32),
    ]


class v4l2_timeval(ctypes.Structure):
    _fields_ = [
        ('tv_sec', ctypes.c_long),
        ('tv_usec', ctypes.c_long),
    ]


class v4l2_buffer(ctypes.Structure):
    _fields_ = [
        ('index', ctypes.c_uint32),
        ('type', ctypes.c_uint32),
        ('bytesused', ctypes.c_uint32),
        ('flags', ctypes.c_uint32),
        ('field', ctypes.c_uint32),
        ('timestamp', v4l2_timeval),
        ('timecode_type', ctypes.c_uint32),
        ('timecode_flags', ctypes.c_uint32),
        ('timecode_frames', ctypes.c_uint8),
        ('timecode_seconds', ctypes.c_uint8),
        ('timecode_minutes', ctypes.c_uint8),
        ('timecode_hours', ctypes.c_uint8),
        ('timecode_userbits', ctypes.c_uint8 * 4),
        ('sequence', ctypes.c_uint32),
        ('memory', ctypes.c_uint32),
        ('m', v4l2_buffer_m),
        ('length', ctypes.c_uint32),
        ('reserved2', ctypes.c_uint32),
        ('_union', ctypes.c_uint32),
    ]


class v4l2_control(ctypes.Structure):
    _fields_ = [
        ('id', ctypes.c_uint32),
        ('value', ctypes.c_int32),
    ]


class v4l2_bt_timings(ctypes.Structure):
    _fields_ = [
        ('width', ctypes.c_uint32),
        ('height', ctypes.c_uint32),
        ('interlaced', ctypes.c_uint32),
        ('polarities', ctypes.c_uint32),
        ('pixelclock', ctypes.c_uint64),
        ('hfrontporch', ctypes.c_uint32),
        ('hsync', ctypes.c_uint32),
        ('hbackporch', ctypes.c_uint32),
        ('vfrontporch', ctypes.c_uint32),
        ('vsync', ctypes.c_uint32),
        ('vbackporch', ctypes.c_uint32),
        ('il_vfrontporch', ctypes.c_uint32),
        ('il_vsync', ctypes.c_uint32),
        ('il_vbackporch', ctypes.c_uint32),
        ('standards', ctypes.c_uint32),
        ('flags', ctypes.c_uint32),
        ('picture_aspect_width', ctypes.c_uint32),
        ('picture_aspect_height', ctypes.c_uint32),
        ('cea861_vic', ctypes.c_uint8),
        ('hdmi_vic', ctypes.c_uint8),
        ('reserved', ctypes.c_uint8 * 46),
    ]


class v4l2_dv_timings_u(ctypes.Union):
    _fields_ = [
        ('bt', v4l2_bt_timings),
        ('reserved', ctypes.c_uint32 * 32),
    ]


class v4l2_dv_timings(ctypes.Structure):
    _fields_ = [
        ('type', ctypes.c_uint32),
        ('_pad', ctypes.c_uint32),
        ('u', v4l2_dv_timings_u),
    ]


class v4l2_edid(ctypes.Structure):
    _fields_ = [
        ('pad', ctypes.c_uint32),
        ('start_block', ctypes.c_uint32),
        ('blocks', ctypes.c_uint32),
        ('reserved', ctypes.c_uint32),
        ('edid', ctypes.POINTER(ctypes.c_uint8)),
    ]


class dma_heap_allocation_data(ctypes.Structure):
    _fields_ = [
        ('len', ctypes.c_uint64),
        ('fd', ctypes.c_uint32),
        ('fd_flags', ctypes.c_uint32),
        ('heap_flags', ctypes.c_uint64),
    ]


class dma_buf_sync(ctypes.Structure):
    _fields_ = [
        ('flags', ctypes.c_uint64),
    ]
