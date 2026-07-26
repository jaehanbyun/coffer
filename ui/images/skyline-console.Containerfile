ARG BASE_IMAGE
FROM ${BASE_IMAGE}

LABEL org.opencontainers.image.title="Coffer Skyline Console"
LABEL org.opencontainers.image.version="8.0.0+coffer.1"
LABEL org.opencontainers.image.revision="c9000cb1be332a213009793598f17a80ce59671e"
LABEL org.opencontainers.image.vendor="Coffer"
LABEL org.opencontainers.image.source="https://github.com/jaehanbyun/coffer"
LABEL io.coffer.ui.contract="coffer-ui-image-v1"
LABEL io.coffer.ui.surface="skyline"

COPY skyline_console-8.0.0+coffer.1-py3-none-any.whl /tmp/skyline_console-8.0.0+coffer.1-py3-none-any.whl

RUN /var/lib/kolla/venv/bin/pip install \
        --no-cache-dir \
        --no-deps \
        --force-reinstall \
        /tmp/skyline_console-8.0.0+coffer.1-py3-none-any.whl \
    && rm -f /tmp/skyline_console-8.0.0+coffer.1-py3-none-any.whl
