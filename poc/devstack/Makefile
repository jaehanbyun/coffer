SHELL := /bin/bash

.PHONY: bootstrap verify export-ca info start stop

bootstrap:
	./bootstrap.sh

verify:
	./verify.sh

export-ca:
	./export-ca.sh

info:
	limactl list "$${COFFER_DEVSTACK_INSTANCE:-coffer-devstack}"

start:
	limactl start "$${COFFER_DEVSTACK_INSTANCE:-coffer-devstack}"

stop:
	limactl stop "$${COFFER_DEVSTACK_INSTANCE:-coffer-devstack}"
