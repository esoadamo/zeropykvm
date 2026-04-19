"""Native V4L2 Capture with DMABUF support.

This bypasses libv4l2cpp to enable zero-copy buffer sharing with encoder.
"""

import ctypes
import logging
import os
import select
from dataclasses import dataclass

from . import v4l2
from .dma import DmaBuffer
from .utils import fourcc_to_string, ioctl_raw

logger = logging.getLogger(__name__)


@dataclass
class DequeueResult:
    """Result of dequeuing a buffer."""
    index: int
    bytesused: int


class Capture:
    """V4L2 Capture device with DMABUF support."""

    def __init__(self):
        self.fd: int = -1
        self.width: int = 0
        self.height: int = 0
        self.format: int = 0
        self.buffer_size: int = 0
        self.num_buffers: int = 0
        self.dmabuf_fds: list[int] = []
        self.streaming: bool = False

    def init(self, device: str, pixel_format: int, dmabuf_buffers: list[DmaBuffer]) -> None:
        """Initialize capture device with external DMABUF buffers.

        Args:
            device: Path to the V4L2 capture device (e.g., /dev/video0).
            pixel_format: V4L2 pixel format (e.g., V4L2_PIX_FMT_UYVY).
            dmabuf_buffers: List of DmaBuffer objects for zero-copy capture.

        Raises:
            OSError: If device initialization fails.
        """
        logger.info("Opening %s...", device)

        self.fd = os.open(device, os.O_RDWR)

        try:
            # Query capabilities
            cap = v4l2.v4l2_capability()
            ioctl_raw(self.fd, v4l2.VIDIOC_QUERYCAP, ctypes.byref(cap))

            if not (cap.capabilities & v4l2.V4L2_CAP_VIDEO_CAPTURE):
                raise RuntimeError("Device does not support capture")
            if not (cap.capabilities & v4l2.V4L2_CAP_STREAMING):
                raise RuntimeError("Device does not support streaming")

            # Get current format to learn resolution
            fmt = v4l2.v4l2_format()
            ctypes.memset(ctypes.byref(fmt), 0, ctypes.sizeof(fmt))
            fmt.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
            ioctl_raw(self.fd, v4l2.VIDIOC_G_FMT, ctypes.byref(fmt))

            current_width = fmt.fmt.pix.width
            current_height = fmt.fmt.pix.height

            # Set desired format
            fmt.fmt.pix.pixelformat = pixel_format
            ioctl_raw(self.fd, v4l2.VIDIOC_S_FMT, ctypes.byref(fmt))

            self.width = fmt.fmt.pix.width
            self.height = fmt.fmt.pix.height
            self.format = fmt.fmt.pix.pixelformat
            self.buffer_size = fmt.fmt.pix.sizeimage

            fmt_str = fourcc_to_string(self.format)
            logger.info("Format %s %dx%d, buffer size %d",
                        fmt_str, self.width, self.height, self.buffer_size)

            if current_width != self.width or current_height != self.height:
                logger.info("Resolution changed from %dx%d to %dx%d",
                            current_width, current_height, self.width, self.height)

            self.num_buffers = len(dmabuf_buffers)

            # Request buffers with DMABUF memory type
            reqbuf = v4l2.v4l2_requestbuffers()
            ctypes.memset(ctypes.byref(reqbuf), 0, ctypes.sizeof(reqbuf))
            reqbuf.count = self.num_buffers
            reqbuf.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
            reqbuf.memory = v4l2.V4L2_MEMORY_DMABUF
            ioctl_raw(self.fd, v4l2.VIDIOC_REQBUFS, ctypes.byref(reqbuf))

            logger.info("Requested %d DMABUF buffers", reqbuf.count)

            # Store dmabuf fds
            self.dmabuf_fds = [buf.fd for buf in dmabuf_buffers]

            # Queue all buffers
            for i in range(self.num_buffers):
                buf = v4l2.v4l2_buffer()
                ctypes.memset(ctypes.byref(buf), 0, ctypes.sizeof(buf))
                buf.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
                buf.memory = v4l2.V4L2_MEMORY_DMABUF
                buf.index = i
                buf.m.fd = self.dmabuf_fds[i]
                ioctl_raw(self.fd, v4l2.VIDIOC_QBUF, ctypes.byref(buf))

            logger.info("Queued %d buffers", self.num_buffers)

            # Start streaming
            buf_type = ctypes.c_uint32(v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE)
            ioctl_raw(self.fd, v4l2.VIDIOC_STREAMON, ctypes.byref(buf_type))

            self.streaming = True
            logger.info("Streaming started")

        except Exception:
            os.close(self.fd)
            self.fd = -1
            raise

    def dequeue_buffer(self, timeout_ms: int = 2000) -> DequeueResult:
        """Wait for a buffer to be ready and dequeue it.

        Args:
            timeout_ms: Timeout in milliseconds.

        Returns:
            DequeueResult with buffer index and bytes used.

        Raises:
            TimeoutError: If no buffer is ready within timeout.
            OSError: If dequeue fails.
        """
        # Poll for readability
        timeout_sec = timeout_ms / 1000.0
        readable, _, _ = select.select([self.fd], [], [], timeout_sec)

        if not readable:
            raise TimeoutError("Capture buffer dequeue timeout")

        # Dequeue buffer
        buf = v4l2.v4l2_buffer()
        ctypes.memset(ctypes.byref(buf), 0, ctypes.sizeof(buf))
        buf.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
        buf.memory = v4l2.V4L2_MEMORY_DMABUF
        ioctl_raw(self.fd, v4l2.VIDIOC_DQBUF, ctypes.byref(buf))

        return DequeueResult(index=buf.index, bytesused=buf.bytesused)

    def queue_buffer(self, index: int) -> None:
        """Re-queue a buffer for capture.

        Args:
            index: Buffer index to re-queue.

        Raises:
            OSError: If queue fails.
        """
        buf = v4l2.v4l2_buffer()
        ctypes.memset(ctypes.byref(buf), 0, ctypes.sizeof(buf))
        buf.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
        buf.memory = v4l2.V4L2_MEMORY_DMABUF
        buf.index = index
        buf.m.fd = self.dmabuf_fds[index]
        ioctl_raw(self.fd, v4l2.VIDIOC_QBUF, ctypes.byref(buf))

    def close(self) -> None:
        """Stop streaming and release resources."""
        if self.streaming:
            buf_type = ctypes.c_uint32(v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE)
            try:
                ioctl_raw(self.fd, v4l2.VIDIOC_STREAMOFF, ctypes.byref(buf_type))
            except OSError:
                pass
            self.streaming = False

        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1
            logger.info("Capture closed")

    def __del__(self):
        if self.fd >= 0:
            self.close()
