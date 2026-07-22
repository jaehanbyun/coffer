SHELL := /bin/bash

.PHONY: bootstrap-vm deploy-rgw export-distribution-ca export-rgw-ca export-s3-profile info install-ceph provision-s3 rotate-s3-key run-distribution verify-distribution verify-distribution-ha verify-distribution-host verify-gc-dry-run verify-rgw

bootstrap-vm:
	./bootstrap-vm.sh

install-ceph:
	./install-ceph.sh

deploy-rgw:
	./deploy-rgw.sh

export-rgw-ca:
	./export-rgw-ca.sh

verify-rgw: export-rgw-ca
	./verify-rgw.sh

provision-s3:
	./provision-s3.sh

rotate-s3-key:
	./rotate-s3-key.sh

export-s3-profile: provision-s3
	./export-s3-profile.sh

run-distribution: provision-s3
	./run-distribution.sh

export-distribution-ca: run-distribution
	./export-distribution-ca.sh

verify-distribution: run-distribution
	./verify-distribution.sh

verify-distribution-host: export-distribution-ca
	./verify-distribution-host.sh

verify-distribution-ha: run-distribution
	./verify-distribution-ha.sh

verify-gc-dry-run: run-distribution
	./verify-gc-dry-run.sh

info:
	ssh "$${COFFER_RGW_REMOTE:-bb00}" \
		'virsh -c qemu:///system dominfo "$${COFFER_RGW_VM_NAME:-coffer-rgw-poc}"'
