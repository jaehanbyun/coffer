SOURCE ?= ../../work/skyline-console-2026.1
BUILD_DIR ?= ../../work/skyline-console-coffer
WHEEL_DIR ?= ../../work/skyline-console-coffer-wheel
OVERLAY_VERSION ?= 8.0.0+coffer.1

.PHONY: check-source prepare dependencies locales lint test-core build wheel verify

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
		src/stores/coffer/stores.test.js \
		src/pages/coffer/containers/Repository/QuotaSummary.test.js \
		src/pages/coffer/integration.test.js

locales:
	cd "$(BUILD_DIR)" && yarn i18n

lint:
	cd "$(BUILD_DIR)" && yarn eslint \
		src/client/client/constants.js \
		src/pages/basic/routes/index.js \
		src/layouts/menu.jsx \
		src/client/coffer \
		src/resources/coffer \
		src/stores/coffer \
		src/pages/coffer \
		--quiet --ext .js,.jsx

build: locales lint test-core
	cd "$(BUILD_DIR)" && yarn build

wheel: build
	python3 clean_python_artifacts.py --tree "$(BUILD_DIR)"
	PBR_VERSION="$(OVERLAY_VERSION)" uv build --wheel \
		--out-dir "$(WHEEL_DIR)" "$(BUILD_DIR)"

verify: check-source wheel
	python3 verify_build.py --tree "$(BUILD_DIR)" --wheel-dir "$(WHEEL_DIR)"
