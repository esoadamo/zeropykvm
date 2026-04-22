"""V4L2 Memory-to-Memory (M2M) Encoder with DMABUF support.

Hardware H.264 encoding via bcm2835-codec-encode (/dev/video11).
This encoder uses external DMABUF buffers for zero-copy input from capture device.

Reference: https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/dev-encoder.html
"""

import ctypes
import ctypes.util
import logging
import mmap
import os
import select
from dataclasses import dataclass

from . import v4l2
from .dma import DmaBuffer
from .utils import fourcc_to_string, ioctl_raw

logger = logging.getLogger(__name__)

# Load libc for mmap/munmap
_libc_path = ctypes.util.find_library("c")
if _libc_path is None:
    raise RuntimeError("Could not find libc; encoder support is unavailable")
_libc = ctypes.CDLL(_libc_path, use_errno=True)


@dataclass
class MappedBuffer:
    """Memory-mapped buffer info for CAPTURE/output buffers."""
    mm: mmap.mmap
    length: int
    plane_length: int
    offset: int


@dataclass
class EncoderConfig:
    """Encoder configuration."""
    width: int = 1280
    height: int = 720
    input_format: int = v4l2.V4L2_PIX_FMT_YUYV
    output_format: int = v4l2.V4L2_PIX_FMT_H264
    bitrate: int = 1_000_000
    gop_size: int = 3
    bytesperline: int | None = None
    sizeimage: int | None = None


@dataclass
class EncodeResult:
    """Result of encoding a frame."""
    data: bytes
    reclaimed_idx: int | None


def _set_control(fd: int, ctrl_id: int, value: int) -> None:
    """Set a V4L2 control value."""
    ctrl = v4l2.v4l2_control()
    ctrl.id = ctrl_id
    ctrl.value = value
    try:
        ioctl_raw(fd, v4l2.VIDIOC_S_CTRL, ctypes.byref(ctrl))
    except OSError:
        logger.warning("Failed to set control 0x%x = %d", ctrl_id, value)


class Encoder:
    """V4L2 M2M Encoder with DMABUF input."""

    def __init__(self):
        self.fd: int = -1
        self.config: EncoderConfig | None = None
        self.num_buffers: int = 0
        self.input_sizeimage: int = 0
        self.dmabuf_fds: list[int] = []
        self.capture_buffers: list[MappedBuffer] = []
        self.streaming: bool = False

    def init(self, device: str, config: EncoderConfig,
             dmabuf_buffers: list[DmaBuffer]) -> None:
        """Initialize the M2M encoder with external DMABUF buffers for input.

        Args:
            device: Path to encoder device (e.g., /dev/video11).
            config: Encoder configuration.
            dmabuf_buffers: List of DmaBuffer objects for zero-copy input.

        Raises:
            OSError: If encoder initialization fails.
        """
        logger.info("Opening encoder device %s...", device)
        logger.info("Using DMABUF for zero-copy input")

        self.config = config
        self.fd = os.open(device, os.O_RDWR)

        try:
            # Query capabilities
            cap = v4l2.v4l2_capability()
            ioctl_raw(self.fd, v4l2.VIDIOC_QUERYCAP, ctypes.byref(cap))

            if not (cap.capabilities & v4l2.V4L2_CAP_VIDEO_M2M_MPLANE):
                raise RuntimeError("Device does not support M2M multiplanar")
            if not (cap.capabilities & v4l2.V4L2_CAP_STREAMING):
                raise RuntimeError("Device does not support streaming")

            # Calculate frame size
            _3bpp_fmts = {v4l2.V4L2_PIX_FMT_RGB24, v4l2.V4L2_PIX_FMT_BGR24}
            if config.input_format in _3bpp_fmts:
                bpp = 3
            else:
                bpp = 2
            bytesperline = config.bytesperline if config.bytesperline is not None \
                else config.width * bpp
            sizeimage = config.sizeimage if config.sizeimage is not None \
                else config.width * config.height * bpp
            self.input_sizeimage = sizeimage

            # Set OUTPUT format (raw frames input)
            fmt_out = v4l2.v4l2_format()
            ctypes.memset(ctypes.byref(fmt_out), 0, ctypes.sizeof(fmt_out))
            fmt_out.type = v4l2.V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE
            fmt_out.fmt.pix_mp.width = config.width
            fmt_out.fmt.pix_mp.height = config.height
            fmt_out.fmt.pix_mp.pixelformat = config.input_format
            fmt_out.fmt.pix_mp.num_planes = 1
            fmt_out.fmt.pix_mp.plane_fmt[0].sizeimage = sizeimage
            fmt_out.fmt.pix_mp.plane_fmt[0].bytesperline = bytesperline
            ioctl_raw(self.fd, v4l2.VIDIOC_S_FMT, ctypes.byref(fmt_out))

            out_fmt_str = fourcc_to_string(fmt_out.fmt.pix_mp.pixelformat)
            logger.info("OUTPUT format: %s %dx%d, sizeimage=%d",
                        out_fmt_str, fmt_out.fmt.pix_mp.width,
                        fmt_out.fmt.pix_mp.height,
                        fmt_out.fmt.pix_mp.plane_fmt[0].sizeimage)

            # Set CAPTURE format (H.264 output)
            fmt_cap = v4l2.v4l2_format()
            ctypes.memset(ctypes.byref(fmt_cap), 0, ctypes.sizeof(fmt_cap))
            fmt_cap.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE
            fmt_cap.fmt.pix_mp.width = config.width
            fmt_cap.fmt.pix_mp.height = config.height
            fmt_cap.fmt.pix_mp.pixelformat = config.output_format
            fmt_cap.fmt.pix_mp.num_planes = 1
            ioctl_raw(self.fd, v4l2.VIDIOC_S_FMT, ctypes.byref(fmt_cap))

            cap_fmt_str = fourcc_to_string(fmt_cap.fmt.pix_mp.pixelformat)
            logger.info("CAPTURE format: %s %dx%d, sizeimage=%d",
                        cap_fmt_str, fmt_cap.fmt.pix_mp.width,
                        fmt_cap.fmt.pix_mp.height,
                        fmt_cap.fmt.pix_mp.plane_fmt[0].sizeimage)

            # Set encoder controls
            _set_control(self.fd, v4l2.V4L2_CID_MPEG_VIDEO_BITRATE, config.bitrate)
            _set_control(self.fd, v4l2.V4L2_CID_MPEG_VIDEO_GOP_SIZE, config.gop_size)
            _set_control(self.fd, v4l2.V4L2_CID_MPEG_VIDEO_B_FRAMES, 0)
            _set_control(self.fd, v4l2.V4L2_CID_MPEG_VIDEO_H264_PROFILE,
                         v4l2.V4L2_MPEG_VIDEO_H264_PROFILE_CONSTRAINED_BASELINE)
            _set_control(self.fd, v4l2.V4L2_CID_MPEG_VIDEO_REPEAT_SEQ_HEADER, 1)

            self.num_buffers = len(dmabuf_buffers)

            # Request OUTPUT buffers (DMABUF mode)
            reqbuf_out = v4l2.v4l2_requestbuffers()
            ctypes.memset(ctypes.byref(reqbuf_out), 0, ctypes.sizeof(reqbuf_out))
            reqbuf_out.count = self.num_buffers
            reqbuf_out.type = v4l2.V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE
            reqbuf_out.memory = v4l2.V4L2_MEMORY_DMABUF
            ioctl_raw(self.fd, v4l2.VIDIOC_REQBUFS, ctypes.byref(reqbuf_out))
            logger.info("Requested %d OUTPUT DMABUF buffers", reqbuf_out.count)

            # Request CAPTURE buffers (MMAP mode)
            reqbuf_cap = v4l2.v4l2_requestbuffers()
            ctypes.memset(ctypes.byref(reqbuf_cap), 0, ctypes.sizeof(reqbuf_cap))
            reqbuf_cap.count = self.num_buffers
            reqbuf_cap.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE
            reqbuf_cap.memory = v4l2.V4L2_MEMORY_MMAP
            ioctl_raw(self.fd, v4l2.VIDIOC_REQBUFS, ctypes.byref(reqbuf_cap))
            logger.info("Allocated %d CAPTURE buffers (MMAP)", reqbuf_cap.count)

            # Store DMABUF fds
            self.dmabuf_fds = [buf.fd for buf in dmabuf_buffers]

            # Query and mmap CAPTURE buffers, then queue them
            cap_count = reqbuf_cap.count
            self.capture_buffers = []

            for i in range(cap_count):
                plane = v4l2.v4l2_plane()
                ctypes.memset(ctypes.byref(plane), 0, ctypes.sizeof(plane))

                buf = v4l2.v4l2_buffer()
                ctypes.memset(ctypes.byref(buf), 0, ctypes.sizeof(buf))
                buf.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE
                buf.memory = v4l2.V4L2_MEMORY_MMAP
                buf.index = i
                buf.length = 1
                buf.m.planes = ctypes.pointer(plane)
                ioctl_raw(self.fd, v4l2.VIDIOC_QUERYBUF, ctypes.byref(buf))

                length = plane.length
                offset = plane.m.mem_offset

                # mmap the buffer
                mm = mmap.mmap(self.fd, length, mmap.MAP_SHARED,
                               mmap.PROT_READ | mmap.PROT_WRITE, offset=offset)

                self.capture_buffers.append(MappedBuffer(
                    mm=mm, length=length, plane_length=length, offset=offset
                ))

                # Queue CAPTURE buffer
                plane2 = v4l2.v4l2_plane()
                ctypes.memset(ctypes.byref(plane2), 0, ctypes.sizeof(plane2))
                plane2.length = length

                buf2 = v4l2.v4l2_buffer()
                ctypes.memset(ctypes.byref(buf2), 0, ctypes.sizeof(buf2))
                buf2.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE
                buf2.memory = v4l2.V4L2_MEMORY_MMAP
                buf2.index = i
                buf2.length = 1
                buf2.m.planes = ctypes.pointer(plane2)
                ioctl_raw(self.fd, v4l2.VIDIOC_QBUF, ctypes.byref(buf2))

            logger.info("Mapped and queued %d CAPTURE buffers", cap_count)

            # Start streaming
            type_out = ctypes.c_uint32(v4l2.V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE)
            ioctl_raw(self.fd, v4l2.VIDIOC_STREAMON, ctypes.byref(type_out))

            type_cap = ctypes.c_uint32(v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE)
            ioctl_raw(self.fd, v4l2.VIDIOC_STREAMON, ctypes.byref(type_cap))

            self.streaming = True
            logger.info("Encoder initialized and streaming")

        except Exception:
            os.close(self.fd)
            self.fd = -1
            raise

    def encode_from_buffer(self, index: int, bytes_used: int) -> EncodeResult:
        """Encode a frame from the DMABUF at given index.

        The buffer must have been filled by the capture device first.

        Args:
            index: Buffer index.
            bytes_used: Number of bytes used in the buffer.

        Returns:
            EncodeResult with encoded H.264 data and reclaimed buffer index.

        Raises:
            RuntimeError: If encoder is not streaming.
            OSError: If encode operation fails.
        """
        if not self.streaming:
            raise RuntimeError("Encoder not streaming")

        # Queue OUTPUT buffer with DMABUF fd
        out_plane = v4l2.v4l2_plane()
        ctypes.memset(ctypes.byref(out_plane), 0, ctypes.sizeof(out_plane))
        out_plane.bytesused = bytes_used
        out_plane.length = self.input_sizeimage
        out_plane.m.fd = self.dmabuf_fds[index]

        qbuf_out = v4l2.v4l2_buffer()
        ctypes.memset(ctypes.byref(qbuf_out), 0, ctypes.sizeof(qbuf_out))
        qbuf_out.type = v4l2.V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE
        qbuf_out.memory = v4l2.V4L2_MEMORY_DMABUF
        qbuf_out.index = index
        qbuf_out.length = 1
        qbuf_out.m.planes = ctypes.pointer(out_plane)
        ioctl_raw(self.fd, v4l2.VIDIOC_QBUF, ctypes.byref(qbuf_out))

        # Wait for CAPTURE buffer
        readable, _, _ = select.select([self.fd], [], [], 5.0)
        if not readable:
            raise TimeoutError("Encoder poll timeout")

        # Dequeue CAPTURE buffer
        cap_plane = v4l2.v4l2_plane()
        ctypes.memset(ctypes.byref(cap_plane), 0, ctypes.sizeof(cap_plane))

        dqbuf_cap = v4l2.v4l2_buffer()
        ctypes.memset(ctypes.byref(dqbuf_cap), 0, ctypes.sizeof(dqbuf_cap))
        dqbuf_cap.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE
        dqbuf_cap.memory = v4l2.V4L2_MEMORY_MMAP
        dqbuf_cap.length = 1
        dqbuf_cap.m.planes = ctypes.pointer(cap_plane)
        ioctl_raw(self.fd, v4l2.VIDIOC_DQBUF, ctypes.byref(dqbuf_cap))

        cap_idx = dqbuf_cap.index
        encoded_size = cap_plane.bytesused

        # Read encoded data from mmap'd buffer
        cap_buf = self.capture_buffers[cap_idx]
        cap_buf.mm.seek(0)
        encoded_data = cap_buf.mm.read(encoded_size)

        # Re-queue CAPTURE buffer
        requeue_plane = v4l2.v4l2_plane()
        ctypes.memset(ctypes.byref(requeue_plane), 0, ctypes.sizeof(requeue_plane))
        requeue_plane.length = cap_buf.plane_length

        reqbuf_cap = v4l2.v4l2_buffer()
        ctypes.memset(ctypes.byref(reqbuf_cap), 0, ctypes.sizeof(reqbuf_cap))
        reqbuf_cap.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE
        reqbuf_cap.memory = v4l2.V4L2_MEMORY_MMAP
        reqbuf_cap.index = cap_idx
        reqbuf_cap.length = 1
        reqbuf_cap.m.planes = ctypes.pointer(requeue_plane)
        ioctl_raw(self.fd, v4l2.VIDIOC_QBUF, ctypes.byref(reqbuf_cap))

        # Try to dequeue OUTPUT buffer
        reclaimed = self.reclaim_output_buffer()

        return EncodeResult(data=encoded_data, reclaimed_idx=reclaimed)

    def reclaim_output_buffer(self) -> int | None:
        """Try to reclaim an OUTPUT buffer.

        Returns:
            Buffer index if reclaimed, None otherwise.
        """
        out_plane = v4l2.v4l2_plane()
        ctypes.memset(ctypes.byref(out_plane), 0, ctypes.sizeof(out_plane))

        dqbuf_out = v4l2.v4l2_buffer()
        ctypes.memset(ctypes.byref(dqbuf_out), 0, ctypes.sizeof(dqbuf_out))
        dqbuf_out.type = v4l2.V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE
        dqbuf_out.memory = v4l2.V4L2_MEMORY_DMABUF
        dqbuf_out.length = 1
        dqbuf_out.m.planes = ctypes.pointer(out_plane)

        try:
            ioctl_raw(self.fd, v4l2.VIDIOC_DQBUF, ctypes.byref(dqbuf_out))
            return dqbuf_out.index
        except OSError:
            return None

    def force_key_frame(self) -> None:
        """Force generation of a key frame."""
        _set_control(self.fd, v4l2.V4L2_CID_MPEG_VIDEO_FORCE_KEY_FRAME, 1)

    def close(self) -> None:
        """Stop encoding and release resources."""
        if self.streaming:
            type_out = ctypes.c_uint32(v4l2.V4L2_BUF_TYPE_VIDEO_OUTPUT_MPLANE)
            try:
                ioctl_raw(self.fd, v4l2.VIDIOC_STREAMOFF, ctypes.byref(type_out))
            except OSError:
                pass

            type_cap = ctypes.c_uint32(v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE)
            try:
                ioctl_raw(self.fd, v4l2.VIDIOC_STREAMOFF, ctypes.byref(type_cap))
            except OSError:
                pass

            self.streaming = False

        # Unmap CAPTURE buffers
        for buf in self.capture_buffers:
            try:
                buf.mm.close()
            except Exception:
                pass
        self.capture_buffers.clear()

        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

        logger.info("Encoder deinitialized")

    def __del__(self):
        if self.fd >= 0:
            self.close()
