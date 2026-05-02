"""Install zeropykvm as a systemd service.

Usage:
    zeropykvm install-service [--data-dir DIR] [--port PORT]
                              [--no-enable] [--no-start]
"""

import argparse
import os
import subprocess
import sys

DATA_DIR = "/etc/zeropykvm"
SERVICE_NAME = "zeropykvm"
SERVICE_FILE = f"/etc/systemd/system/{SERVICE_NAME}.service"


def _find_executable() -> str:
    """Return the absolute path of the zeropykvm executable.

    Prefers the binary that lives next to the currently-running Python
    interpreter (i.e. the active venv), so that the service unit always uses
    the same installation that ran ``install-service``.
    """
    # First: same venv / bin dir as the current interpreter
    bin_dir = os.path.dirname(sys.executable)
    candidate = os.path.join(bin_dir, "zeropykvm")
    if os.path.exists(candidate):
        return candidate
    # Fall back: $PATH lookup (may point to a different installation)
    import shutil
    path = shutil.which("zeropykvm")
    if path:
        return path
    return "zeropykvm"


def build_service_unit(
    exec_path: str,
    data_dir: str,
    port: int,
    hdmi_passthrough: bool = False,
) -> str:
    """Return the content of the systemd unit file as a string.

    The service always runs as root, which is required to create USB HID
    gadgets through ConfigFS (/sys/kernel/config/usb_gadget/).

    Args:
        exec_path: Absolute path to the zeropykvm executable.
        data_dir: Directory that stores certs and config.
        port: HTTPS port to listen on.
        hdmi_passthrough: Whether to enable HDMI passthrough.

    Returns:
        Systemd unit file content.
    """
    cert_path = os.path.join(data_dir, "cert.pem")
    key_path = os.path.join(data_dir, "key.pem")
    cmd_args = [
        f"ExecStart={exec_path}",
        f" --cert {cert_path}",
        f" --key {key_path}",
        f" --port {port}"
    ]
    if hdmi_passthrough:
        cmd_args.append(" --hdmi-passthrough")
        
    cmd_str = "".join(cmd_args)
    
    return (
        "[Unit]\n"
        f"Description=zeropykvm KVM-over-IP service\n"
        "After=network.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"WorkingDirectory={data_dir}\n"
        f"{cmd_str}\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def install_service(
    data_dir: str = DATA_DIR,
    port: int = 8443,
    enable: bool = True,
    start: bool = True,
    service_file: str = SERVICE_FILE,
    hdmi_passthrough: bool = False,
) -> None:
    """Install and optionally enable/start the zeropykvm systemd service.

    The service always runs as root, which is required for USB HID gadget
    creation through ConfigFS (/sys/kernel/config/usb_gadget/).

    Args:
        data_dir: Directory for certificates and config (will be created).
        port: HTTPS port to listen on.
        enable: Whether to enable the service at boot.
        start: Whether to start the service immediately.
        service_file: Path where the systemd unit file is written.
        hdmi_passthrough: Whether to enable HDMI passthrough in the service.
    """
    # Create data directory
    os.makedirs(data_dir, mode=0o755, exist_ok=True)
    print(f"Data directory: {data_dir}")

    # Generate TLS certificate if not present
    cert_path = os.path.join(data_dir, "cert.pem")
    key_path = os.path.join(data_dir, "key.pem")
    if not os.path.exists(cert_path) or not os.path.exists(key_path):
        print("Generating self-signed TLS certificate...")
        from .gencert import generate_cert
        generate_cert(cert_path=cert_path, key_path=key_path)
    else:
        print(f"TLS certificate already exists: {cert_path}")

    # Restrict access to the private key
    os.chmod(key_path, 0o600)

    # Write systemd unit file
    exec_path = _find_executable()
    unit_content = build_service_unit(
        exec_path=exec_path,
        data_dir=data_dir,
        port=port,
        hdmi_passthrough=hdmi_passthrough,
    )
    with open(service_file, "w") as f:
        f.write(unit_content)
    os.chmod(service_file, 0o644)
    print(f"Systemd unit file written: {service_file}")

    # Reload systemd daemon
    try:
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        print("systemctl daemon-reload: OK")
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"Warning: daemon-reload failed: {exc}", file=sys.stderr)

    # Enable service
    if enable:
        try:
            subprocess.run(
                ["systemctl", "enable", SERVICE_NAME], check=True
            )
            print(f"Service enabled: {SERVICE_NAME}")
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            print(f"Warning: enable failed: {exc}", file=sys.stderr)

    # Start service
    if start:
        try:
            subprocess.run(
                ["systemctl", "start", SERVICE_NAME], check=True
            )
            print(f"Service started: {SERVICE_NAME}")
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            print(f"Warning: start failed: {exc}", file=sys.stderr)

    print("Installation complete.")


def main() -> None:
    """Entry point for the install-service subcommand."""
    parser = argparse.ArgumentParser(
        prog="zeropykvm install-service",
        description=(
            "Install zeropykvm as a systemd service running as root "
            "with data stored in /etc/zeropykvm/"
        ),
    )
    parser.add_argument(
        "--data-dir",
        default=DATA_DIR,
        metavar="<dir>",
        help=f"Directory for certificates and config (default: {DATA_DIR})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8443,
        metavar="<port>",
        help="HTTPS port to listen on (default: 8443)",
    )
    parser.add_argument(
        "--no-enable",
        action="store_true",
        help="Do not enable the service at boot",
    )
    parser.add_argument(
        "--no-start",
        action="store_true",
        help="Do not start the service immediately after installation",
    )
    parser.add_argument(
        "--hdmi-passthrough",
        action="store_true",
        help="Enable zero-latency HDMI passthrough to the local display",
    )

    args = parser.parse_args()

    try:
        install_service(
            data_dir=args.data_dir,
            port=args.port,
            enable=not args.no_enable,
            start=not args.no_start,
            service_file=SERVICE_FILE,
            hdmi_passthrough=args.hdmi_passthrough,
        )
    except PermissionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print("Hint: run as root (e.g. sudo zeropykvm install-service)", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
