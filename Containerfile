# Stage 1: install margot wheel into a venv
FROM python:3.12.13-alpine3.24 AS builder

WORKDIR /build

# Copy the pre-built wheel (produced by `uv build` before `podman build`)
COPY dist/*.whl .

RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir *.whl

# Stage 2: minimal runtime image
FROM python:3.12.13-alpine3.24

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"

# Users mount their project directory here
WORKDIR /workspace

ENTRYPOINT ["margot"]
