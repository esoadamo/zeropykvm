"""DMA Heap allocation and buffer management.

Provides zero-copy buffer sharing between V4L2 capture and encoder devices
using the Linux DMA Heap API.
"""

import ctypes
import logging
import os

from . import v4l2
from .utils import ioctl_raw

logger = logging.getLogger(__name__)

# O_CLOEXEC | O_RDWR
O_CLOEXEC = 0o2000000
O_RDWR = os.O_RDWR


class DmaBuffer:
    """A DMA buffer allocated from a DMA heap."""

    def __init__(self, fd: int, size: int):
        self.fd = fd
        self.size = size

    def sync_start(self, flags: int) -> None:
        """Start DMA buffer sync."""
        sync = v4l2.dma_buf_sync()
        sync.flags = flags | v4l2.DMA_BUF_SYNC_START
        try:
            ioctl_raw(self.fd, v4l2.DMA_BUF_IOCTL_SYNC, ctypes.byref(sync))
        except OSError:
            pass  # Ignore sync errors like the Zig version

    def sync_end(self, flags: int) -> None:
        """End DMA buffer sync."""
        sync = v4l2.dma_buf_sync()
        sync.flags = flags | v4l2.DMA_BUF_SYNC_END
        try:
            ioctl_raw(self.fd, v4l2.DMA_BUF_IOCTL_SYNC, ctypes.byref(sync))
        except OSError:
            pass  # Ignore sync errors like the Zig version

    def close(self) -> None:
        """Close the DMA buffer file descriptor."""
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __del__(self):
        if self.fd >= 0:
            try:
                os.close(self.fd)
            except OSError:
                pass


class DmaHeap:
    """DMA Heap allocator using /dev/dma_heap/linux,cma."""

    HEAP_PATH = "/dev/dma_heap/linux,cma"

    def __init__(self):
        self.fd = -1

    def open(self) -> None:
        """Open the DMA heap device."""
        try:
            self.fd = os.open(self.HEAP_PATH, os.O_RDWR)
        except OSError as e:
            logger.error("Failed to open %s: %s", self.HEAP_PATH, e)
            raise
        logger.info("Opened %s", self.HEAP_PATH)

    def alloc(self, size: int) -> DmaBuffer:
        """Allocate a DMA buffer of the given size.

        Args:
            size: Buffer size in bytes.

        Returns:
            DmaBuffer with the allocated file descriptor.

        Raises:
            OSError: If allocation fails.
        """
        alloc_data = v4l2.dma_heap_allocation_data()
        alloc_data.len = size
        alloc_data.fd = 0
        alloc_data.fd_flags = O_CLOEXEC | O_RDWR
        alloc_data.heap_flags = 0

        try:
            ioctl_raw(self.fd, v4l2.DMA_HEAP_IOCTL_ALLOC, ctypes.byref(alloc_data))
        except OSError as e:
            logger.error("Failed to allocate %d bytes: %s", size, e)
            raise

        return DmaBuffer(fd=alloc_data.fd, size=size)

    def close(self) -> None:
        """Close the DMA heap device."""
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __del__(self):
        if self.fd >= 0:
            try:
                os.close(self.fd)
            except OSError:
                pass
