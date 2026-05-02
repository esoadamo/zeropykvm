# zeropykvm

A KVM-over-IP solution running on Raspberry Pi Zero 2 W — rewritten from [Zig](https://github.com/darkyzhou/mykvm) to Python.

> **Attribution:** This project is a Python port of [darkyzhou/mykvm](https://github.com/darkyzhou/mykvm), originally written in Zig. All credit for the architecture and design goes to the original author.

## Features

- **Zero-copy video pipeline**: Uses Linux DMA-BUF to share buffers between capture device (TC358743) and hardware H.264 encoder (bcm2835-codec)
- **USB HID gadget**: Emulates USB keyboard and mouse via Linux ConfigFS, with Boot Protocol support for BIOS compatibility
- **HTTPS + WebSocket**: Serves a web frontend over HTTPS with WebSocket for real-time video streaming and HID control
- **E-Paper display**: Optional status display on Waveshare EPD 2in13 V4
- **HDMI passthrough**: Optionally mirror the captured HDMI input to the RPi's own HDMI output via the Linux framebuffer

## Demo hardware

- [Raspberry Pi Zero 2 W](https://rpishop.cz/raspberry-pi-zero/4311-raspberry-pi-zero-2-w.html) ([Archive](https://web.archive.org/web/20241129185458/https://rpishop.cz/raspberry-pi-zero/4311-raspberry-pi-zero-2-w.html))
- [Waveshare HDMI-CSI Adapter](https://rpishop.cz/mipi/3795-waveshare-hdmi-csi-adapter-pro-raspberry-pi.html) ([Archive](https://web.archive.org/web/20241120194451/https://rpishop.cz/mipi/3795-waveshare-hdmi-csi-adapter-pro-raspberry-pi.html))
- [Raspberry Pi Zero Camera Cable (38 cm)](https://rpishop.cz/mipi/695-raspberry-pi-zero-kamera-kabel-38-cm.html) ([Archive](https://web.archive.org/web/20230528221841/https://rpishop.cz/mipi/695-raspberry-pi-zero-kamera-kabel-38-cm.html))

## Screenshots

![Web UI — Pi Zero 2 W capturing its own HDMI output, viewed in the browser](screenshots/ui.png)

![Hardware — Raspberry Pi Zero 2 W connected to the Waveshare HDMI-CSI adapter via flex cable](screenshots/irl.jpeg)

## Architecture

The Python rewrite mirrors the original Zig project's architecture:

| Module | Description |
|--------|--------------|
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
| `passthrough.py` | HDMI passthrough via Linux framebuffer (`/dev/fb0`) |
| `gencert.py` | Self-signed certificate generator (`zeropykvm gencrt` subcommand) |
| `install_service.py` | Systemd service installer (`zeropykvm install-service` subcommand) |
| `main.py` | Main entry point |

## Requirements

- Python >= 3.12
- Linux with V4L2 support (Raspberry Pi OS recommended)
- TC358743 HDMI capture device
- bcm2835-codec hardware encoder
- USB gadget support (dwc2 overlay)
- [uv](https://docs.astral.sh/uv/) (recommended for dependency management)

## Installation

```bash
# Install from PyPI using uv (recommended)
uv tool install zeropykvm

# Or with pip
pip install zeropykvm

# With e-Paper display support (on Raspberry Pi)
pip install zeropykvm[epaper]
```

### Development setup

```bash
git clone https://github.com/esoadamo/zeropykvm.git
cd zeropykvm
uv sync

# With development tools
uv sync --extra dev

# With e-Paper display support (on Raspberry Pi)
uv sync --extra epaper
```

## Usage

```bash
# Generate a self-signed TLS certificate (no openssl required)
zeropykvm gencrt --cert cert.pem --key key.pem

# Run zeropykvm
zeropykvm --cert cert.pem --key key.pem

# With custom settings
zeropykvm --cert cert.pem --key key.pem --port 443 --bitrate 2000000

# Enable HDMI passthrough (mirror input to the RPi HDMI output)
zeropykvm --cert cert.pem --key key.pem --hdmi-passthrough

# Use an alternate framebuffer device
zeropykvm --cert cert.pem --key key.pem --hdmi-passthrough --hdmi-passthrough-device /dev/fb1
```

Then open `https://<pi-ip>:8443/` in a browser (or whatever port you chose) and accept the self-signed certificate.

### HDMI passthrough

When `--hdmi-passthrough` is given, each captured frame is also written to the Linux framebuffer device (default `/dev/fb0`).
This lets a locally-connected HDMI monitor display the source content in real time while the stream is simultaneously encoded and served over the network.

Supported framebuffer colour depths: **16-bit (RGB565)** and **32-bit (ARGB8888)**.
Supported capture pixel formats: **YUYV**, **UYVY**, and **BGR24** (produced by the TC358743).

> **Performance note:** The pixel format conversion is handled by a dynamically compiled C-extension directly between memory-mapped DMA buffers, achieving absolute zero-copy latency (literally 0 frames of software delay).
> **Requirement:** You MUST have `gcc` installed on the host device for this feature to function properly, as the extension is compiled at runtime to perfectly match the active hardware memory layout.

### Systemd service

`zeropykvm install-service` automates the full setup on a Raspberry Pi OS host:
- creates `/etc/zeropykvm/` (mode `0755`)
- generates a self-signed TLS certificate there if one does not already exist
- writes `/etc/systemd/system/zeropykvm.service` and runs `daemon-reload` → `enable` → `start`

```bash
# Install with defaults (port 8443, data dir /etc/zeropykvm) — runs as root
sudo zeropykvm install-service

# Custom port and data directory
sudo zeropykvm install-service --port 443 --data-dir /opt/zeropykvm

# Install with HDMI passthrough enabled by default
sudo zeropykvm install-service --hdmi-passthrough

# Install without starting the service immediately
sudo zeropykvm install-service --no-start

# Full option list
zeropykvm install-service --help
```

## Testing

```bash
# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run specific test module
uv run pytest tests/test_usb.py -v
```

## License

This project follows the same license as the original [mykvm](https://github.com/darkyzhou/mykvm).