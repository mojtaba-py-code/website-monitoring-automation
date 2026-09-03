# syntax=docker/dockerfile:1
# --- build stage -------------------------------------------------------------
FROM python:3.12-slim AS build

WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

# Install into an isolated prefix we can copy into the runtime image.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --prefix=/install ".[web,pdf]"

# --- runtime stage -----------------------------------------------------------
FROM python:3.12-slim AS runtime

# Unbuffered so log lines reach `docker logs` as they happen rather than in
# blocks; no .pyc files, since the layer is read-only anyway.
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# 'ping' (iputils) is needed for the ICMP probe; curl for the healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends iputils-ping curl \
    && rm -rf /var/lib/apt/lists/*

# Run as a non-root user.
RUN useradd --create-home --uid 10001 webmon
COPY --from=build /install /usr/local

WORKDIR /app
COPY config/config.example.yaml ./config/config.example.yaml

# Persist runtime output to a mountable data dir (passed via --data-dir below).
RUN mkdir -p /data && chown -R webmon:webmon /data /app
USER webmon
VOLUME ["/data"]

EXPOSE 8899
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8899/api/ping || exit 1

# Default: run the dashboard. Override the command for `webmon run`, etc.
# NOTE: binding to 0.0.0.0 requires WEBMON_API_TOKEN to be set in the
# environment -- the server refuses a non-local bind without one.
ENTRYPOINT ["webmon", "--data-dir", "/data"]
CMD ["dashboard", "--host", "0.0.0.0"]
