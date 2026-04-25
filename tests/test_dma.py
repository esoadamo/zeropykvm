"""Tests for DMA module."""

from zeropykvm.dma import DmaBuffer, DmaHeap


class TestDmaBuffer:
    """Test DmaBuffer class."""

    def test_init(self):
        buf = DmaBuffer(fd=42, size=1024)
        assert buf.fd == 42
        assert buf.size == 1024

    def test_close(self):
        """Test close sets fd to -1."""
        # We can't actually test closing since we need a real fd
        buf = DmaBuffer(fd=-1, size=1024)
        buf.close()  # Should handle -1 gracefully
        assert buf.fd == -1


class TestDmaHeap:
    """Test DmaHeap class."""

    def test_init(self):
        heap = DmaHeap()
        assert heap.fd == -1

    def test_close_without_open(self):
        """Test closing without opening doesn't crash."""
        heap = DmaHeap()
        heap.close()
        assert heap.fd == -1
