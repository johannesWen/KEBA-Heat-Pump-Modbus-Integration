# syntax=docker/dockerfile:1
FROM mcr.microsoft.com/devcontainers/python:1-3.13-bookworm

# (Optional) System packages you commonly need
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# (Optional) Keep pip tooling current
RUN python -m pip install --upgrade pip setuptools wheel
