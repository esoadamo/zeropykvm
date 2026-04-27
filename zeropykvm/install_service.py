"""Install zeropykvm as a systemd service.

Usage:
    zeropykvm install-service [--data-dir DIR] [--user USER] [--port PORT]
                              [--no-enable] [--no-start]
"""

import argparse
import os
import subprocess
import sys

DATA_DIR = "/etc/zeropykvm"
SERVICE_USER = "www-data"
SERVICE_NAME = "zeropykvm"
SERVICE_FILE = f"/etc/systemd/system/{SERVICE_NAME}.service"


def _find_executable() -> str:
    """Return the absolute path of the zeropykvm executable."""
    import shutil
    path = shutil.which("zeropykvm")
    if path:
        return path
    # Fall back to sys.executable's directory
    bin_dir = os.path.dirname(sys.executable)
    candidate = os.path.join(bin_dir, "zeropykvm")
    if os.path.exists(candidate):
        return candidate
    return "zeropykvm"


def build_service_unit(
    exec_path: str,
    data_dir: str,
    user: str,
    port: int,
) -> str:
    """Return the content of the systemd unit file as a string.

    Args:
        exec_path: Absolute path to the zeropykvm executable.
        data_dir: Directory that stores certs and config.
        user: System user to run the service as.
        port: HTTPS port to listen on.

    Returns:
        Systemd unit file content.
    """
    cert_path = os.path.join(data_dir, "cert.pem")
    key_path = os.path.join(data_dir, "key.pem")
    return (
        "[Unit]\n"
        f"Description=zeropykvm KVM-over-IP service\n"
        "After=network.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"User={user}\n"
        f"WorkingDirectory={data_dir}\n"
        f"ExecStart={exec_path}"
        f" --cert {cert_path}"
        f" --key {key_path}"
        f" --port {port}"
        " --no-epaper\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def install_service(
    data_dir: str = DATA_DIR,
    user: str = SERVICE_USER,
    port: int = 8443,
    enable: bool = True,
    start: bool = True,
    service_file: str = SERVICE_FILE,
) -> None:
    """Install and optionally enable/start the zeropykvm systemd service.

    Args:
        data_dir: Directory for certificates and config (will be created).
        user: System user to run the service as.
        port: HTTPS port to listen on.
        enable: Whether to enable the service at boot.
        start: Whether to start the service immediately.
        service_file: Path where the systemd unit file is written.
    """
    # Create data directory
    os.makedirs(data_dir, mode=0o750, exist_ok=True)
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

    # Write systemd unit file
    exec_path = _find_executable()
    unit_content = build_service_unit(
        exec_path=exec_path,
        data_dir=data_dir,
        user=user,
        port=port,
    )
    with open(service_file, "w") as f:
        f.write(unit_content)
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
            "Install zeropykvm as a systemd service running as www-data "
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
        "--user",
        default=SERVICE_USER,
        metavar="<user>",
        help=f"System user to run the service as (default: {SERVICE_USER})",
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

    args = parser.parse_args()

    try:
        install_service(
            data_dir=args.data_dir,
            user=args.user,
            port=args.port,
            enable=not args.no_enable,
            start=not args.no_start,
            service_file=SERVICE_FILE,
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
