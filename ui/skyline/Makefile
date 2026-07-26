SOURCE ?= ../../work/skyline-console-2026.1
BUILD_DIR ?= ../../work/skyline-console-coffer

.PHONY: check-source prepare dependencies test-core

check-source:
	python3 apply_overlay.py --source "$(SOURCE)" --check

prepare: check-source
	test ! -e "$(BUILD_DIR)"
	python3 apply_overlay.py --source "$(SOURCE)" --output "$(BUILD_DIR)"

dependencies:
	cd "$(BUILD_DIR)" && yarn install --frozen-lockfile

test-core:
	cd "$(BUILD_DIR)" && yarn test:unit --runInBand \
		src/client/coffer/index.test.js \
		src/resources/coffer/repository.test.js \
		src/stores/coffer/stores.test.js
