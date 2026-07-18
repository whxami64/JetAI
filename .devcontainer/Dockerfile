# Dev container image: Debian-based Python with the uv package manager.
FROM mcr.microsoft.com/devcontainers/python:3.12-bookworm

# Install uv and uvx from the official distroless image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Byte-compile installed packages and copy from the cache for faster,
# reproducible container builds. The project environment lives in the vscode
# user's home so it is writable by the non-root user and stays off the
# bind-mounted workspace (which carries the host's own .venv).
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/home/vscode/.venv
