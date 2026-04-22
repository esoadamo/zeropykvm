"""Command-line argument parsing for MyKVM."""

import argparse
import logging
import os
import sys
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Config:
    """MyKVM configuration from command-line arguments."""
    port: int = 8443
    listen: str = "0.0.0.0"
    device: str = "/dev/video0"
    subdev: str = "/dev/v4l-subdev0"
    encoder: str = "/dev/video11"
    bitrate: int = 1_000_000
    no_epaper: bool = False
    tls_cert_path: str = ""
    tls_key_path: str = ""


def parse(args: list[str] | None = None) -> Config:
    """Parse command-line arguments.

    Args:
        args: List of arguments (defaults to sys.argv[1:])

    Returns:
        Config object with parsed values.

    Raises:
        SystemExit: If required arguments are missing or --help is used.
    """
    parser = argparse.ArgumentParser(
        prog="mykvm",
        description="A KVM-over-IP solution running on Raspberry Pi Zero 2 W",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  mykvm --cert cert.pem --key key.pem
  mykvm --cert cert.pem --key key.pem --port 443
  mykvm --cert cert.pem --key key.pem --listen 0.0.0.0
""",
    )

    parser.add_argument(
        "-c", "--cert",
        required=True,
        metavar="<path>",
        help="TLS certificate path",
    )
    parser.add_argument(
        "-k", "--key",
        required=True,
        metavar="<path>",
        help="TLS private key path",
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=8443,
        metavar="<port>",
        help="HTTPS server port (default: 8443)",
    )
    parser.add_argument(
        "-l", "--listen",
        default="0.0.0.0",
        metavar="<address>",
        help="Listen address (default: 0.0.0.0)",
    )
    parser.add_argument(
        "-d", "--device",
        default="/dev/video0",
        metavar="<path>",
        help="Capture device path (default: /dev/video0)",
    )
    parser.add_argument(
        "-s", "--subdev",
        default="/dev/v4l-subdev0",
        metavar="<path>",
        help="V4L2 subdevice path for EDID/DV timings (default: /dev/v4l-subdev0)",
    )
    parser.add_argument(
        "-e", "--encoder",
        default="/dev/video11",
        metavar="<path>",
        help="Encoder device path (default: /dev/video11)",
    )
    parser.add_argument(
        "-r", "--bitrate",
        type=int,
        default=1_000_000,
        metavar="<bps>",
        help="Encoder bitrate (default: 1000000)",
    )
    parser.add_argument(
        "--no-epaper",
        action="store_true",
        help="Disable e-Paper display",
    )

    parsed = parser.parse_args(args)

    # Resolve cert and key paths to absolute paths
    cert_path = os.path.realpath(parsed.cert)
    key_path = os.path.realpath(parsed.key)

    if not os.path.exists(cert_path):
        logger.error("Certificate file not found: %s", cert_path)
        sys.exit(1)
    if not os.path.exists(key_path):
        logger.error("Key file not found: %s", key_path)
        sys.exit(1)

    return Config(
        port=parsed.port,
        listen=parsed.listen,
        device=parsed.device,
        subdev=parsed.subdev,
        encoder=parsed.encoder,
        bitrate=parsed.bitrate,
        no_epaper=parsed.no_epaper,
        tls_cert_path=cert_path,
        tls_key_path=key_path,
    )
