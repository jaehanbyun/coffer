ROOT := $(abspath ../..)
PYTHON ?= $(ROOT)/.venv/bin/python

.PHONY: verify verify-remote

verify:
	cd "$(ROOT)" && "$(PYTHON)" poc/kolla-ansible-role/verify.py

verify-remote:
	cd "$(ROOT)" && "$(PYTHON)" poc/kolla-ansible-role/verify_remote.py
