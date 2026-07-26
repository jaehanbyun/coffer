REPO_ROOT := $(abspath $(CURDIR)/../..)

.PHONY: probe-parents qualify verify

verify:
	cd "$(REPO_ROOT)" && uv run pytest -q tests/test_ui_image_qualification.py \
		tests/test_ui_image_collectors.py tests/test_ui_parent_remediation.py \
		tests/test_ui_parent_package_probe.py

probe-parents:
	./probe_stock_parents.sh

qualify:
	./qualify.sh
