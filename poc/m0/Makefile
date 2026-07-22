SHELL := /bin/bash

.PHONY: up verify conformance conformance-full conformance-supported scan-security down reset logs

up:
	docker compose up --detach --wait

verify: up
	./verify.sh

conformance: conformance-full

conformance-full: up
	COFFER_M0_CONFORMANCE_PROFILE=full ./run-conformance.sh

conformance-supported: up
	COFFER_M0_CONFORMANCE_PROFILE=supported ./run-conformance.sh

scan-security:
	./scan-security.sh

logs:
	docker compose logs registry minio

down:
	docker compose down --remove-orphans

reset:
	docker compose down --volumes --remove-orphans
