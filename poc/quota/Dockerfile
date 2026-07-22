FROM docker.io/library/python:3.13.11-slim@sha256:2b9c9803c6a287cafa0a8c917211dddd23dcd2016f049690ee5219f5d3f1636e

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app
COPY pyproject.toml uv.lock README.md /app/
COPY src /app/src
RUN python -m pip install --no-cache-dir uv==0.11.30 && \
    uv sync --frozen --no-group test

COPY poc/quota /app/poc/quota
CMD ["/bin/sh", "-ec", "set -a; . /runtime/fixture.env; exec gunicorn --bind 0.0.0.0:5000 --workers 1 --worker-class gthread --threads 8 --chdir /app/poc/quota fixture_server:application"]
