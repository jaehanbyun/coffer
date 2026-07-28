REPO_ROOT := $(abspath $(CURDIR)/../..)
OUTPUT := $(REPO_ROOT)/work/production-promotion/release-readiness.json
GC_OUTPUT := $(REPO_ROOT)/work/production-promotion/gc-filesystem-result.json
LEDGER_OUTPUT := $(REPO_ROOT)/work/production-promotion/promotion-ledger.json

.PHONY: check ledger require-promotion require-qualified verify

check:
	cd "$(REPO_ROOT)" && uv run python \
		poc/production-promotion/readiness.py --output "$(OUTPUT)"

require-qualified:
	cd "$(REPO_ROOT)" && uv run python \
		poc/production-promotion/readiness.py \
		--output "$(OUTPUT)" --require candidate-qualified

ledger: check
	cd "$(REPO_ROOT)" && \
	if test -f "$(GC_OUTPUT)"; then \
		uv run python poc/production-promotion/ledger.py \
			--release-readiness "$(OUTPUT)" \
			--gc-result "$(GC_OUTPUT)" \
			--output "$(LEDGER_OUTPUT)"; \
	else \
		uv run python poc/production-promotion/ledger.py \
			--release-readiness "$(OUTPUT)" \
			--output "$(LEDGER_OUTPUT)"; \
	fi

require-promotion: check
	cd "$(REPO_ROOT)" && \
	if test -f "$(GC_OUTPUT)"; then \
		uv run python poc/production-promotion/ledger.py \
			--release-readiness "$(OUTPUT)" \
			--gc-result "$(GC_OUTPUT)" \
			--output "$(LEDGER_OUTPUT)" \
			--require-qualified; \
	else \
		uv run python poc/production-promotion/ledger.py \
			--release-readiness "$(OUTPUT)" \
			--output "$(LEDGER_OUTPUT)" \
			--require-qualified; \
	fi

verify:
	cd "$(REPO_ROOT)" && uv run pytest -q \
		tests/test_production_promotion_readiness.py \
		tests/test_production_promotion_ledger.py \
		tests/test_gc_filesystem_result.py
