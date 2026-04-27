# Containerfile (Podmanfile) for zeropykvm
#
# Uses the official zeropykvm image published on Docker Hub by esoadamo.
# Build:  podman build -t zeropykvm .
# Run:    podman run --rm -p 8443:8443 zeropykvm
FROM docker.io/esoadamo/zeropykvm:latest

# Data directory – mount a host volume here to persist certs/config
VOLUME ["/etc/zeropykvm"]

# Default HTTPS port
EXPOSE 8443

ENTRYPOINT ["zeropykvm"]
CMD ["--cert", "/etc/zeropykvm/cert.pem", "--key", "/etc/zeropykvm/key.pem", "--no-epaper"]
