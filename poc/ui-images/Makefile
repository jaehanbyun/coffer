REPO_ROOT := $(abspath $(CURDIR)/../..)

.PHONY: probe-parents qualify trial-os-cleanup trial-python-click \
	trial-python-django trial-python-httplib2 trial-python-overlay \
	trial-python-lxml trial-python-msgpack trial-python-pyjwt trial-python-ujson \
	trial-python-pillow trial-python-urllib3 verify

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

trial-python-click:
	./trial_python_overlay.sh click

trial-python-django:
	./trial_python_overlay.sh django

trial-python-httplib2:
	./trial_python_overlay.sh httplib2

trial-python-lxml:
	./trial_python_overlay.sh lxml

trial-python-msgpack:
	./trial_python_overlay.sh msgpack

trial-python-pillow:
	./trial_python_overlay.sh pillow

trial-python-pyjwt:
	./trial_python_overlay.sh pyjwt

trial-python-ujson:
	./trial_python_overlay.sh ujson

trial-python-urllib3:
	./trial_python_overlay.sh urllib3

qualify:
	./qualify.sh
