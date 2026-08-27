FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install the laptop package and its runtime deps.
COPY apps/laptop/pyproject.toml ./apps/laptop/pyproject.toml
COPY apps/laptop/shruti_array ./apps/laptop/shruti_array
COPY apps/laptop/Makefile ./apps/laptop/Makefile
COPY tools ./tools

# Make the laptop package and tools importable.
ENV PYTHONPATH=/app/apps/laptop:/app

# Install just the runtime deps (no dev) for a small image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libasound2-dev \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --upgrade pip \
    && cd apps/laptop && python -m pip install --no-deps -e . \
    && python -m pip install numpy scipy click rich pyyaml websockets \
    && cd / && chmod +x /app/tools/rebuild/dirty-check.py

# Healthcheck hits the standalone /metrics server when started
# alongside. We don't start the array processor from the image
# directly; that's the operator's job (so they can pass --host
# etc.). We do provide a small entrypoint script.
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8765 8766

ENTRYPOINT ["/entrypoint.sh"]
CMD ["--help"]
