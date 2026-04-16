"""Zero-copy V4L2 video pipeline.

Uses shared DMABUF between capture and encoder for zero-copy operation.
Reference: https://www.kernel.org/doc/html/latest/userspace-api/dma-buf-alloc-exchange.html
"""

import ctypes
import logging
import os
import time

from . import v4l2
from .capture import Capture
from .dma import DmaBuffer, DmaHeap
from .edid import wait_for_signal
from .encode import Encoder, EncoderConfig
from .server import Server
from .utils import fourcc_to_string, ioctl_raw

logger = logging.getLogger(__name__)

NUM_BUFFERS = 6


def _probe_format(device: str) -> dict:
    """Probe the capture device for current format.

    Args:
        device: Path to the V4L2 capture device.

    Returns:
        Dict with width, height, buffer_size, bytesperline.

    Raises:
        OSError: If probing fails.
    """
    fd = os.open(device, os.O_RDWR | os.O_NONBLOCK)
    try:
        # Query capabilities
        cap = v4l2.v4l2_capability()
        ioctl_raw(fd, v4l2.VIDIOC_QUERYCAP, ctypes.byref(cap))

        if not (cap.capabilities & v4l2.V4L2_CAP_VIDEO_CAPTURE):
            raise RuntimeError("Device does not support capture")

        # Get current format
        fmt = v4l2.v4l2_format()
        ctypes.memset(ctypes.byref(fmt), 0, ctypes.sizeof(fmt))
        fmt.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
        ioctl_raw(fd, v4l2.VIDIOC_G_FMT, ctypes.byref(fmt))

        # Set UYVY format
        fmt.fmt.pix.pixelformat = v4l2.V4L2_PIX_FMT_UYVY
        ioctl_raw(fd, v4l2.VIDIOC_S_FMT, ctypes.byref(fmt))

        # Read back
        ioctl_raw(fd, v4l2.VIDIOC_G_FMT, ctypes.byref(fmt))

        width = fmt.fmt.pix.width
        height = fmt.fmt.pix.height
        buffer_size = fmt.fmt.pix.sizeimage
        bytesperline = fmt.fmt.pix.bytesperline

        fmt_str = fourcc_to_string(fmt.fmt.pix.pixelformat)
        logger.info("Probe: Format %s %dx%d, sizeimage=%d, bytesperline=%d",
                     fmt_str, width, height, buffer_size, bytesperline)

        return {
            "width": width,
            "height": height,
            "buffer_size": buffer_size,
            "bytesperline": bytesperline,
        }
    finally:
        os.close(fd)


def _run_session(server: Server, capture_device: str, encoder_device: str,
                  bitrate: int, first_run: bool) -> None:
    """Run a single capture/encode session.

    Args:
        server: Server instance for broadcasting.
        capture_device: Path to capture device.
        encoder_device: Path to encoder device.
        bitrate: Encoder bitrate.
        first_run: Whether this is the first session.

    Raises:
        Various exceptions on failure.
    """
    logger.info("Starting zero-copy session...")
    logger.info("Capture device: %s", capture_device)
    logger.info("Encoder device: %s, bitrate: %d", encoder_device, bitrate)

    format_info = _probe_format(capture_device)
    logger.info("Capture format: %dx%d, buffer size: %d bytes",
                format_info["width"], format_info["height"], format_info["buffer_size"])

    # Open DMA Heap
    logger.info("Opening DMA Heap...")
    heap = DmaHeap()
    heap.open()

    try:
        logger.info("Allocating %d shared DMABUF buffers (%d bytes each)...",
                     NUM_BUFFERS, format_info["buffer_size"])
        dma_buffers: list[DmaBuffer] = []
        try:
            for i in range(NUM_BUFFERS):
                buf = heap.alloc(format_info["buffer_size"])
                dma_buffers.append(buf)
                logger.info("Allocated DMA buffer %d, fd=%d", i, buf.fd)
        except Exception:
            for buf in dma_buffers:
                buf.close()
            raise

        try:
            # Initialize encoder
            logger.info("Initializing M2M encoder with shared DMABUF...")
            enc = Encoder()
            enc.init(encoder_device, EncoderConfig(
                width=format_info["width"],
                height=format_info["height"],
                input_format=v4l2.V4L2_PIX_FMT_UYVY,
                output_format=v4l2.V4L2_PIX_FMT_H264,
                bitrate=bitrate,
                bytesperline=format_info["bytesperline"],
                sizeimage=format_info["buffer_size"],
            ), dma_buffers)

            try:
                # Initialize capture
                logger.info("Initializing V4L2 capture with shared DMABUF...")
                cap = Capture()
                cap.init(capture_device, v4l2.V4L2_PIX_FMT_UYVY, dma_buffers)

                try:
                    logger.info("Zero-copy pipeline ready, starting capture loop...")

                    timeout_count = 0
                    while True:
                        try:
                            cap_result = cap.dequeue_buffer(2000)
                        except TimeoutError:
                            timeout_count += 1
                            if timeout_count >= 3:
                                logger.warning("Too many capture timeouts, exiting session")
                                break
                            continue
                        except OSError as e:
                            logger.error("Capture dequeue error: %s", e)
                            if first_run:
                                raise
                            break

                        timeout_count = 0

                        try:
                            enc_result = enc.encode_from_buffer(
                                cap_result.index, cap_result.bytesused)
                        except Exception as e:
                            logger.error("Encode error: %s", e)
                            try:
                                cap.queue_buffer(cap_result.index)
                            except OSError as qerr:
                                logger.error("Failed to re-queue capture buffer: %s", qerr)
                            continue

                        if enc_result.reclaimed_idx is not None:
                            try:
                                cap.queue_buffer(enc_result.reclaimed_idx)
                            except OSError as e:
                                logger.error("Failed to re-queue buffer %d: %s",
                                             enc_result.reclaimed_idx, e)

                        try:
                            server.broadcast(enc_result.data)
                        except Exception as e:
                            logger.error("Broadcast error: %s", e)
                            continue

                finally:
                    cap.close()
            finally:
                enc.close()
        finally:
            for buf in dma_buffers:
                buf.close()
    finally:
        heap.close()


def run(server: Server, capture_device: str, encoder_device: str,
        bitrate: int) -> None:
    """Run the video pipeline with automatic recovery.

    This function runs in a loop, recovering from errors by waiting for
    HDMI signal and restarting the session.

    Args:
        server: Server instance for broadcasting.
        capture_device: Path to capture device.
        encoder_device: Path to encoder device.
        bitrate: Encoder bitrate.
    """
    first_run = True

    while True:
        if not first_run:
            logger.info("Attempting to recover connection...")
            try:
                signal = wait_for_signal(capture_device, 300)
                logger.info("Signal recovered: %dx%d", signal.width, signal.height)
            except (TimeoutError, OSError) as e:
                logger.error("Recovery failed (signal wait): %s", e)
                time.sleep(2)
                continue

        try:
            _run_session(server, capture_device, encoder_device, bitrate, first_run)
        except Exception as e:
            logger.error("Session error: %s", e)
            if first_run:
                raise

        first_run = False
        time.sleep(2)
