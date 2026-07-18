# Dev container image: Debian-based Python with the uv package manager.
FROM mcr.microsoft.com/devcontainers/python:3.12-bookworm

# Install uv and uvx from the official distroless image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Byte-compile installed packages and hard-link from the cache for faster,
# reproducible container builds.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/workspaces/.venv
