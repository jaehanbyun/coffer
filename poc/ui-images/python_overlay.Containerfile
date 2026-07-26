ARG BASE_IMAGE
FROM ${BASE_IMAGE}

LABEL io.coffer.ui.python-overlay-trial="coffer-ui-mako-1.3.12-v1"

COPY mako-1.3.12-py3-none-any.whl /tmp/mako-1.3.12-py3-none-any.whl

RUN /var/lib/kolla/venv/bin/python -m pip install \
        --no-cache-dir \
        --no-deps \
        --no-index \
        --force-reinstall \
        /tmp/mako-1.3.12-py3-none-any.whl \
    && /var/lib/kolla/venv/bin/python -m pip check \
    && /var/lib/kolla/venv/bin/python -c \
        'from mako.template import Template; assert Template("${value}").render(value="coffer") == "coffer"' \
    && rm -f /tmp/mako-1.3.12-py3-none-any.whl
