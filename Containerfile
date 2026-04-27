# Containerfile for zeropykvm
#
# Build:  podman compose build
# Push:   podman compose push
# Run:    podman compose up -d

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Create the video group (GID 44 is conventional on Linux) and a dedicated
# application user that belongs to it so the container can access
# /dev/video* devices when the host group GID matches.
RUN groupadd --gid 44 video 2>/dev/null || true && \
    useradd --no-log-init --system --create-home --home-dir /app \
            --gid 44 \
            --uid 1000 pyzerokvm

WORKDIR /app

# Copy source tree
COPY --chown=pyzerokvm:video . .

# Stage the pre-built web frontend into the package data directory so
# that 'uv pip install .' picks it up via the package-data declaration.
RUN mkdir -p zeropykvm/static && \
    cp web/dist.tar zeropykvm/static/dist.tar

# Install the application and its dependencies using uv from the lockfile
# (reproducible, no pip resolver at build time).
RUN uv sync --frozen --no-dev --no-cache

# Put the venv on PATH so ENTRYPOINT can find the zeropykvm script.
ENV PATH="/app/.venv/bin:$PATH"

# Data directory – mount a host volume here to persist certs/config
VOLUME ["/etc/zeropykvm"]

# Default HTTPS port
EXPOSE 8443

ENTRYPOINT ["zeropykvm"]
CMD ["--cert", "/etc/zeropykvm/cert.pem", "--key", "/etc/zeropykvm/key.pem", "--no-epaper"]
