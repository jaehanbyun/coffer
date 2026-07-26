REPO_ROOT := $(abspath $(CURDIR)/../..)

.PHONY: qualify verify

verify:
	cd "$(REPO_ROOT)" && uv run pytest -q tests/test_ui_image_qualification.py \
		tests/test_ui_image_collectors.py

qualify:
	./qualify.sh
