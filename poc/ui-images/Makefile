REPO_ROOT := $(abspath $(CURDIR)/../..)

.PHONY: probe-parents qualify trial-os-cleanup trial-python-httplib2 \
	trial-python-overlay verify

verify:
	cd "$(REPO_ROOT)" && uv run pytest -q tests/test_ui_image_qualification.py \
		tests/test_ui_image_collectors.py tests/test_ui_parent_remediation.py \
		tests/test_ui_parent_package_probe.py tests/test_ui_os_cleanup_trial.py \
		tests/test_ui_python_overlay_trial.py

probe-parents:
	./probe_stock_parents.sh

trial-os-cleanup:
	./trial_os_cleanup.sh

trial-python-overlay:
	./trial_python_overlay.sh mako

trial-python-httplib2:
	./trial_python_overlay.sh httplib2

qualify:
	./qualify.sh
