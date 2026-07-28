REPO_ROOT := $(abspath $(CURDIR)/../../..)
PROMOTION_OUTPUT := $(REPO_ROOT)/work/production-promotion/gc-filesystem-result.json

.PHONY: promotion-evidence verify

promotion-evidence:
	COFFER_GC_RESULT_OUTPUT="$(PROMOTION_OUTPUT)" ./verify.sh

verify:
	./verify.sh
