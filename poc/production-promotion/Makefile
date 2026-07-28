REPO_ROOT := $(abspath $(CURDIR)/../..)
OUTPUT := $(REPO_ROOT)/work/production-promotion/release-readiness.json
GC_OUTPUT := $(REPO_ROOT)/work/production-promotion/gc-filesystem-result.json
ARTIFACT_OUTPUT := $(REPO_ROOT)/work/production-promotion/artifact-result.json
RGW_KMS_OUTPUT := $(REPO_ROOT)/work/production-promotion/rgw-kms-result.json
RGW_KMS_EVIDENCE := $(REPO_ROOT)/work/production-promotion/rgw-kms-evidence.json
LEDGER_OUTPUT := $(REPO_ROOT)/work/production-promotion/promotion-ledger.json
ARTIFACT_INPUTS := $(REPO_ROOT)/work/production-promotion/artifacts

.PHONY: artifact-result check ledger require-promotion require-qualified rgw-kms-result verify

check:
	cd "$(REPO_ROOT)" && uv run python \
		poc/production-promotion/readiness.py --output "$(OUTPUT)"

require-qualified:
	cd "$(REPO_ROOT)" && uv run python \
		poc/production-promotion/readiness.py \
		--output "$(OUTPUT)" --require candidate-qualified

artifact-result: check
	cd "$(REPO_ROOT)" && uv run python \
		poc/production-promotion/artifacts.py \
		--release-readiness "$(OUTPUT)" \
		--amd64-core-directory "$(ARTIFACT_INPUTS)/amd64/core" \
		--amd64-ui-result "$(ARTIFACT_INPUTS)/amd64/ui-qualification.json" \
		--arm64-core-directory "$(ARTIFACT_INPUTS)/arm64/core" \
		--arm64-ui-result "$(ARTIFACT_INPUTS)/arm64/ui-qualification.json" \
		--output "$(ARTIFACT_OUTPUT)"

rgw-kms-result: check
	cd "$(REPO_ROOT)" && uv run python \
		poc/production-promotion/rgw_kms.py \
		--release-readiness "$(OUTPUT)" \
		--evidence "$(RGW_KMS_EVIDENCE)" \
		--output "$(RGW_KMS_OUTPUT)"

ledger: check
	cd "$(REPO_ROOT)" && set -- \
		--release-readiness "$(OUTPUT)" \
		--output "$(LEDGER_OUTPUT)"; \
	if test -f "$(GC_OUTPUT)"; then \
		set -- "$$@" --gc-result "$(GC_OUTPUT)"; \
	fi; \
	if test -f "$(ARTIFACT_OUTPUT)"; then \
		set -- "$$@" --artifact-result "$(ARTIFACT_OUTPUT)"; \
	fi; \
	if test -f "$(RGW_KMS_OUTPUT)"; then \
		set -- "$$@" --rgw-kms-result "$(RGW_KMS_OUTPUT)"; \
	fi; \
	uv run python poc/production-promotion/ledger.py "$$@"

require-promotion: check
	cd "$(REPO_ROOT)" && set -- \
		--release-readiness "$(OUTPUT)" \
		--output "$(LEDGER_OUTPUT)" \
		--require-qualified; \
	if test -f "$(GC_OUTPUT)"; then \
		set -- "$$@" --gc-result "$(GC_OUTPUT)"; \
	fi; \
	if test -f "$(ARTIFACT_OUTPUT)"; then \
		set -- "$$@" --artifact-result "$(ARTIFACT_OUTPUT)"; \
	fi; \
	if test -f "$(RGW_KMS_OUTPUT)"; then \
		set -- "$$@" --rgw-kms-result "$(RGW_KMS_OUTPUT)"; \
	fi; \
	uv run python poc/production-promotion/ledger.py "$$@"

verify:
	cd "$(REPO_ROOT)" && uv run pytest -q \
		tests/test_production_promotion_readiness.py \
		tests/test_production_promotion_ledger.py \
		tests/test_production_promotion_artifacts.py \
		tests/test_production_promotion_rgw_kms.py \
		tests/test_gc_filesystem_result.py
