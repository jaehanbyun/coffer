ARG BASE_IMAGE
FROM ${BASE_IMAGE}

ARG TARGET_KEY
ARG TARGET_LABEL

LABEL io.coffer.ui.python-overlay-trial="${TARGET_LABEL}"

COPY target-wheels/ /tmp/target-wheels/
COPY python_target.py /tmp/python_target.py
COPY python_targets.json /tmp/python_targets.json

RUN /var/lib/kolla/venv/bin/python -m pip install \
        --no-cache-dir \
        --no-deps \
        --no-index \
        --force-reinstall \
        /tmp/target-wheels/*.whl \
    && /var/lib/kolla/venv/bin/python -m pip check \
    && /var/lib/kolla/venv/bin/python /tmp/python_target.py \
        --manifest /tmp/python_targets.json \
        --target "${TARGET_KEY}" \
    && rm -rf \
        /tmp/target-wheels \
        /tmp/python_target.py \
        /tmp/python_targets.json
