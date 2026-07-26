ARG BASE_IMAGE
FROM ${BASE_IMAGE}

LABEL io.coffer.ui.os-cleanup-trial="coffer-ui-os-cleanup-v1"

RUN apt-get -y purge linux-libc-dev \
    && test -z "$(dpkg --audit)" \
    && apt-get -s -o Debug::NoLocking=true check \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
