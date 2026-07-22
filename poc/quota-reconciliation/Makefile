SHELL := /bin/bash

.PHONY: config verify

config:
	podman compose --file compose.yaml --project-name coffer-quota-reconciliation config --quiet

verify:
	./verify.sh
