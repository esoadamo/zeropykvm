# MyKVM-Python

A KVM-over-IP solution running on Raspberry Pi Zero 2 W — rewritten from [Zig](https://github.com/darkyzhou/mykvm) to Python.

## Features

- **Zero-copy video pipeline**: Uses Linux DMA-BUF to share buffers between capture device (TC358743) and hardware H.264 encoder (bcm2835-codec)
- **USB HID gadget**: Emulates USB keyboard and mouse via Linux ConfigFS, with Boot Protocol support for BIOS compatibility
- **HTTPS + WebSocket**: Serves a web frontend over HTTPS with WebSocket for real-time video streaming and HID control
- **E-Paper display**: Optional status display on Waveshare EPD 2in13 V4
- **EDID management**: Sets custom EDID on the HDMI capture device for resolution control

## Architecture

The Python rewrite mirrors the original Zig project's architecture:

| Module | Description |
|--------|-------------|
| `args.py` | CLI argument parsing (argparse) |
| `utils.py` | Utility functions (ioctl wrapper, IP detection, FourCC) |
| `v4l2.py` | V4L2 constants, ioctl numbers, and ctypes structures |
| `dma.py` | DMA heap allocation and buffer management |
| `edid.py` | EDID setting and HDMI signal detection |
| `capture.py` | V4L2 capture device with DMABUF support |
| `encode.py` | V4L2 M2M H.264 encoder with DMABUF input |
| `usb.py` | USB HID gadget setup, keyboard/mouse emulation |
| `epaper.py` | E-Paper display driver |
| `http_handler.py` | HTTP static file serving |
| `server.py` | WebSocket client management and broadcast |
| `ws_handler.py` | WebSocket message handling (keyboard/mouse events) |
| `https_server.py` | HTTPS/TLS server with WebSocket upgrade |
| `video.py` | Zero-copy video pipeline orchestration |
| `main.py` | Main entry point |

## Requirements

- Python >= 3.9
- Linux with V4L2 support (Raspberry Pi OS recommended)
- TC358743 HDMI capture device
- bcm2835-codec hardware encoder
- USB gadget support (dwc2 overlay)

## Installation

```bash
pip install -e ".[dev]"
```

## Usage

```bash
# Generate self-signed certificates for development
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes

# Run MyKVM
mykvm --cert cert.pem --key key.pem

# With custom settings
mykvm --cert cert.pem --key key.pem --port 443 --bitrate 2000000
```

## Testing

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test module
pytest tests/test_usb.py -v
```

## License

This project follows the same license as the original [mykvm](https://github.com/darkyzhou/mykvm).