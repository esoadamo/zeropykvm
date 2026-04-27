"""Zero-copy V4L2 video pipeline.

Uses shared DMABUF between capture and encoder for zero-copy operation.
Reference: https://www.kernel.org/doc/html/latest/userspace-api/dma-buf-alloc-exchange.html
"""

import ctypes
import logging
import os
import select
import time

from . import v4l2
from .capture import Capture
from .dma import DmaBuffer, DmaHeap
from .edid import SignalInfo, wait_for_signal
from .encode import Encoder, EncoderConfig
from .server import Server, _contains_nal_type
from .utils import fourcc_to_string, ioctl_raw

logger = logging.getLogger(__name__)

NUM_BUFFERS = 6

# Minimum output frame rate: skip backlogged capture frames to avoid a growing
# delay while still guaranteeing the client receives at least this many frames
# per second when the source is faster than the network can handle.
_MIN_FPS = 20
_MIN_SEND_INTERVAL_NS = 1_000_000_000 // _MIN_FPS  # 50 ms


def _probe_format(device: str, subdev: str) -> dict:
    """Probe the capture device for current format after applying fresh DV timings.

    Args:
        device: Path to the V4L2 capture device.
        subdev: Path to the V4L2 subdevice to query fresh DV timings from.

    Returns:
        Dict with width, height, buffer_size, bytesperline, pixelformat, dv_timings.

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

        # Re-query fresh DV timings from subdev so we always apply current signal info.
        # The signal may have changed resolution since initial detection.
        dv_timings = v4l2.v4l2_dv_timings()
        ctypes.memset(ctypes.byref(dv_timings), 0, ctypes.sizeof(dv_timings))
        fd_sub = os.open(subdev, os.O_RDWR)
        try:
            try:
                ioctl_raw(fd_sub, v4l2.VIDIOC_QUERY_DV_TIMINGS, ctypes.byref(dv_timings))
            except OSError:
                ioctl_raw(fd_sub, v4l2.VIDIOC_SUBDEV_G_DV_TIMINGS, ctypes.byref(dv_timings))
            # On kernel 6.x+ the subdev is read-only; S_DV may fail with EPERM
            try:
                ioctl_raw(fd_sub, v4l2.VIDIOC_S_DV_TIMINGS, ctypes.byref(dv_timings))
            except OSError:
                pass
        finally:
            os.close(fd_sub)
        ioctl_raw(fd, v4l2.VIDIOC_S_DV_TIMINGS, ctypes.byref(dv_timings))

        # Read the format the driver has set — do NOT force a specific pixelformat
        # so the tc358743 CSI-2 bus format is not disrupted.
        fmt = v4l2.v4l2_format()
        ctypes.memset(ctypes.byref(fmt), 0, ctypes.sizeof(fmt))
        fmt.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE
        ioctl_raw(fd, v4l2.VIDIOC_G_FMT, ctypes.byref(fmt))

        width = fmt.fmt.pix.width
        height = fmt.fmt.pix.height
        buffer_size = fmt.fmt.pix.sizeimage
        bytesperline = fmt.fmt.pix.bytesperline
        pixelformat = fmt.fmt.pix.pixelformat

        fmt_str = fourcc_to_string(pixelformat)
        logger.info(
            "Probe: Format %s %dx%d, sizeimage=%d, bytesperline=%d",
            fmt_str, width, height, buffer_size, bytesperline,
        )

        return {
            "width": width,
            "height": height,
            "buffer_size": buffer_size,
            "bytesperline": bytesperline,
            "pixelformat": pixelformat,
            "dv_timings": dv_timings,
        }
    finally:
        os.close(fd)


def _run_session(server: Server, capture_device: str,
                 encoder_device: str, bitrate: int,
                 first_run: bool, signal_info: SignalInfo,
                 subdev: str) -> None:
    """Run a single capture/encode session.

    Args:
        server: Server instance for broadcasting.
        capture_device: Path to capture device.
        encoder_device: Path to encoder device.
        bitrate: Encoder bitrate.
        first_run: Whether this is the first session.
        signal_info: HDMI signal dimensions from DV timings.
        subdev: Path to V4L2 subdevice for fresh DV timings queries.

    Raises:
        Various exceptions on failure.
    """
    logger.info("Starting zero-copy session...")
    logger.info("Capture device: %s", capture_device)
    logger.info("Encoder device: %s, bitrate: %d", encoder_device, bitrate)

    format_info = _probe_format(capture_device, subdev)
    logger.info("Capture format: %dx%d, buffer size: %d bytes",
                format_info["width"], format_info["height"], format_info["buffer_size"])

    # Build a fresh SignalInfo with current DV timings from the probe step
    fresh_signal = SignalInfo(
        width=format_info["width"],
        height=format_info["height"],
        fps=signal_info.fps,
        dv_timings=format_info["dv_timings"],
    )

    # Open DMA Heap
    logger.info("Opening DMA Heap...")
    heap = DmaHeap()
    heap.open()

    try:
        logger.info(
            "Allocating %d shared DMABUF buffers (%d bytes each)...",
            NUM_BUFFERS, format_info["buffer_size"],
        )
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
                input_format=format_info["pixelformat"],
                output_format=v4l2.V4L2_PIX_FMT_H264,
                bitrate=bitrate,
                bytesperline=format_info["bytesperline"],
                sizeimage=format_info["buffer_size"],
            ), dma_buffers)

            try:
                # Initialize capture
                logger.info("Initializing V4L2 capture with shared DMABUF...")
                cap = Capture()
                cap.init(capture_device, dma_buffers, fresh_signal)

                try:
                    logger.info("Zero-copy pipeline ready, starting capture loop...")

                    # Force a keyframe every ~2 seconds so late-joining clients
                    # don't wait long, and also on demand when a client connects.
                    KEYFRAME_INTERVAL = 50
                    frame_counter = 0
                    timeout_count = 0
                    last_sent_ns = 0
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

                        # Skip backlogged frames to maintain minimum output frame rate.
                        # If another frame is already waiting in the capture queue
                        # (we are running behind) and we have sent a frame within
                        # the minimum interval, drop this frame to catch up.
                        now_ns = time.monotonic_ns()
                        more_waiting = bool(select.select([cap.fd], [], [], 0)[0])
                        if more_waiting and (now_ns - last_sent_ns) < _MIN_SEND_INTERVAL_NS:
                            try:
                                cap.queue_buffer(cap_result.index)
                            except OSError as qerr:
                                logger.warning("Failed to re-queue skipped frame: %s", qerr)
                            continue

                        # Force a keyframe periodically or when a client just connected
                        if (frame_counter % KEYFRAME_INTERVAL == 0
                                or server.keyframe_requested.is_set()):
                            enc.force_key_frame()
                            server.keyframe_requested.clear()
                        frame_counter += 1

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

                        last_sent_ns = now_ns

                        # Cache keyframes (containing IDR) for late-joining clients
                        if _contains_nal_type(enc_result.data, 5):  # IDR = 5
                            server.update_keyframe(enc_result.data)

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
        bitrate: int, subdev: str, initial_signal: SignalInfo | None) -> None:
    """Run the video pipeline with automatic recovery.

    This function runs in a loop, recovering from errors by waiting for
    HDMI signal and restarting the session.

    Args:
        server: Server instance for broadcasting.
        capture_device: Path to capture device.
        encoder_device: Path to encoder device.
        bitrate: Encoder bitrate.
        subdev: Path to V4L2 subdevice.
        initial_signal: Signal info from initial HDMI detection.
    """
    first_run = initial_signal is not None
    current_signal = initial_signal

    while True:
        if not first_run:
            logger.info("Attempting to recover connection...")
            try:
                current_signal = wait_for_signal(capture_device, subdev, 300)
                logger.info("Signal recovered: %dx%d", current_signal.width, current_signal.height)
            except (TimeoutError, OSError) as e:
                logger.error("Recovery failed (signal wait): %s", e)
                time.sleep(2)
                continue

        try:
            _run_session(server, capture_device, encoder_device, bitrate, first_run, current_signal, subdev)
        except Exception as e:
            logger.error("Session error: %s", e)
            if first_run and initial_signal is not None:
                raise

        first_run = False
        time.sleep(2)
