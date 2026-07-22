SHELL := /bin/bash

.PHONY: bind-rgw bootstrap configure-rgw-kms enable-distribution-kms info provision stop tunnel-check tunnel-start tunnel-stop verify verify-distribution-kms verify-fail-closed

bootstrap:
	./bootstrap.sh

provision: bootstrap
	./provision.sh

bind-rgw: provision
	./bind-rgw.sh

configure-rgw-kms: bind-rgw
	./configure-rgw-kms.sh

enable-distribution-kms: configure-rgw-kms
	./enable-distribution-kms.sh

verify-distribution-kms: enable-distribution-kms
	./verify-distribution-kms.sh

verify-fail-closed: verify-distribution-kms
	./verify-fail-closed.sh

tunnel-start:
	./tunnel.sh start

tunnel-check:
	./tunnel.sh check

tunnel-stop:
	./tunnel.sh stop

verify: provision
	./verify.sh

info:
	limactl list coffer-devstack

stop:
	limactl stop coffer-devstack
