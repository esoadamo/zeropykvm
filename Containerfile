# Containerfile (Podmanfile) for zeropykvm
#
# Uses the official zeropykvm image published on Docker Hub by esoadamo.
# Build:  podman build -t zeropykvm .
# Run:    podman run --rm -p 8443:8443 zeropykvm
FROM docker.io/esoadamo/zeropykvm:latest

# Create a dedicated system user that is a member of the video group.
# The container itself runs as root; this user exists for host-side
# systemd service installs that use the same image as a reference.
RUN useradd --system --user-group --groups video --no-create-home pyzerokvm

# Data directory – mount a host volume here to persist certs/config
VOLUME ["/etc/zeropykvm"]

# Default HTTPS port
EXPOSE 8443

ENTRYPOINT ["zeropykvm"]
CMD ["--cert", "/etc/zeropykvm/cert.pem", "--key", "/etc/zeropykvm/key.pem", "--no-epaper"]
