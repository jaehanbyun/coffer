REPO_ROOT := $(abspath $(CURDIR)/../..)
OUTPUT := $(REPO_ROOT)/work/production-promotion/release-readiness.json

.PHONY: check require-qualified verify

check:
	cd "$(REPO_ROOT)" && uv run python \
		poc/production-promotion/readiness.py --output "$(OUTPUT)"

require-qualified:
	cd "$(REPO_ROOT)" && uv run python \
		poc/production-promotion/readiness.py \
		--output "$(OUTPUT)" --require candidate-qualified

verify:
	cd "$(REPO_ROOT)" && uv run pytest -q \
		tests/test_production_promotion_readiness.py
