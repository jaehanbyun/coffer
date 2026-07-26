REPO_ROOT := $(abspath $(CURDIR)/../..)

.PHONY: probe-parents qualify trial-os-cleanup verify

verify:
	cd "$(REPO_ROOT)" && uv run pytest -q tests/test_ui_image_qualification.py \
		tests/test_ui_image_collectors.py tests/test_ui_parent_remediation.py \
		tests/test_ui_parent_package_probe.py tests/test_ui_os_cleanup_trial.py

probe-parents:
	./probe_stock_parents.sh

trial-os-cleanup:
	./trial_os_cleanup.sh

qualify:
	./qualify.sh
