# syntax=docker/dockerfile:1
FROM mcr.microsoft.com/devcontainers/python:3-3.13-bookworm@sha256:f967814892a2783fb9910d77ae30c8254a9c7f4040600613e7fbef33bcb8fec8

# (Optional) System packages you commonly need
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# (Optional) Keep pip tooling current
RUN python -m pip install --upgrade pip setuptools wheel
