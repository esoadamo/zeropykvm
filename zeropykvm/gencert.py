"""Generate a self-signed TLS certificate and private key for zeropykvm.

Usage:
    gencrt --cert cert.pem --key key.pem [--days 3650] [--hostname HOST]
"""

import argparse
import datetime
import ipaddress
import socket
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def _detect_local_ips() -> list[str]:
    """Return the non-loopback local IP address(es) of this machine."""
    addrs: list[str] = []
    try:
        # Connect to an external address to discover the preferred outbound IP
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            addrs.append(s.getsockname()[0])
    except OSError:
        pass
    return addrs


def generate_cert(
    cert_path: str,
    key_path: str,
    days: int = 3650,
    extra_hostnames: list[str] | None = None,
) -> None:
    """Generate an RSA-2048 self-signed certificate with SAN entries.

    Includes ``localhost``, ``127.0.0.1``, and any detected local IPs in the
    Subject Alternative Name extension so browsers accept the certificate
    without extra configuration.
    """
    # Generate private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Build SAN list
    san: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        x509.IPAddress(ipaddress.IPv6Address("::1")),
    ]
    for ip_str in _detect_local_ips():
        try:
            san.append(x509.IPAddress(ipaddress.ip_address(ip_str)))
        except ValueError:
            san.append(x509.DNSName(ip_str))

    for h in (extra_hostnames or []):
        try:
            san.append(x509.IPAddress(ipaddress.ip_address(h)))
        except ValueError:
            san.append(x509.DNSName(h))

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_san: list[x509.GeneralName] = []
    for entry in san:
        key = repr(entry)
        if key not in seen:
            seen.add(key)
            unique_san.append(entry)

    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "zeropykvm"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "zeropykvm"),
    ])

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(unique_san), critical=False)
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None), critical=True
        )
        .sign(private_key, hashes.SHA256())
    )

    # Write private key (PEM, unencrypted)
    with open(key_path, "wb") as f:
        f.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    # Write certificate (PEM)
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    fingerprint = cert.fingerprint(hashes.SHA256()).hex(":")
    _not_after = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after
    expiry = _not_after.strftime("%Y-%m-%d")
    san_strs = []
    for entry in unique_san:
        if isinstance(entry, x509.DNSName):
            san_strs.append(f"DNS:{entry.value}")
        elif isinstance(entry, x509.IPAddress):
            san_strs.append(f"IP:{entry.value}")

    print(f"Certificate written to : {cert_path}")
    print(f"Private key written to : {key_path}")
    print(f"Valid until            : {expiry}")
    print(f"Subject Alt Names      : {', '.join(san_strs)}")
    print(f"SHA-256 fingerprint    : {fingerprint}")


def main() -> None:
    """Entry point for the gencrt command."""
    parser = argparse.ArgumentParser(
        prog="zeropykvm gencrt",
        description="Generate a self-signed TLS certificate for zeropykvm",
    )
    parser.add_argument(
        "-c", "--cert",
        required=True,
        metavar="<path>",
        help="Output path for the certificate (PEM)",
    )
    parser.add_argument(
        "-k", "--key",
        required=True,
        metavar="<path>",
        help="Output path for the private key (PEM)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=3650,
        metavar="<N>",
        help="Certificate validity in days (default: 3650)",
    )
    parser.add_argument(
        "--hostname",
        action="append",
        default=[],
        metavar="<host>",
        help="Extra hostname or IP to include in SAN (may be repeated)",
    )

    args = parser.parse_args()

    try:
        generate_cert(
            cert_path=args.cert,
            key_path=args.key,
            days=args.days,
            extra_hostnames=args.hostname,
        )
    except OSError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
