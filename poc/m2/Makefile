SHELL := /bin/bash

.PHONY: verify down logs

verify:
	./verify.sh

logs:
	docker compose logs registry minio

down:
	docker compose down --remove-orphans
