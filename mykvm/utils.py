"""Common utility functions."""

import ctypes
import ctypes.util
import errno
import fcntl
import logging
import os
import socket
import struct

logger = logging.getLogger(__name__)

# Load libc for ioctl
_libc_path = ctypes.util.find_library("c")
if _libc_path is None:
    raise RuntimeError("Could not find libc; ioctl support is unavailable")
_libc = ctypes.CDLL(_libc_path, use_errno=True)


def ioctl(fd: int, request: int, arg) -> int:
    """Wrapper for ioctl syscall with EINTR retry.

    Args:
        fd: File descriptor
        request: ioctl request number
        arg: Argument (ctypes structure or integer)

    Returns:
        0 on success, raises OSError on failure.
    """
    while True:
        try:
            if isinstance(arg, ctypes.Structure):
                ret = fcntl.ioctl(fd, request, arg)
            elif isinstance(arg, int):
                # For simple integer arguments (e.g., STREAMON/STREAMOFF)
                buf = struct.pack('I', arg)
                fcntl.ioctl(fd, request, buf)
                ret = 0
            elif isinstance(arg, (bytes, bytearray)):
                fcntl.ioctl(fd, request, arg)
                ret = 0
            else:
                ret = fcntl.ioctl(fd, request, arg)
            return ret
        except OSError as e:
            if e.errno == errno.EINTR:
                continue
            raise


def ioctl_raw(fd: int, request: int, arg_ptr) -> int:
    """Raw ioctl using ctypes for cases where fcntl.ioctl doesn't work well.

    Uses the C library ioctl directly with a pointer argument.
    Retries on EINTR.
    """
    while True:
        ret = _libc.ioctl(fd, ctypes.c_ulong(request), arg_ptr)
        if ret == -1:
            err = ctypes.get_errno()
            if err == errno.EINTR:
                continue
            raise OSError(err, os.strerror(err))
        return ret


def get_local_ip() -> str | None:
    """Get local IP address by creating a UDP socket and checking the source address."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Connect to external IP (doesn't actually send anything for UDP)
            sock.connect(("8.8.8.8", 53))
            ip = sock.getsockname()[0]
            return ip
        finally:
            sock.close()
    except OSError:
        return None


def fourcc_to_string(fourcc: int) -> str:
    """Convert V4L2 FourCC format code to string."""
    return (chr(fourcc & 0xFF) + chr((fourcc >> 8) & 0xFF)
            + chr((fourcc >> 16) & 0xFF) + chr((fourcc >> 24) & 0xFF))
