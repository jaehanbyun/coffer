REPO_ROOT := $(abspath $(CURDIR)/../..)
HORIZON_SOURCE ?= $(REPO_ROOT)/work/horizon-25.7.3
PYTHON := $(CURDIR)/.venv/bin/python

.PHONY: sync verify-adapter

sync:
	uv sync --project "$(CURDIR)" --extra test
	uv pip install --python "$(PYTHON)" --no-deps -e "$(HORIZON_SOURCE)"

verify-adapter:
	"$(PYTHON)" "$(CURDIR)/verify.py" --horizon-source "$(HORIZON_SOURCE)"
	"$(PYTHON)" -m pytest -q \
		"$(CURDIR)/cofferdashboard/tests/test_api.py"
	"$(PYTHON)" -m compileall -q "$(CURDIR)/cofferdashboard"
