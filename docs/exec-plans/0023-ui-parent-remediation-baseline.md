---
title: "UI parent vulnerability remediation baseline"
status: active
updated: 2026-07-27
owner: primary-agent
---

# Objective

Turn the inherited Critical/High findings in the accepted native ARM64 Horizon
and Skyline Console parent images into a deterministic, non-waiving
remediation baseline. Bind every inherited finding to both scanner evidence,
the exact OpenStack requirements revision and upper-constraints payload used by
Kolla, then test only narrowly justified package cleanup or constraint changes
against the real dashboard build/runtime contracts. Keep production promotion
fail closed until both scanners and both architectures meet the existing
absolute gate.

## Done Criteria

- [x] A fixture-tested classifier refuses incomplete or divergent
      parent/custom evidence and records every inherited Critical/High package
      without treating a zero Coffer delta as qualification.
- [x] The result binds the exact Kolla/OpenStack requirements revision,
      archived upper-constraints member and SHA-256, qualification evidence
      SHA-256, architecture, scanner findings, installed versions, fixed-version
      signals, and constraint matches.
- [x] The accepted ARM64 evidence produces an owner-only deterministic report
      separating constraint-bound Python candidates, upstream-unfixed
      findings, and OS-package findings without a waiver or arbitrary private
      constraint override.
- [ ] A bounded experiment evaluates whether final-image OS build dependency
      cleanup and the smallest compatible Python fix candidates preserve the
      Horizon/Skyline package, runtime, and UI test contracts.
- [ ] Any remediation image is rescanned by both accepted scanners and remains
      blocked unless its absolute Critical/High count is zero; scanner
      replacement, reachability-only suppression, or undocumented VEX is
      refused.
- [ ] Focused and repository regression, documentation, secret, and diff gates
      pass; verified atomic milestones are committed and pushed.

## Non-goals

- Waiving, suppressing, or hiding inherited findings because Coffer introduced
  none.
- Forking OpenStack global constraints or removing Kolla runtime packages
  without build, runtime, and compatibility evidence.
- Handling Docker credentials, publishing/signing images, creating a live
  OpenStack cloud, or bypassing plans 0019 and 0022.
- Claiming that a package is unreachable or build-only from its name alone.

## Context and Evidence

- Plan 0021's native ARM64 result is valid and blocked: Horizon parent/custom
  have Trivy 1 Critical/83 High and Scout 0 Critical/75 High; Skyline
  parent/custom have Trivy 1 Critical/68 High and Scout 0 Critical/60 High.
  Both scanners report zero introduced and zero missing Coffer findings.
- Plan 0022 proved the same native AMD64 build/runtime path but cannot produce
  canonical Scout CVE evidence without an unauthorized Docker login. That
  external credential boundary remains separate.
- The accepted Kolla build archive contains the OpenStack requirements
  `stable/2026.1` upper constraints. Read-only inspection binds current
  revision `06cd4e8523cbade25fb93efc4f8ea77d6d97064f` and shows the vulnerable
  Horizon Python versions match those exact constraints.
- Examples with scanner-advertised fixes include Django 4.2.28, cryptography
  43.0.3, pyOpenSSL 24.2.1, PyJWT 2.11.0, ujson 5.11.0, Pillow 12.1.1, lxml
  6.0.2, Mako 1.3.10, urllib3 2.6.3, msgpack 1.1.2, and httplib2 0.31.2.
  This is candidate evidence, not permission to override global constraints.
- The OS finding set includes `linux-libc-dev`/kernel-family packages with no
  scanner fixed version. Kolla's final `openstack-base` includes build
  dependencies, but removal safety must be proven from package dependency and
  runtime evidence rather than assumed.

## Decisions

| Decision | Reason | Alternatives rejected | Date |
|---|---|---|---|
| Preserve the existing two-scanner absolute gate | A zero Coffer delta proves inheritance, not production safety | Delta-only qualification; Trivy-only replacement; CVE waiver | 2026-07-26 |
| Bind classification to the actual archived upper-constraints payload and official requirements revision | Package remediation is meaningful only against the exact Kolla build input | Copying a hand-selected vulnerable package list; mutable latest constraints | 2026-07-26 |
| Treat fixed-version data as an experiment candidate, not an accepted upgrade | OpenStack global constraints encode cross-project compatibility and cannot be privately reversed without tests | Blind latest-version upgrade; broad constraints fork | 2026-07-26 |
| Refuse build-only or reachability claims without direct evidence | Package names and scanner classes do not prove runtime irrelevance | Automatic `linux-libc-dev` removal; undocumented VEX | 2026-07-26 |
| Accept the exact 18-package purge only as a reusable experimental mechanism | Native ARM64 package, runtime, lineage, rollback-parent, and two-scanner evidence passed with no introduced Critical/High finding | Editing production Containerfiles immediately; treating a lower count as production qualification | 2026-07-26 |
| Accept Mako 1.3.12 only as the first narrow Python compatibility derivative | The exact official wheel, dependency/runtime/source hashes, OS/Python delta, and both scanners passed on Horizon and Skyline | Broad private constraints fork; combining unrelated upgrades; promoting while High findings remain | 2026-07-26 |
| Use one strict checked-in target manifest for all single-package overlay trials | One validated data contract preserves exact wheel identity and fail-closed delta checks without copying target-specific code | Free-form shell inputs; one script per package; runtime code from the manifest | 2026-07-27 |
| Accept httplib2 0.32.0 only as the second independent compatibility derivative | Both surfaces preserved OS and non-target Python state while both scanners removed exactly CVE-2026-59939 | Combining it with Mako or other upgrades; changing production images before the matrix is complete | 2026-07-27 |
| Accept urllib3 2.7.0 only as the third independent compatibility derivative | The official non-yanked wheel, no-network HTTPS pool probe, exact runtime delta, and both scanners passed on both surfaces | Treating an HTTP stack import alone as compatibility; combining accepted derivatives; immediate production adoption | 2026-07-27 |
| Accept PyJWT 2.13.0 only as the fourth independent compatibility derivative | The official non-yanked wheel, offline HS256 round trip, exact runtime delta, and both scanners passed on both surfaces | Treating an import alone as token compatibility; combining accepted derivatives; changing the production image | 2026-07-27 |
| Bind every target to its actual installed UI surfaces | Django exists in Horizon but not Skyline; an implicit two-surface trial would add an unrelated package and fabricate a Skyline remediation | Installing every target into both images; accepting missing baseline findings; free-form runtime surface inputs | 2026-07-27 |
| Accept Django 4.2.30 only as the Horizon-scoped fifth compatibility derivative | The official non-yanked wheel, offline framework setup/template probe, exact runtime delta, and both scanners passed on its one installed surface | Installing Django in Skyline; treating an import alone as framework compatibility; changing the production image | 2026-07-27 |
| Model expected findings per scanner while preserving their nonempty union | Click is reported by Scout but not Trivy; exact scanner-local sets preserve fail-closed delta checks without fabricating a Trivy finding | Requiring a fabricated common set; accepting arbitrary removals; dropping either scanner; waiving a finding | 2026-07-27 |
| Accept Click 8.3.3 only as the sixth independent compatibility derivative | Official wheel identity, offline CLI invocation, exact runtime delta, unchanged Trivy set, and exact Scout-only CVE removal passed on both surfaces | Fabricating a Trivy finding; combining upgrades; changing production images while High findings remain | 2026-07-27 |
| Admit only canonical CVE and GHSA finding namespaces | Trivy and Scout both identify the msgpack issue by GHSA; GitHub documents a strict lowercase alphabet and 4-4-4 shape | Converting GHSA to a nonexistent CVE; accepting free-form scanner IDs; waiving GHSA-only findings | 2026-07-27 |

## Tasks

- [x] Implement and fixture-test the inherited-finding/constraints classifier.
- [x] Generate and independently reproduce the ARM64 remediation baseline.
- [x] Run the bounded post-Coffer OS cleanup experiment.
- [x] Run the smallest Python constraint compatibility experiment.
- [x] Generalize the single-package target contract without weakening its
      wheel, runtime, lineage, or scanner gates.
- [x] Run the independent httplib2 0.31.2 to 0.32.0 experiment.
- [x] Run the independent urllib3 2.6.3 to 2.7.0 experiment.
- [x] Run the independent PyJWT 2.11.0 to 2.13.0 experiment.
- [x] Make target surface eligibility explicit and fail closed throughout the
      runner, collector, evidence, and classifier.
- [x] Run the Horizon-only Django 4.2.28 to 4.2.30 experiment.
- [x] Make scanner-specific expected finding identities explicit without
      weakening exact delta, introduced-finding, secret, or absolute gates.
- [x] Run the independent Click 8.3.1 to 8.3.3 experiment.
- [x] Extend the strict finding identifier grammar to canonical CVE and GHSA
      values with positive and rejection fixtures.
- [ ] Rescan viable derivatives, update the durable handoff, and publish each
      verified atomic milestone.

## Progress Log

### 2026-07-26 — Work package activated

- Completed: Rechecked the live Stage 6 upstream classifier; Distribution
  v3.1.1 remains the latest stable accepted line and Ceph v20.2.2 still
  predates the merged Tentacle zero-byte SSE-KMS fix. Inspected the accepted
  ARM64 UI evidence and actual Kolla `openstack-base` source archive.
- Evidence: Parent/custom finding counts and sets remain equal. The installed
  vulnerable Python versions match the exact `stable/2026.1` upper constraints
  at requirements revision
  `06cd4e8523cbade25fb93efc4f8ea77d6d97064f`.
- Changed files: This plan and `.codex/state/HANDOFF.md`.
- Next exact action: Add `poc/ui-images/remediation.py` with strict fixture
  tests in `tests/test_ui_parent_remediation.py`; consume the Kolla source
  archive directly rather than copying a mutable constraints subset.

### 2026-07-26 — Deterministic inherited-finding baseline completed

- Completed: Added a dependency-free classifier that refuses linked/missing
  evidence, invalid schemas and revisions, divergent parent/custom finding
  sets, qualification count mismatches, ambiguous constraints members,
  conflicting constraints, and non-atomic output replacement. No finding is
  suppressed and the result is never a production candidate.
- Accepted result: The owner-only ARM64 report exits `3` and reproduces at
  SHA-256
  `9ecde6e3b6e2d484bd27fa05cf6c1b26e81077a3e3154a64ebf4902863fa0941`.
  It binds qualification SHA-256
  `883a8af9ae1bd9419caccd027943fbeb6352f5a4316608009e1fa4b0de2cb564`
  and exact constraints SHA-256
  `04a324d166aa983f79341fe0584e0dc0b1b81377403dc85e47605c43d58db167`.
- Classification: Horizon has 16 package/version groups, including 12
  constraint-bound all-fixed candidates, one constraint-bound no-fix group,
  two OS no-fix groups, and one unbound all-fixed group. Skyline has 14 groups
  split 10/1/2/1 respectively. `linux`/`linux-libc-dev` remain OS no-fix;
  `oslo.messaging` remains constraint-bound without a fixed version.
- Safety boundary: The candidate lists are test inputs only.
  `waivers_applied`, `private_constraint_override_accepted`,
  `os_cleanup_accepted`, and `production_candidate` are all false.
- Changed files: Classifier, five focused fixtures, Make target, UI image
  README, this plan, and the handoff. Canonical raw/report evidence stays
  owner-only under ignored `work/`.
- Next exact action: Add a bounded dependency/removal probe for the stock
  Horizon and Skyline parent filesystem before modifying an image or
  constraints.

### 2026-07-26 — Stock-parent OS dependency boundary completed

- Completed: Added a fixed-target package probe and bounded Kolla stock-parent
  runner. It builds exact ARM64 Horizon/Skyline parents from the accepted
  Ubuntu digest and Kolla revision, then executes only read-only/no-network/
  no-capability/no-new-privileges `dpkg`, `apt-mark`, and `apt-get -s`
  inspection. Exact probe images and build contexts are removed and a
  previously stopped Podman machine is restored to stopped.
- Evidence: Horizon and Skyline probe payloads are byte-identical at SHA-256
  `75dfaac579e19bece668f480cbffc1212b08e1496dc8533d489d31b7256d783a`.
  The owner-only summary is mode 0640 at SHA-256
  `e0b95fe54f4d083fc5507847b0e7ed31fa61ec99e3af138446fe62039f21e0bc`.
- Package boundary: `linux-libc-dev` 6.8.0-136.136 is automatic, not manual.
  It owns 1,015 paths: 1,007 headers, zero shared-object paths, and zero
  executable paths. Its installed direct reverse dependency is automatic
  `libc6-dev` 2.39-0ubuntu8.7.
- Purge boundary: The exact simulation removes 18 packages, including
  `linux-libc-dev`, `libc6-dev`, `build-essential`, the C++ toolchain, Python
  development headers, and XML/XSLT/zlib development packages. Both package
  database checks pass, but the report keeps `safe_to_apply=false`; inventory
  and simulation do not prove runtime, rebuild, upgrade, or rollback safety.
- Diagnosed failures: The first probe rejected Ubuntu's normal
  `/etc/os-release` link to `/usr/lib/os-release`; the fixed-path system link is
  now accepted. The second probe parsed apt `Remv` but not purge-mode `Purg`;
  both exact action records are now accepted. A lightweight disposable Ubuntu
  digest fixture reproduced and verified each correction before the final
  stock-parent run. Failed owner-only probe directories were moved to the
  user's Trash and can be recovered; no raw invalid result entered Git.
- Cleanup: Final probe images and generated contexts are absent; the retained
  Podman machine is stopped. Owner-only non-secret evidence remains under
  ignored `work/ui-parent-remediation-probe/evidence/`.
- Changed files: Package probe, bounded runner, seven focused fixtures, Make
  target, README, this plan, and the handoff.
- Next exact action: Build a disposable post-Coffer derivative that applies
  only the exact 18-package apt purge transaction, then require clean package
  DB, Horizon/Skyline import and runtime checks, image metadata preservation,
  rollback parent availability, and two-scanner comparison before accepting or
  rejecting the cleanup.

### 2026-07-26 — Post-Coffer OS cleanup trial accepted

- Completed: Added an inventory-only package collector, fixed experimental
  cleanup Containerfile, owner-only provenance/package/runtime evidence
  collector, fail-closed classifier, bounded native runner, and focused
  fixtures. Production Horizon and Skyline Containerfiles remain unchanged.
- Exact transaction: Native ARM64 derivatives removed exactly the 18 packages
  from the accepted stock-parent simulation. No package was added or changed;
  both resulting package databases are clean. Kolla user/entrypoint/command,
  exact pre-cleanup layer prefix, Coffer labels, wheel-installed runtime file
  hashes, and build-input absence all pass.
- Scan result: Horizon Trivy Critical/High changed from 1/83 to 0/31 and Scout
  from 0/75 to 0/34. Skyline changed from Trivy 1/68 to 0/16 and Scout 0/60 to
  0/19. Trivy removed 53 Critical/High identities per surface and Scout
  removed 41; neither scanner introduced one and Trivy found zero secrets.
- Decision: `os_cleanup_trial_accepted=true`, but status remains `blocked` and
  `production_candidate=false`. No waiver or private constraint override was
  accepted. The remaining Python findings and constraint-bound
  `oslo.messaging` no-fix finding keep the absolute gate closed.
- Evidence: Owner-only ignored result SHA-256
  `a8da7856f955f25866a0b9fbe9214d34863a502714a1624ac2ae66ce6caac2d3`;
  manifest `6a55442007af74444f441ac4d07938330a957d71078c57c010d6bd81a39de7e8`,
  images `d717fdd62330d36a3c56d14ec5b2921b30e5347a2273f42b6fe2bbef28c33c99`,
  inventories `cce5364a6a2202ae822b8510cb0b4339afef1133d3f8f0affacb75e28cf721db`,
  and runtime `e659ef7fd56227632b5252c9650ea2e7df074216a3e944b1feb9389fa9671e01`.
- Cleanup: All exact trial images, generated contexts, wheel copies, image
  archives, and scanner caches are absent. The retained Podman machine is
  stopped. Non-secret evidence remains owner-only under ignored
  `work/ui-os-cleanup-trial/evidence/`.
- Next exact action: Add a fixture-first constraint-overlay classifier and
  disposable derivative for the smallest coherent Python candidate set. Begin
  with independently upgradable pure-Python candidates; require dependency
  resolution, `pip check`, Horizon/Skyline build/runtime tests, exact package
  delta, rollback-parent preservation, and the same two-scanner absolute gate.

### 2026-07-26 — Mako 1.3.12 compatibility derivative accepted

- Completed: Added a fixed official-wheel derivative, exact OS/Python/UI
  runtime collectors, provenance manifest, fail-closed classifier, bounded
  native runner, and six focused fixtures. The overlay uses `--no-index`,
  `--no-deps`, and `--force-reinstall`; production UI Containerfiles remain
  unchanged.
- Compatibility: Both native ARM64 surfaces retain the exact accepted
  post-cleanup OS inventory. Installed Python distribution version
  multisets are unchanged except Mako 1.3.10 to 1.3.12. `pip check`, a Mako
  render, target source hashes, generated-bytecode boundaries, Coffer UI
  runtime hashes, image metadata, and input absence pass.
- Scan result: Horizon Trivy High changed 31 to 29 and Scout 34 to 32;
  Skyline Trivy High changed 16 to 14 and Scout 19 to 17. Both scanners
  removed exactly `CVE-2026-41205` and `CVE-2026-44307`, introduced zero
  Critical/High finding, and Trivy found zero secrets.
- Decision: `python_overlay_trial_accepted=true`, status `blocked`, and
  `production_candidate=false`. No waiver, production Containerfile change,
  or private constraints override was accepted. Other nonzero Python High
  findings, the unfixed `oslo.messaging` group, native AMD64 evidence, and
  Stage 6 release gates remain independent blockers.
- Evidence: Owner-only ignored result SHA-256
  `ca4e5aab6fdd37105aa9107f441a29734d7e9f29ef011c338e151418eda3338a`;
  manifest `7dbf87db361684ae397251ad64c63035629c021d520e7b91b0cc9199af67352e`,
  images `47366b2a9366cf779d31fb55698717a2c9d6a9d01a9d90594482e6810cea272c`,
  OS inventories
  `8e7fe70bc16543c09475f69c7c66557e97d991cac7b716a8491092e05d6677af`,
  and runtimes
  `ade4ceea2e9aa29246bb8fa2be8ad409db475f47232094f337a7c1fc62e76b3e`.
- Diagnosed failures: The first collector emitted only a generic error. The
  corrected retry identified Kolla's expected duplicate development/install
  metadata, which is now preserved as a sorted version multiset. The final
  classifier initially rejected generated `__pycache__` records; it now
  requires every official wheel source hash exactly and permits only matching
  package-local `.pyc` extras. Failed owner-only directories were moved to the
  user's Trash; no invalid raw result entered Git.
- Cleanup: Exact trial images, contexts, wheel copies, archives, and scanner
  caches are absent. The retained Podman machine is stopped. Non-secret
  evidence remains owner-only under ignored
  `work/ui-python-overlay-trial-mako/evidence/`.
- Next exact action: Generalize the one-package overlay manifest without
  changing its fail-closed contracts, then test the independent pure-Python
  `httplib2` 0.31.2 to 0.32.0 candidate alone.

### 2026-07-27 — Generic target contract and httplib2 derivative accepted

- Completed: Replaced Mako-specific target constants with the strict
  `coffer.ui-python-overlay-targets/v1` manifest, bounded loader, generic
  collector/classifier, one fixed overlay Containerfile, and one runner.
  Target selection remains a checked-in allowlist; manifest values cannot
  execute code. The original wheel filename is preserved for pip parsing and
  its exact final-image absence is verified.
- Compatibility: Both native ARM64 surfaces preserve the accepted cleanup OS
  inventory and every non-target Python distribution version multiset.
  `httplib2` alone changes from 0.31.2 to 0.32.0. `pip check`, module import,
  official wheel source hashes, package-local generated bytecode boundaries,
  Coffer UI runtime hashes, image lineage, and build-input absence pass.
- Scan result: Horizon Trivy High changed 31 to 30 and Scout 34 to 33;
  Skyline Trivy High changed 16 to 15 and Scout 19 to 18. Both scanners
  removed exactly `CVE-2026-59939`, introduced zero Critical/High finding,
  and Trivy found zero secrets.
- Decision: `python_overlay_trial_accepted=true`, status `blocked`, and
  `production_candidate=false`. The accepted result is specific to
  `httplib2==0.32.0`; no production Containerfile, private constraints
  override, waiver, credential, or live cloud changed.
- Evidence: Owner-only ignored result SHA-256
  `b0f06afebc37f75610652fc6ba8855b1a52cdc91d946d27e2fb177d7b8dcd0a2`;
  manifest `33edfea6bb087efed8582ad9e49ffbf8916adcc630346ff039b771a1a2c85e7e`,
  images `0ea4e1f91a46b4fd9ca960fdf7b07b24be7cfe653d77888e342f18ed6f223728`,
  OS inventories
  `8e7fe70bc16543c09475f69c7c66557e97d991cac7b716a8491092e05d6677af`,
  and runtimes
  `0f89fc503ba683ad79953c33209068cedeac3852ba85c3afe50de42e7530c68a`.
- Diagnosed failure: The first generic build copied the wheel to the
  non-standard name `coffer-target.whl`, which pip correctly rejected before
  installation. The retry preserves the strict manifest filename in `/tmp`
  and proves its removal. The failed ignored work directory is retained under
  `work/ui-python-overlay-trial-httplib2-failed-wheel-filename/`.
- Cleanup: Exact trial images, generated contexts, wheel copies, archives, and
  scanner caches are absent. The harness-started Podman machine is stopped.
  Non-secret evidence remains owner-only under ignored
  `work/ui-python-overlay-trial-httplib2/evidence/`.
- Next exact action: Add only the official `urllib3` 2.7.0 target after binding
  its PyPI wheel metadata and exact `CVE-2026-44431`/`CVE-2026-44432`
  expectations, then run the same independent ARM64 two-scanner matrix.

### 2026-07-27 — urllib3 2.7.0 derivative accepted

- Completed: Bound the official non-yanked PyPI wheel, SHA-256, Python 3.10+
  metadata, optional dependency markers, and exact expected CVEs. Added a
  bounded `urllib3-pool` probe that constructs and clears an HTTPS pool without
  opening a network connection.
- Compatibility: Both native ARM64 surfaces preserve the accepted cleanup OS
  inventory and all non-target Python distribution version multisets.
  `urllib3` alone changes from 2.6.3 to 2.7.0. `pip check`, HTTPS pool
  construction, official source hashes, package-local bytecode boundaries,
  Coffer UI runtime hashes, image lineage, and build-input absence pass.
- Scan result: Horizon Trivy High changed 31 to 29 and Scout 34 to 32;
  Skyline Trivy High changed 16 to 14 and Scout 19 to 17. Both scanners
  removed exactly `CVE-2026-44431` and `CVE-2026-44432`, introduced zero
  Critical/High finding, and Trivy found zero secrets.
- Decision: `python_overlay_trial_accepted=true`, status `blocked`, and
  `production_candidate=false`. The accepted result is specific to
  `urllib3==2.7.0`; it is not cumulative with Mako or httplib2 and changes no
  production Containerfile or constraints policy.
- Evidence: Owner-only ignored result SHA-256
  `c8c4d6c441c9ce7c6b03d567c84a398bff16a80ff50a6cc40f8f00480bd0311e`;
  manifest `1dbb12e3ca36c760e272e25c09750635bc2bf8a5711825fe2d47f8c653ab48eb`,
  images `7f3a5bae36e6ec234d9920e50baa491bfd1eb90a6a1b7259a36b9d97bd52c22f`,
  OS inventories
  `8e7fe70bc16543c09475f69c7c66557e97d991cac7b716a8491092e05d6677af`,
  and runtimes
  `e789429c0bc60bf921856f7783e7d3422dd58ff21779caa8615f5bfa45879172`.
- Cleanup: Exact trial images, generated contexts, wheel copies, archives, and
  scanner caches are absent. The harness-started Podman machine is stopped.
  Non-secret evidence remains owner-only under ignored
  `work/ui-python-overlay-trial-urllib3/evidence/`.
- Next exact action: Bind only the official pure-Python PyJWT 2.13.0 wheel and
  exact `CVE-2026-32597`/`CVE-2026-48526` expectations, add an offline
  encode/decode probe, and run that target alone.

### 2026-07-27 — PyJWT 2.13.0 derivative accepted

- Completed: Bound the official non-yanked PyPI wheel, SHA-256, Python 3.9+
  metadata, optional dependency markers, and exact expected CVEs. Added a
  bounded `pyjwt-hs256` probe that performs an offline encode/decode round trip
  with fixture-only key material.
- Compatibility: Both native ARM64 surfaces preserve the accepted cleanup OS
  inventory and all non-target Python distribution version multisets. PyJWT
  alone changes from 2.11.0 to 2.13.0. `pip check`, HS256 round trip, official
  source hashes, package-local bytecode boundaries, Coffer UI runtime hashes,
  image lineage, and build-input absence pass.
- Scan result: Horizon Trivy High changed 31 to 29 and Scout 34 to 32;
  Skyline Trivy High changed 16 to 14 and Scout 19 to 17. Both scanners
  removed exactly `CVE-2026-32597` and `CVE-2026-48526`, introduced zero
  Critical/High finding, and Trivy found zero secrets.
- Decision: `python_overlay_trial_accepted=true`, status `blocked`, and
  `production_candidate=false`. The accepted result is specific to
  `PyJWT==2.13.0`; it is not cumulative with another derivative and changes no
  production Containerfile or constraints policy.
- Evidence: Owner-only ignored result SHA-256
  `dd51d44d5fb049aa88362a8ce7579de24f7ffee85fc812f373259f85fabf9b7b`;
  manifest `f928fc3ea0ab3458cbe624e9a6dcaa4efd28ffc71fd913ee4ad2e532845020c8`,
  images `928a689da4958dec954c599b39c4842720f25f0b68651c2f69c07da66c1356a2`,
  OS inventories
  `8e7fe70bc16543c09475f69c7c66557e97d991cac7b716a8491092e05d6677af`,
  and runtimes
  `891429b12920e1a027a8ebebb4539d30d15821d9633599b7e254b281e9be246f`.
- Cleanup: Exact trial images, generated contexts, wheel copies, archives, and
  scanner caches are absent. The harness-started Podman machine is stopped.
  Non-secret evidence remains owner-only under ignored
  `work/ui-python-overlay-trial-pyjwt/evidence/`.
- Next exact action: Inspect only the official Django 4.2.30 release metadata
  and current runtime consumers before deciding whether its three-finding
  derivative can enter the same bounded compatibility matrix.

### 2026-07-27 — surface-scoped target contract accepted

- Completed: Verified from the accepted runtime and scanner evidence that
  Django 4.2.28 is installed and reported only in Horizon. Added a sorted,
  nonempty, allow-listed `surfaces` field to every target and carried it
  through image selection, collection, exact evidence identities, baseline
  validation, runtime checks, and two-scanner classification.
- Safety: The runner builds the target overlay and scans only the declared
  target surfaces. Stock parent preparation may still build both baselines.
  The collector rejects missing selected image arguments and any unexpected
  unselected image argument. The classifier requires its image, runtime, UI,
  and scanner sets to match the target surfaces exactly.
- Scope: Existing Mako, httplib2, urllib3, and PyJWT targets remain explicitly
  two-surface. No package version, production Containerfile, constraints
  policy, scanner result, or existing acceptance decision changed.
- Next exact action: Add Django 4.2.30 as a Horizon-only target with the
  official wheel identity, exact three High CVEs, and an offline framework
  setup/template probe, then run that one surface alone.

### 2026-07-27 — Django 4.2.30 Horizon derivative accepted

- Completed: Bound the official non-yanked PyPI wheel, SHA-256, Python 3.8+
  metadata, six dependency markers, one installed surface, and exact expected
  High CVEs. Added a bounded offline probe that configures Django, calls
  `django.setup()`, and renders one template.
- Compatibility: The native ARM64 Horizon derivative preserves the accepted
  cleanup OS inventory and all non-target Python distribution version
  multisets. Django alone changes from 4.2.28 to 4.2.30. `pip check`, framework
  setup/template rendering, official source hashes, package-local bytecode
  boundaries, Coffer Horizon runtime hashes, image lineage, and build-input
  absence pass.
- Scan result: Horizon Trivy High changed 31 to 28 and Scout 34 to 31. Both
  scanners removed exactly `CVE-2026-25673`, `CVE-2026-33034`, and
  `CVE-2026-3902`, introduced zero Critical/High finding, and Trivy found zero
  secrets. Skyline contains no Django and has no overlay or scan evidence.
- Decision: `python_overlay_trial_accepted=true`, status `blocked`, and
  `production_candidate=false`. The accepted result is specific to
  Horizon `Django==4.2.30`; it is not cumulative with another derivative and
  changes no production Containerfile or constraints policy.
- Evidence: Owner-only ignored result SHA-256
  `5d9026d31e8aeb4c0433fb7c41ffb8d7edd74d2eb94521b1c0421a4d314bb6e5`;
  manifest `e79e594e5a6a5219af4622dba2f3e125a5ae18d67e450f074c9a698c51f0d51f`,
  images `8a80d5eb09eb65536ed44491364015d5ebaafdc72d11caa934936a62867d1bf9`,
  OS inventories
  `1c37ea201d13a9e2fc5c4b4d606268f3d4239c20017e8fbc0b507e44e243b4cb`,
  and runtimes
  `f1d9856e344550b0b8711357cc2e2e5d95f7078fdfdeaa06ff3041cb28412571`.
- Cleanup: Exact trial images, generated contexts, wheel copies, archives, and
  scanner caches are absent. The harness-started Podman machine is stopped,
  and no Skyline scanner result was emitted. Non-secret evidence remains
  owner-only under ignored `work/ui-python-overlay-trial-django/evidence/`.
- Next exact action: Generalize expected target finding identities by scanner
  without weakening introduced-finding or absolute-count gates, then admit
  pure-Python Click 8.3.3 only if the Scout-only baseline is explicit.

### 2026-07-27 — scanner-specific finding contract accepted

- Completed: Upgraded the checked-in target manifest to
  `coffer.ui-python-overlay-targets/v2`. Every target now carries exact
  `trivy` and `scout` finding sets. Empty scanner-local sets are permitted only
  when the sorted union is nonempty and exactly matches the accepted
  remediation candidate.
- Safety: The evidence manifest and result schemas are v2 and retain both the
  union and scanner-keyed identities. Each scanner must remove exactly its own
  declared set, may introduce no Critical/High finding, and remains subject to
  the Trivy secret and absolute remaining-count gates. Unknown/missing
  scanners, invalid/duplicate/unsorted CVEs, an empty union, and an unexpected
  removal are rejected by fixtures.
- Scope: Existing five derivatives retain identical two-scanner finding
  expectations and acceptance decisions. No wheel, package version,
  production Containerfile, scanner result, constraints policy, credential,
  or live deployment changed.
- Next exact action: Bind the official Click 8.3.3 release identity and its
  Scout-only `CVE-2026-7246` expectation, add a bounded offline CLI invocation
  probe, and run that target alone on both native ARM64 UI surfaces.

### 2026-07-27 — Click 8.3.3 derivative accepted

- Completed: Bound the official non-yanked PyPI wheel, SHA-256, Python 3.10+
  metadata, Windows-only optional dependency marker, both installed surfaces,
  and Scout-only expected CVE. Added an offline `click-cli` probe that invokes
  a real command through `CliRunner`.
- Compatibility: Both native ARM64 derivatives preserve the accepted cleanup
  OS inventory and every non-target Python distribution version multiset.
  Click alone changes from 8.3.1 to 8.3.3. `pip check`, CLI invocation,
  official source hashes, package-local bytecode boundaries, Coffer UI runtime
  hashes, image lineage, and build-input absence pass.
- Scan result: Trivy remains unchanged at Horizon 31 and Skyline 16 High.
  Scout removes exactly `CVE-2026-7246`, changing Horizon 34 to 33 and Skyline
  19 to 18 High. Both scanners introduce zero Critical/High finding, and Trivy
  finds zero secrets.
- Decision: `python_overlay_trial_accepted=true`, status `blocked`, and
  `production_candidate=false`. The accepted result is specific to
  `click==8.3.3`; it is not cumulative with another derivative and changes no
  production Containerfile or constraints policy.
- Evidence: Owner-only ignored result SHA-256
  `d81fab9acf6234c9f7d87eb06ec150530565abf63bbe95e5a2c9473b78661dbe`;
  manifest `0384d9663f58accfad57dca3c87fb66a66a67d64086f583707a12321b4a7aa07`,
  images `fac06b79e4561486c5c63b835b01536f960af5c8997cf0846479db9d33f365a6`,
  OS inventories
  `8e7fe70bc16543c09475f69c7c66557e97d991cac7b716a8491092e05d6677af`,
  and runtimes
  `06962bc8d4a127d4da6fe5aeb0bf667251bf4d6c5ac6eae9277f29c3156c3d05`.
- Cleanup: Exact trial images, generated contexts, wheel copies, archives, and
  scanner caches are absent. The harness-started Podman machine is stopped.
  Non-secret evidence remains owner-only under ignored
  `work/ui-python-overlay-trial-click/evidence/`.
- Next exact action: Extend the strict finding identifier grammar to accept
  canonical `GHSA-xxxx-xxxx-xxxx` identities, preserve the same scanner-local
  and remediation-union gates, then evaluate msgpack 1.2.1 independently.

### 2026-07-27 — canonical GHSA finding contract accepted

- Completed: Extended the finding grammar from CVE-only to the union of
  canonical CVE and GitHub-documented lowercase
  `GHSA(-[23456789cfghjmpqrvwx]{4}){3}` identifiers. The scanner-keyed target,
  evidence, exact-delta, and remediation-union contracts are unchanged.
- Safety: A full two-surface fixture proves the same GHSA can be removed
  exactly by both scanners. Uppercase GHSA values, disallowed alphabet
  characters, truncated groups, free-form names, missing scanner entries,
  unsorted/duplicate lists, and an empty union fail closed.
- Scope: No existing target, finding set, package version, wheel, scanner
  result, production Containerfile, constraints policy, credential, or live
  deployment changed.
- Next exact action: Bind the official msgpack 1.2.1 native ARM64 wheel and
  exact `GHSA-6v7p-g79w-8964` expectation, add an offline binary
  pack/unpack/streaming probe, and run that target alone on both UI surfaces.

## Verification

| Check | Command or method | Result |
|---|---|---|
| Stage 6 upstream release gate | `make -C poc/production-images check-upstream` | blocked as expected |
| ARM64 parent evidence inventory | accepted ignored evidence plus `jq` | inspected; exact parent/custom counts retained |
| Kolla constraints binding | archived `openstack-base` source plus official requirements revision | inspected; exact vulnerable versions match |
| Classifier fixtures | focused pytest | passed; 28 UI classifier/qualification/collector tests |
| Accepted evidence classification | deterministic repeat and SHA-256 comparison | passed; exit 3, mode 0640, stable SHA-256 `9ecde6e...` |
| Stock-parent package probe | bounded native ARM64 build and read-only inspection | passed; identical surfaces, exact cleanup, summary `e0b95fe...` |
| Package-probe milestone gates | 35 focused tests, ShellCheck, Ruff E/F/I, compilation, full pytest | passed; 1,490 tests |
| OS cleanup compatibility experiment | native ARM64 image/package/runtime/two-scanner trial | passed as a reusable mechanism; production blocked at Horizon Trivy/Scout 31/34 High and Skyline 16/19 High |
| OS cleanup milestone gates | strict ShellCheck, Ruff E/F/I, compilation, 41 focused tests, full pytest | passed; 1,496 tests |
| Python constraints compatibility experiment | native ARM64 exact Mako wheel, OS/Python/UI runtime and two-scanner trial | passed for Mako only; production blocked at Horizon Trivy/Scout 29/32 High and Skyline 14/17 High |
| Mako milestone gates | Bash syntax, strict ShellCheck, Ruff E/F/I, compilation, UI image suite, full pytest, lock and diff checks | passed; 52 focused and 1,502 total tests |
| Generic target and httplib2 experiment | native ARM64 exact wheel, OS/Python/UI runtime and two-scanner trial | passed for httplib2 only; production blocked at Horizon Trivy/Scout 30/33 High and Skyline 15/18 High |
| httplib2 milestone gates | Bash syntax, strict ShellCheck, Ruff, compilation, UI image suite, full pytest, lock, secret, and diff checks | passed; 48 focused and 1,503 total tests with no staged leak |
| urllib3 compatibility experiment | native ARM64 official wheel, OS/Python/UI runtime, HTTPS pool, and two-scanner trial | passed for urllib3 only; production blocked at Horizon Trivy/Scout 29/32 High and Skyline 14/17 High |
| urllib3 milestone gates | JSON, Bash, strict ShellCheck, Ruff, compilation, UI image suite, full pytest, lock, secret, and diff checks | passed; 49 focused and 1,504 total tests with no staged leak |
| PyJWT compatibility experiment | native ARM64 official wheel, OS/Python/UI runtime, offline HS256 round trip, and two-scanner trial | passed for PyJWT only; production blocked at Horizon Trivy/Scout 29/32 High and Skyline 14/17 High |
| PyJWT milestone gates | JSON, Bash, strict ShellCheck, Ruff, compilation, UI image suite, full pytest, lock, secret, and diff checks | passed; 50 focused and 1,505 total tests with no staged leak |
| Surface-scoped target contract | strict target manifest, dynamic runner/collector/classifier, two-surface and Horizon-only fixtures | passed; 51 focused and 1,506 total tests |
| Django compatibility experiment | native ARM64 Horizon official wheel, OS/Python/UI runtime, framework setup/template probe, and two-scanner trial | passed for Horizon Django only; production blocked at Trivy/Scout 28/31 High |
| Django milestone gates | JSON, Bash, strict ShellCheck, Ruff, compilation, UI image suite, full pytest, lock, secret, and diff checks | passed; 52 focused and 1,507 total tests with no staged leak |
| Scanner-specific finding contract | strict v2 target/evidence schemas, equal and empty scanner-local sets, malformed contract and unexpected-delta fixtures | passed; 58 focused and 1,513 total tests |
| Click compatibility experiment | native ARM64 official wheel, exact OS/Python/UI runtime, offline CLI invocation, and scanner-specific two-scanner trial | passed for Click only; production blocked at Horizon Trivy/Scout 31/33 High and Skyline 16/18 High |
| Click milestone gates | JSON, Bash, strict ShellCheck, Ruff, compilation, UI image suite, full pytest, lock, secret, and diff checks | passed; 59 focused and 1,514 total tests |
| Canonical GHSA contract | documented grammar, positive two-surface GHSA delta, malformed/uppercase/alphabet/truncation rejection fixtures | passed; 63 focused and 1,518 total tests |
| Baseline milestone gates | full pytest, Ruff E/F/I, compilation, staged secret/diff | passed; 1,483 tests and no staged leak |
| Final repository gates | dashboard packages, Kolla role, docs/links, secret, diff | pending with remediation experiment |

## Failures, Blockers, and Risks

- Distribution and Ceph stable-release gates still block plan 0019.
- Docker Scout authentication still blocks canonical native AMD64 evidence in
  plan 0022; this package does not expand credential authority.
- OpenStack upper constraints may intentionally exclude scanner-advertised
  fixed releases. A private override could introduce API/runtime incompatibility
  and remains unaccepted until the exact test matrix passes.
- The exact 18-package OS purge is accepted only as an experimental mechanism.
  It is not yet in production Containerfiles and cannot promote an image while
  either scanner retains Critical/High findings.
- Mako 1.3.12 is accepted only as one compatibility derivative. It does not
  authorize another package upgrade or a private OpenStack constraints fork,
  and the remaining absolute High counts keep promotion blocked.
- httplib2 0.32.0 is accepted only as a separate compatibility derivative.
  It is not cumulative with Mako in the current evidence and does not authorize
  production adoption or another target.
- urllib3 2.7.0 is accepted only as a separate compatibility derivative.
  Its stronger pool probe is not live HTTP traffic, and the result does not
  authorize a cumulative image or constraints override.
- PyJWT 2.13.0 is accepted only as a separate compatibility derivative. Its
  offline symmetric round trip is not Keystone/asymmetric token-path evidence
  and does not authorize a cumulative image or constraints override.
- Surface scope is target identity, not an operator override. A package can be
  tested only where the accepted remediation baseline proves that exact
  constrained version and findings are installed.
- Scanner-specific expected sets describe observed source coverage; they do
  not waive the union finding, permit a missing scanner, or weaken remaining
  Critical/High and secret gates.
- Django 4.2.30 is accepted only as a Horizon-scoped derivative. The framework
  smoke probe does not replace live Horizon/Kolla startup, reconfigure,
  upgrade, rollback, or browser acceptance after Stage 6 release gates close.
- Click 8.3.3 is accepted only as a separate two-surface derivative. A
  scanner-local empty expected set records absent Trivy coverage; it does not
  waive the Scout CVE or weaken either scanner's remaining absolute gate.
- The derivative proves static Kolla metadata, package integrity, installed UI
  runtime files, input cleanup, parent availability, and scan behavior. A
  production adoption still needs the Python compatibility matrix and later
  live Kolla startup/reconfigure/upgrade/rollback evidence after release gates
  permit a disposable cloud.

## Handoff

- Current state: Plan 0023 is active; plans 0019 and 0022 remain externally
  blocked. The inherited ARM64 classifier, deterministic baseline, stock
  dependency probe, post-Coffer OS cleanup trial, and narrow Mako compatibility
  derivative, generic target contract, and independent httplib2/urllib3
  and PyJWT compatibility derivatives, exact target-surface selection, the
  Horizon-only Django derivative, scanner-specific finding identities, and the
  independent Click derivative are complete locally with no waiver. The
  trials passed package, runtime, lineage, and two-scanner delta gates but
  correctly remain blocked by nonzero Critical/High findings. Raw/report
  evidence is non-secret and remains owner-only under ignored `work/`.
- Exact next action: Admit canonical GHSA identifiers without weakening the
  strict finding contract, then evaluate msgpack 1.2.1 independently.
- First file or command: Extend `FINDING` in
  `poc/ui-images/python_target.py` to accept only canonical CVE or GHSA
  identities and add rejection fixtures before adding a msgpack target; do not
  modify production UI Containerfiles.
- Questions requiring user input: None. No credential, external publication,
  live deployment, or waiver is required for the next local milestone.
