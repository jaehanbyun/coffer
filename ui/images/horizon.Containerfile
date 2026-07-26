ARG BASE_IMAGE
FROM ${BASE_IMAGE}

LABEL org.opencontainers.image.title="Coffer Horizon dashboard"
LABEL org.opencontainers.image.version="0.1.0"
LABEL org.opencontainers.image.revision="0a4439556517cf67be0aa949b6551a14e409af75"
LABEL org.opencontainers.image.vendor="Coffer"
LABEL org.opencontainers.image.source="https://github.com/jaehanbyun/coffer"
LABEL io.coffer.ui.contract="coffer-ui-image-v1"
LABEL io.coffer.ui.surface="horizon"

COPY coffer_horizon-0.1.0-py3-none-any.whl /tmp/coffer-horizon.whl
COPY install_horizon.py /tmp/install-coffer-horizon.py

RUN /var/lib/kolla/venv/bin/pip install \
        --no-cache-dir \
        --no-deps \
        /tmp/coffer-horizon.whl \
    && /var/lib/kolla/venv/bin/python /tmp/install-coffer-horizon.py \
    && rm -f /tmp/coffer-horizon.whl /tmp/install-coffer-horizon.py

USER root
