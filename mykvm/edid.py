"""EDID setting and HDMI signal detection for TC358743.

Handles setting EDID data on the capture device and waiting for
HDMI signal using DV timings queries.
"""

import ctypes
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from . import v4l2
from .utils import ioctl_raw

logger = logging.getLogger(__name__)

# EDID data files directory
_EDID_DIR = Path(__file__).parent / "edid_data"


class EdidPreset(Enum):
    """Available EDID presets."""
    P720_60 = "720p60"
    P1080_25 = "1080p25"
    P1080_30 = "1080p30"


@dataclass
class SignalInfo:
    """Video signal information."""
    width: int
    height: int
    fps: int
    dv_timings: v4l2.v4l2_dv_timings = field(default_factory=v4l2.v4l2_dv_timings)


def _load_edid_data(preset: EdidPreset) -> bytes:
    """Load EDID data for the given preset.

    The EDID files are stored as text hex dumps (space-separated hex bytes).
    This function parses them into raw binary bytes.
    """
    filename = {
        EdidPreset.P720_60: "720p60edid",
        EdidPreset.P1080_25: "1080p25edid",
        EdidPreset.P1080_30: "1080p30edid",
    }[preset]
    edid_path = _EDID_DIR / filename
    with open(edid_path, "r", encoding="ascii") as f:
        text = f.read()
    # Parse space/newline-separated hex bytes
    hex_bytes = text.split()
    return bytes(int(b, 16) for b in hex_bytes)


def set_edid(subdev: str, edid_data: bytes) -> None:
    """Set EDID data on the TC358743 subdevice.

    Args:
        subdev: Path to the V4L2 subdevice (e.g. /dev/v4l-subdev0).
        edid_data: Raw EDID data bytes.

    Raises:
        OSError: If setting EDID fails.
    """
    fd = os.open(subdev, os.O_RDWR)
    try:
        # Create a writable buffer for the EDID data
        edid_buffer = (ctypes.c_uint8 * len(edid_data))(*edid_data)

        # Each EDID block is 128 bytes
        blocks = len(edid_data) // 128

        edid_struct = v4l2.v4l2_edid()
        edid_struct.pad = 0
        edid_struct.start_block = 0
        edid_struct.blocks = blocks
        # Cast the array to POINTER(c_uint8) to match the struct field type
        edid_struct.edid = ctypes.cast(
            edid_buffer, ctypes.POINTER(ctypes.c_uint8)
        )

        ioctl_raw(fd, v4l2.VIDIOC_S_EDID, ctypes.byref(edid_struct))
    finally:
        os.close(fd)


def set_edid_with_retry(subdev: str, preset: EdidPreset, max_retries: int = 10) -> None:
    """Set EDID with retry logic.

    Args:
        subdev: Path to the V4L2 subdevice (e.g. /dev/v4l-subdev0).
        preset: EDID preset to use.
        max_retries: Maximum number of retries.
    """
    edid_data = _load_edid_data(preset)
    last_error: OSError | None = None

    for retry in range(max_retries):
        try:
            set_edid(subdev, edid_data)
            logger.info(
                "EDID %s set successfully after %d retries",
                preset.value, retry,
            )
            return
        except OSError as e:
            last_error = e
            if e.errno == 25:  # ENOTTY: subdev is read-only, no point retrying
                logger.warning(
                    "EDID set not supported on this subdevice (read-only): %s", e
                )
                break
            logger.warning(
                "EDID set failed: %s, retry %d/%d",
                e, retry + 1, max_retries,
            )
            time.sleep(2)

    msg = f"Failed to set EDID after {max_retries} retries"
    logger.error(msg)
    raise RuntimeError(msg) from last_error


def _query_and_apply_dv_timings(fd_subdev: int, fd_video: int, apply: bool) -> SignalInfo:
    """Query DV timings from subdevice and optionally apply them to capture device.

    Args:
        fd_subdev: File descriptor of the V4L2 subdevice (tc358743).
        fd_video: File descriptor of the V4L2 capture device (unicam).
        apply: Whether to apply the detected timings to the capture device.

    Returns:
        SignalInfo with detected resolution and frame rate.

    Raises:
        OSError: If query fails (no signal).
    """
    timings = v4l2.v4l2_dv_timings()
    ctypes.memset(ctypes.byref(timings), 0, ctypes.sizeof(timings))

    ioctl_raw(fd_subdev, v4l2.VIDIOC_SUBDEV_G_DV_TIMINGS, ctypes.byref(timings))

    bt = timings.u.bt
    if bt.width == 0 or bt.height == 0:
        raise OSError("No signal detected (zero dimensions)")

    if apply:
        ioctl_raw(fd_video, v4l2.VIDIOC_S_DV_TIMINGS, ctypes.byref(timings))

    # Calculate FPS from pixel clock and total dimensions
    tot_height = (bt.height + bt.vfrontporch + bt.vsync + bt.vbackporch
                  + bt.il_vfrontporch + bt.il_vsync + bt.il_vbackporch)
    tot_width = bt.width + bt.hfrontporch + bt.hsync + bt.hbackporch

    if tot_width > 0 and tot_height > 0:
        fps = bt.pixelclock // (tot_width * tot_height)
    else:
        fps = 0

    return SignalInfo(width=bt.width, height=bt.height, fps=int(fps), dv_timings=timings)


def query_signal(device: str, subdev: str) -> SignalInfo:
    """Check if HDMI signal is present by querying DV timings.

    Args:
        device: Path to the V4L2 capture device.
        subdev: Path to the V4L2 subdevice (tc358743).

    Returns:
        SignalInfo with current signal parameters.

    Raises:
        OSError: If no signal is detected.
    """
    fd_video = os.open(device, os.O_RDWR)
    fd_subdev = os.open(subdev, os.O_RDWR)
    try:
        return _query_and_apply_dv_timings(fd_subdev, fd_video, apply=False)
    finally:
        os.close(fd_video)
        os.close(fd_subdev)


def wait_for_signal(device: str, subdev: str, timeout_seconds: int = 300) -> SignalInfo:
    """Wait for HDMI signal with retry, then apply DV timings.

    Args:
        device: Path to the V4L2 capture device.
        subdev: Path to the V4L2 subdevice (tc358743).
        timeout_seconds: Maximum time to wait in seconds.

    Returns:
        SignalInfo with detected signal parameters.

    Raises:
        TimeoutError: If no signal detected within timeout.
    """
    fd_video = os.open(device, os.O_RDWR)
    fd_subdev = os.open(subdev, os.O_RDWR)
    try:
        elapsed = 0
        retry_interval = 2

        while elapsed < timeout_seconds:
            try:
                # First query without applying
                _query_and_apply_dv_timings(fd_subdev, fd_video, apply=False)
                # If successful, query again and apply
                info = _query_and_apply_dv_timings(fd_subdev, fd_video, apply=True)
                logger.info("DV timings applied")
                time.sleep(0.1)
                return info
            except OSError:
                logger.info("Waiting for HDMI signal... (%d/%ds)", elapsed, timeout_seconds)
                time.sleep(retry_interval)
                elapsed += retry_interval

        raise TimeoutError(f"No HDMI signal detected within {timeout_seconds}s")
    finally:
        os.close(fd_video)
        os.close(fd_subdev)
