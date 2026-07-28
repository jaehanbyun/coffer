REPO_ROOT := $(abspath $(CURDIR)/../..)
OUTPUT := $(REPO_ROOT)/work/production-promotion/release-readiness.json
GC_FIXTURE_OUTPUT := $(REPO_ROOT)/work/production-promotion/gc-filesystem-result.json
GC_OUTPUT := $(REPO_ROOT)/work/production-promotion/gc-retention-result.json
ARTIFACT_OUTPUT := $(REPO_ROOT)/work/production-promotion/artifact-result.json
RGW_KMS_OUTPUT := $(REPO_ROOT)/work/production-promotion/rgw-kms-result.json
RGW_KMS_EVIDENCE := $(REPO_ROOT)/work/production-promotion/rgw-kms-evidence.json
MAINTENANCE_OUTPUT := $(REPO_ROOT)/work/production-promotion/maintenance-identity-result.json
MAINTENANCE_EVIDENCE := $(REPO_ROOT)/work/production-promotion/maintenance-identity-evidence.json
DATA_PROTECTION_OUTPUT := $(REPO_ROOT)/work/production-promotion/data-protection-result.json
DATA_PROTECTION_EVIDENCE := $(REPO_ROOT)/work/production-promotion/data-protection-evidence.json
OBSERVABILITY_OUTPUT := $(REPO_ROOT)/work/production-promotion/observability-result.json
OBSERVABILITY_EVIDENCE := $(REPO_ROOT)/work/production-promotion/observability-evidence.json
LOAD_SOAK_OUTPUT := $(REPO_ROOT)/work/production-promotion/load-soak-result.json
LOAD_SOAK_EVIDENCE := $(REPO_ROOT)/work/production-promotion/load-soak-evidence.json
KOLLA_MULTINODE_OUTPUT := $(REPO_ROOT)/work/production-promotion/kolla-multinode-result.json
KOLLA_MULTINODE_EVIDENCE := $(REPO_ROOT)/work/production-promotion/kolla-multinode-evidence.json
OPERATOR_RELEASE_OUTPUT := $(REPO_ROOT)/work/production-promotion/operator-release-result.json
OPERATOR_RELEASE_EVIDENCE := $(REPO_ROOT)/work/production-promotion/operator-release-evidence.json
LEDGER_OUTPUT := $(REPO_ROOT)/work/production-promotion/promotion-ledger.json
MIGRATION_V2_OUTPUT := $(REPO_ROOT)/work/production-promotion/migration-v2.json
PROVIDER_INPUTS_V2_OUTPUT := $(REPO_ROOT)/work/production-promotion/provider-inputs-v2.json
LEDGER_V2_OUTPUT := $(REPO_ROOT)/work/production-promotion/promotion-ledger-v2.json
MIGRATION_V2_CHECKPOINT ?=
MIGRATION_V2_CHECKPOINT_POLICY ?=
CEPH_INPUT_V2 ?=
DISTRIBUTION_INPUT_V2 ?=
OSLO_MESSAGING_INPUT_V2 ?=
REGISTRY_CORE_SCOPE_V2 ?=
STORAGE_BACKEND_SCOPE_V2 ?=
RGW_BARBICAN_KMS_SCOPE_V2 ?=
HORIZON_SCOPE_V2 ?=
SKYLINE_SCOPE_V2 ?=
REFERRERS_SCOPE_V2 ?=
ARTIFACT_INPUTS := $(REPO_ROOT)/work/production-promotion/artifacts

.PHONY: artifact-result check data-protection-result gc-retention-result kolla-multinode-result ledger ledger-v2 load-soak-result maintenance-identity-result migration-v2 observability-result operator-release-result provider-inputs-v2 require-promotion require-qualified rgw-kms-result verify

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

maintenance-identity-result: check
	cd "$(REPO_ROOT)" && uv run python \
		poc/production-promotion/maintenance_identity.py \
		--release-readiness "$(OUTPUT)" \
		--artifact-result "$(ARTIFACT_OUTPUT)" \
		--rgw-kms-result "$(RGW_KMS_OUTPUT)" \
		--evidence "$(MAINTENANCE_EVIDENCE)" \
		--output "$(MAINTENANCE_OUTPUT)"

data-protection-result: check
	cd "$(REPO_ROOT)" && uv run python \
		poc/production-promotion/data_protection.py \
		--release-readiness "$(OUTPUT)" \
		--artifact-result "$(ARTIFACT_OUTPUT)" \
		--rgw-kms-result "$(RGW_KMS_OUTPUT)" \
		--maintenance-identity-result "$(MAINTENANCE_OUTPUT)" \
		--evidence "$(DATA_PROTECTION_EVIDENCE)" \
		--output "$(DATA_PROTECTION_OUTPUT)"

observability-result: check
	cd "$(REPO_ROOT)" && uv run python \
		poc/production-promotion/observability.py \
		--release-readiness "$(OUTPUT)" \
		--artifact-result "$(ARTIFACT_OUTPUT)" \
		--rgw-kms-result "$(RGW_KMS_OUTPUT)" \
		--maintenance-identity-result "$(MAINTENANCE_OUTPUT)" \
		--data-protection-result "$(DATA_PROTECTION_OUTPUT)" \
		--evidence "$(OBSERVABILITY_EVIDENCE)" \
		--output "$(OBSERVABILITY_OUTPUT)"

gc-retention-result: check
	cd "$(REPO_ROOT)" && uv run python \
		poc/production-promotion/gc_retention.py \
		--release-readiness "$(OUTPUT)" \
		--artifact-result "$(ARTIFACT_OUTPUT)" \
		--gc-result "$(GC_FIXTURE_OUTPUT)" \
		--output "$(GC_OUTPUT)"

load-soak-result: check
	cd "$(REPO_ROOT)" && uv run python \
		poc/production-promotion/load_soak.py \
		--release-readiness "$(OUTPUT)" \
		--artifact-result "$(ARTIFACT_OUTPUT)" \
		--rgw-kms-result "$(RGW_KMS_OUTPUT)" \
		--maintenance-identity-result "$(MAINTENANCE_OUTPUT)" \
		--data-protection-result "$(DATA_PROTECTION_OUTPUT)" \
		--observability-result "$(OBSERVABILITY_OUTPUT)" \
		--gc-retention-result "$(GC_OUTPUT)" \
		--evidence "$(LOAD_SOAK_EVIDENCE)" \
		--output "$(LOAD_SOAK_OUTPUT)"

kolla-multinode-result: check
	cd "$(REPO_ROOT)" && uv run python \
		poc/production-promotion/kolla_multinode.py \
		--release-readiness "$(OUTPUT)" \
		--artifact-result "$(ARTIFACT_OUTPUT)" \
		--rgw-kms-result "$(RGW_KMS_OUTPUT)" \
		--maintenance-identity-result "$(MAINTENANCE_OUTPUT)" \
		--data-protection-result "$(DATA_PROTECTION_OUTPUT)" \
		--observability-result "$(OBSERVABILITY_OUTPUT)" \
		--gc-retention-result "$(GC_OUTPUT)" \
		--load-soak-result "$(LOAD_SOAK_OUTPUT)" \
		--evidence "$(KOLLA_MULTINODE_EVIDENCE)" \
		--output "$(KOLLA_MULTINODE_OUTPUT)"

operator-release-result: check
	cd "$(REPO_ROOT)" && uv run python \
		poc/production-promotion/operator_release.py \
		--release-readiness "$(OUTPUT)" \
		--artifact-result "$(ARTIFACT_OUTPUT)" \
		--rgw-kms-result "$(RGW_KMS_OUTPUT)" \
		--maintenance-identity-result "$(MAINTENANCE_OUTPUT)" \
		--data-protection-result "$(DATA_PROTECTION_OUTPUT)" \
		--observability-result "$(OBSERVABILITY_OUTPUT)" \
		--gc-retention-result "$(GC_OUTPUT)" \
		--load-soak-result "$(LOAD_SOAK_OUTPUT)" \
		--kolla-multinode-result "$(KOLLA_MULTINODE_OUTPUT)" \
		--evidence "$(OPERATOR_RELEASE_EVIDENCE)" \
		--output "$(OPERATOR_RELEASE_OUTPUT)"

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
	if test -f "$(MAINTENANCE_OUTPUT)"; then \
		set -- "$$@" --maintenance-identity-result "$(MAINTENANCE_OUTPUT)"; \
	fi; \
	if test -f "$(DATA_PROTECTION_OUTPUT)"; then \
		set -- "$$@" --data-protection-result "$(DATA_PROTECTION_OUTPUT)"; \
	fi; \
	if test -f "$(OBSERVABILITY_OUTPUT)"; then \
		set -- "$$@" --observability-result "$(OBSERVABILITY_OUTPUT)"; \
	fi; \
	if test -f "$(LOAD_SOAK_OUTPUT)"; then \
		set -- "$$@" --load-soak-result "$(LOAD_SOAK_OUTPUT)"; \
	fi; \
	if test -f "$(KOLLA_MULTINODE_OUTPUT)"; then \
		set -- "$$@" --kolla-multinode-result "$(KOLLA_MULTINODE_OUTPUT)"; \
	fi; \
	if test -f "$(OPERATOR_RELEASE_OUTPUT)"; then \
		set -- "$$@" --operator-release-result "$(OPERATOR_RELEASE_OUTPUT)"; \
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
	if test -f "$(MAINTENANCE_OUTPUT)"; then \
		set -- "$$@" --maintenance-identity-result "$(MAINTENANCE_OUTPUT)"; \
	fi; \
	if test -f "$(DATA_PROTECTION_OUTPUT)"; then \
		set -- "$$@" --data-protection-result "$(DATA_PROTECTION_OUTPUT)"; \
	fi; \
	if test -f "$(OBSERVABILITY_OUTPUT)"; then \
		set -- "$$@" --observability-result "$(OBSERVABILITY_OUTPUT)"; \
	fi; \
	if test -f "$(LOAD_SOAK_OUTPUT)"; then \
		set -- "$$@" --load-soak-result "$(LOAD_SOAK_OUTPUT)"; \
	fi; \
	if test -f "$(KOLLA_MULTINODE_OUTPUT)"; then \
		set -- "$$@" --kolla-multinode-result "$(KOLLA_MULTINODE_OUTPUT)"; \
	fi; \
	if test -f "$(OPERATOR_RELEASE_OUTPUT)"; then \
		set -- "$$@" --operator-release-result "$(OPERATOR_RELEASE_OUTPUT)"; \
	fi; \
	uv run python poc/production-promotion/ledger.py "$$@"

migration-v2:
	cd "$(REPO_ROOT)" && uv run python \
		poc/production-promotion/migration.py \
		--v1-ledger "$(LEDGER_OUTPUT)" \
		--release-readiness "$(OUTPUT)" \
		$(if $(strip $(MIGRATION_V2_CHECKPOINT)),--checkpoint "$(MIGRATION_V2_CHECKPOINT)") \
		$(if $(strip $(MIGRATION_V2_CHECKPOINT_POLICY)),--checkpoint-policy "$(MIGRATION_V2_CHECKPOINT_POLICY)") \
		--output "$(MIGRATION_V2_OUTPUT)"

provider-inputs-v2:
	cd "$(REPO_ROOT)" && uv run python \
		poc/production-promotion/provider_inputs.py \
		--migration "$(MIGRATION_V2_OUTPUT)" \
		$(if $(strip $(CEPH_INPUT_V2)),--ceph-input "$(CEPH_INPUT_V2)") \
		$(if $(strip $(DISTRIBUTION_INPUT_V2)),--distribution-input "$(DISTRIBUTION_INPUT_V2)") \
		$(if $(strip $(OSLO_MESSAGING_INPUT_V2)),--oslo-messaging-input "$(OSLO_MESSAGING_INPUT_V2)") \
		--output "$(PROVIDER_INPUTS_V2_OUTPUT)"

ledger-v2:
	cd "$(REPO_ROOT)" && uv run python \
		poc/production-promotion/ledger_v2.py \
		--provider-inputs "$(PROVIDER_INPUTS_V2_OUTPUT)" \
		$(if $(strip $(REGISTRY_CORE_SCOPE_V2)),--registry-core "$(REGISTRY_CORE_SCOPE_V2)") \
		$(if $(strip $(STORAGE_BACKEND_SCOPE_V2)),--storage-backend "$(STORAGE_BACKEND_SCOPE_V2)") \
		$(if $(strip $(RGW_BARBICAN_KMS_SCOPE_V2)),--rgw-barbican-kms "$(RGW_BARBICAN_KMS_SCOPE_V2)") \
		$(if $(strip $(HORIZON_SCOPE_V2)),--horizon "$(HORIZON_SCOPE_V2)") \
		$(if $(strip $(SKYLINE_SCOPE_V2)),--skyline "$(SKYLINE_SCOPE_V2)") \
		$(if $(strip $(REFERRERS_SCOPE_V2)),--referrers "$(REFERRERS_SCOPE_V2)") \
		--output "$(LEDGER_V2_OUTPUT)"

verify:
	cd "$(REPO_ROOT)" && uv run pytest -q \
		tests/test_production_promotion_readiness.py \
		tests/test_production_promotion_ledger.py \
		tests/test_production_promotion_artifacts.py \
		tests/test_production_promotion_rgw_kms.py \
		tests/test_production_promotion_maintenance_identity.py \
		tests/test_production_promotion_data_protection.py \
		tests/test_production_promotion_observability.py \
		tests/test_production_promotion_gc_retention.py \
		tests/test_production_promotion_load_soak.py \
		tests/test_production_promotion_kolla_multinode.py \
		tests/test_production_promotion_operator_release.py \
		tests/test_production_promotion_trust_policy.py \
		tests/test_production_promotion_input_lineage.py \
		tests/test_production_promotion_scope_evidence.py \
		tests/test_production_promotion_migration.py \
		tests/test_production_promotion_provider_inputs.py \
		tests/test_production_promotion_ledger_v2.py \
		tests/test_production_promotion_rollback.py \
		tests/test_gc_filesystem_result.py
