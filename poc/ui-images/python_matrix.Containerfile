ARG BASE_IMAGE
FROM ${BASE_IMAGE}

ARG MATRIX_KEY
ARG MATRIX_LABEL
ARG MATRIX_SURFACE

LABEL io.coffer.ui.python-matrix-trial="${MATRIX_LABEL}"

COPY target-wheels/ /tmp/target-wheels/
COPY python_matrix.py /tmp/python_matrix.py
COPY python_matrices.json /tmp/python_matrices.json
COPY python_target.py /tmp/python_target.py
COPY python_targets.json /tmp/python_targets.json

RUN /var/lib/kolla/venv/bin/python -m pip install \
        --no-compile \
        --no-deps \
        --no-index \
        --force-reinstall \
        /tmp/target-wheels/*.whl \
    && /var/lib/kolla/venv/bin/python -m pip check \
    && /var/lib/kolla/venv/bin/python /tmp/python_matrix.py \
        --manifest /tmp/python_matrices.json \
        --target-manifest /tmp/python_targets.json \
        --matrix "${MATRIX_KEY}" \
        --surface "${MATRIX_SURFACE}" \
        --probe-mode candidate \
    && rm -rf \
        /tmp/target-wheels \
        /tmp/python_matrix.py \
        /tmp/python_matrices.json \
        /tmp/python_target.py \
        /tmp/python_targets.json
