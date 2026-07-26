# UI image production qualification

This harness closes the gap between Coffer's tested Horizon/Skyline packages
and actual immutable container images. It is deliberately separate from the
Kolla role fixture and from the Stage 6 live pilot.

The accepted transaction builds stock `horizon` and `skyline-console` parents
from Kolla `stable/2026.1` at the pinned commit and Ubuntu Noble platform
digest. It never treats `quay.io/openstack.kolla` test images as production
parents. The exact Coffer wheels are then installed with the Containerfiles in
`ui/images/`.

Four images are inspected and scanned in one bounded transaction:

```text
horizon-parent  ── exact layer prefix ──> horizon-custom
skyline-parent  ── exact layer prefix ──> skyline-custom
```

`qualification.py` validates:

- exact Kolla, Horizon, and Skyline source revisions;
- actual Horizon/Skyline wheel names, versions, and SHA-256 values;
- Linux native architecture and immutable image configuration digests;
- preserved Kolla user, entrypoint, command, and parent layer prefix;
- required Coffer OCI labels;
- installed package versions and runtime files matching wheel members;
- absence of wheel/installer build inputs from the final filesystem;
- non-empty SPDX inventories;
- Trivy vulnerability and secret results;
- Docker Scout SARIF vulnerability results;
- identical inherited finding sets plus an explicit custom-image delta.

The result is `qualified` only when both parent and custom images have zero
Critical/High findings under both scanners, no secrets, no introduced finding,
and every provenance/runtime contract passes. A custom image introducing
nothing does not hide an unresolved parent finding: the whole surface remains
blocked.

The verifier is fixture-testable without a container engine:

```console
make -C poc/ui-images verify
```

Run the bounded native transaction only from a clean work path with an already
running Podman machine:

```console
make -C poc/ui-images qualify
```

The harness serializes the stock and custom builds. Scanner databases are
acquired with the pinned Trivy image before each scan, while the actual Trivy
image scans run with no network, read-only database mounts, and an ephemeral
writable cache. Docker Scout consumes one Podman-produced archive at a time.
The exit contract is:

- `0`: every absolute and delta gate qualified;
- `3`: complete valid evidence, correctly blocked by one or more production
  gates;
- any other value: invalid or incomplete transaction.

The 2026-07-26 native ARM64 transaction completed with status `blocked`.
Horizon parent/custom had 641/642 SPDX packages and Skyline parent/custom had
569/570. Both scanners reported zero introduced and zero missing Coffer
Critical/High findings, and Trivy reported zero secrets. Production remained
blocked by inherited stock-parent findings: Horizon had Trivy 1 Critical/83
High and Scout 0 Critical/75 High; Skyline had Trivy 1 Critical/68 High and
Scout 0 Critical/60 High.

Non-secret evidence is retained under the ignored owner-only
`work/ui-image-qualification/evidence/` path. The harness removes its exact
containers, images, scan archives, scanner cache, and temporary mounts on
every exit. It does not sign, publish, push, deploy, or create a credential.
Native x86_64 remains a separate qualification gate.

## Parent remediation baseline

`remediation.py` analyzes only complete inherited Critical/High evidence. It
refuses a parent/custom finding mismatch, checks the counts against the
canonical qualification, reads the exact root `upper-constraints.txt` member
from Kolla's archived `openstack-base` source, and binds its SHA-256 plus the
official OpenStack requirements revision.

The report separates constraint-bound Python packages, OS packages, and
upstream-unfixed findings. Scanner-advertised fixed versions are compatibility
experiment inputs only. The report never applies a waiver, accepts a private
global-constraints fork, claims reachability, or qualifies an image with an
inherited Critical/High finding.

```console
python3 poc/ui-images/remediation.py \
  work/ui-image-qualification/evidence \
  --openstack-base-archive \
    work/ui-image-qualification/contexts/docker/openstack-base/openstack-base-archive \
  --requirements-revision 06cd4e8523cbade25fb93efc4f8ea77d6d97064f
```

Exit `3` is the expected valid-but-blocked result while inherited findings
remain. Invalid, incomplete, or divergent evidence exits `2`; a clean report
alone exits `0` but does not bypass the separate native AMD64 or Stage 6 gates.

Before removing an OS package, collect the stock-parent dependency boundary:

```console
make -C poc/ui-images probe-parents
```

The bounded runner builds only fixed-name disposable Kolla parents, executes
`package_probe.py` with no network, a read-only filesystem, no capabilities,
and no-new-privileges, then deletes the exact images and generated build
contexts. It records package marks, direct reverse dependencies, package-file
classes, clean package-database checks, and an `apt-get -s` purge plan. The
read-only result always sets `safe_to_apply` to false; a separate derivative
build/runtime/scan experiment is required before any cleanup can be accepted.

Apply that exact simulated transaction only to disposable post-Coffer
derivatives:

```console
make -C poc/ui-images trial-os-cleanup
```

The trial does not change either production UI Containerfile. It builds the
exact stock parents and Coffer wheels first, derives new images by purging
`linux-libc-dev` and its exact 17 dependent development packages, and requires:

- no added or version-changed Debian package and the exact simulated removal
  set;
- clean `dpkg --audit` and `apt-get -s check` results;
- unchanged Kolla user, entrypoint, command, and inherited layer prefix;
- byte-identical installed Coffer runtime files and no retained wheel/build
  inputs;
- exact source, wheel, image, scanner, and stock-probe identities;
- zero introduced Critical/High finding under both Trivy and Docker Scout;
- at least one removed Critical/High finding for every scanner and surface;
- zero Trivy secret finding.

The 2026-07-26 native ARM64 trial accepted the cleanup mechanism but correctly
kept production blocked. Trivy Critical/High fell from 1/83 to 0/31 for
Horizon and from 1/68 to 0/16 for Skyline. Docker Scout High fell from 75 to
34 and from 60 to 19 respectively. Neither scanner found a newly introduced
Critical/High issue, and Trivy found no secret. The exact images, generated
contexts, wheel copies, archives, and scanner caches were deleted; the
pre-existing Podman machine was restored to stopped. Owner-only, non-secret
evidence remains under ignored `work/ui-os-cleanup-trial/evidence/`.

This result permits a later production-image design to include an equivalent
final-image cleanup only after the remaining compatibility and release gates
close. It does not approve a private OpenStack constraints fork, a CVE waiver,
an image publication, or a production deployment. Exit `3` remains the
expected successful result while the cleaned images have nonzero
Critical/High findings.

Test one constraint-bound Python fix at a time on top of the accepted cleanup
derivative:

```console
make -C poc/ui-images trial-python-overlay
make -C poc/ui-images trial-python-click
make -C poc/ui-images trial-python-django
make -C poc/ui-images trial-python-httplib2
make -C poc/ui-images trial-python-urllib3
make -C poc/ui-images trial-python-pyjwt
```

The checked-in `python_targets.json` manifest is the only target-selection
boundary. Its v2 contract binds each allowed package to the official wheel
URL, filename, SHA-256, dependency metadata, exact before/after versions,
scanner-specific expected findings, compatibility probe, explicit installed
UI surfaces, and trial label. Both `trivy` and `scout` keys are mandatory;
each scanner may have an empty expected set, but their union must be nonempty,
sorted, unique, canonical CVE or GHSA identifiers and must exactly equal the accepted
remediation candidate. The classifier requires each scanner to remove exactly
its declared set and rejects any introduced Critical/High finding. This
represents scanner observation differences without suppressing or waiving a
finding.

GHSA identities follow GitHub's canonical
`GHSA(-[23456789cfghjmpqrvwx]{4}){3}` syntax. Uppercase, ambiguous alphabet
characters, truncated groups, free-form advisory names, and any other finding
namespace are rejected.

The loader rejects unknown scanners, surfaces, or fields, unsafe filenames or
URLs, unsupported probes, arbitrary target keys, and linked manifests. The
runner builds the target overlay and inventories and scans only those declared
surfaces; it cannot silently install a Horizon-only dependency into Skyline.
Stock parent preparation may still build both accepted UI baselines. The
generic overlay retains the official wheel filename for pip parsing and still
removes that exact build input from the final image.

Each fixed trial installs one official wheel with `--no-index`, `--no-deps`,
and `--force-reinstall`. It requires the OS package inventory to remain
byte-for-byte equivalent to the accepted cleanup result, preserves every
installed Python distribution version including duplicate development/install
metadata, and permits no Python package delta except the selected target.
`pip check`, the target-specific compatibility probe, installed wheel source
hashes, Horizon/Skyline Coffer runtime hashes, image lineage, input removal,
and the two-scanner/secret gates are all mandatory.

The 2026-07-26 native ARM64 trial accepted that narrow compatibility
derivative for Mako 1.3.12. Horizon High findings changed from Trivy 31 to 29
and Scout 34 to 32; Skyline changed from Trivy 16 to 14 and Scout 19 to 17.
Both scanners removed exactly `CVE-2026-41205` and `CVE-2026-44307`,
introduced no Critical/High finding, and Trivy found no secret.

The result remains `blocked` with `production_candidate=false`. It does not
modify the production UI Containerfiles, adopt a private global-constraints
override, approve another Python upgrade, or close the native AMD64,
Distribution, Ceph, signing, publication, or live deployment gates.
Owner-only evidence is retained under the ignored
`work/ui-python-overlay-trial-mako/evidence/` path; generated images, contexts,
wheel copies, archives, scanner caches, and a harness-started Podman machine
are removed on exit.

The 2026-07-27 native ARM64 trial independently accepted the `httplib2`
0.31.2 to 0.32.0 derivative. Horizon High findings changed from Trivy 31 to
30 and Scout 34 to 33; Skyline changed from Trivy 16 to 15 and Scout 19 to
18. Both scanners removed exactly `CVE-2026-59939`, introduced no
Critical/High finding, and Trivy found no secret. OS inventories, all
non-target Python version multisets, `pip check`, import compatibility,
official wheel source hashes, package-local bytecode boundaries, Coffer UI
runtime hashes, lineage, and build-input removal passed.

This second result is also accepted only as an isolated compatibility
derivative. It remains `blocked` with `production_candidate=false`, changes no
production Containerfile, and grants no broad constraints override. Owner-only
evidence is retained under ignored
`work/ui-python-overlay-trial-httplib2/evidence/`; generated images, contexts,
wheel copies, archives, scanner caches, and the harness-started Podman machine
are absent after exit.

The 2026-07-27 native ARM64 trial independently accepted the `urllib3` 2.6.3
to 2.7.0 derivative using the official non-yanked PyPI wheel. The compatibility
probe constructs and clears an HTTPS connection pool without performing a
network request. Horizon High findings changed from Trivy 31 to 29 and Scout
34 to 32; Skyline changed from Trivy 16 to 14 and Scout 19 to 17. Both
scanners removed exactly `CVE-2026-44431` and `CVE-2026-44432`, introduced no
Critical/High finding, and Trivy found no secret.

The result remains an isolated, non-cumulative compatibility derivative with
`production_candidate=false`. It changes no production Containerfile or
constraints policy. Owner-only evidence is retained under ignored
`work/ui-python-overlay-trial-urllib3/evidence/`; generated images, contexts,
wheel copies, archives, scanner caches, and the harness-started Podman machine
are absent after exit.

The 2026-07-27 native ARM64 trial independently accepted the `PyJWT` 2.11.0
to 2.13.0 derivative using the official non-yanked PyPI wheel. The
compatibility probe performs an offline HS256 encode/decode round trip with
fixture-only key material. Horizon High findings changed from Trivy 31 to 29
and Scout 34 to 32; Skyline changed from Trivy 16 to 14 and Scout 19 to 17.
Both scanners removed exactly `CVE-2026-32597` and `CVE-2026-48526`,
introduced no Critical/High finding, and Trivy found no secret.

The result remains an isolated, non-cumulative compatibility derivative with
`production_candidate=false`. It changes no production Containerfile or
constraints policy and does not exercise asymmetric or Keystone token paths.
Owner-only evidence is retained under ignored
`work/ui-python-overlay-trial-pyjwt/evidence/`; generated images, contexts,
wheel copies, archives, scanner caches, and the harness-started Podman machine
are absent after exit.

The 2026-07-27 native ARM64 trial independently accepted the Horizon-only
`Django` 4.2.28 to 4.2.30 derivative using the official non-yanked PyPI wheel.
The offline compatibility probe configures a minimal framework instance, calls
`django.setup()`, and renders a template. Horizon High findings changed from
Trivy 31 to 28 and Scout 34 to 31. Both scanners removed exactly
`CVE-2026-25673`, `CVE-2026-33034`, and `CVE-2026-3902`, introduced no
Critical/High finding, and Trivy found no secret.

Skyline does not contain Django and therefore has no target overlay, runtime,
or scanner evidence in this trial. The result remains isolated with
`production_candidate=false`; it changes no production Containerfile or
constraints policy. Owner-only evidence is retained under ignored
`work/ui-python-overlay-trial-django/evidence/`; generated images, contexts,
wheel copies, archives, scanner caches, and the harness-started Podman machine
are absent after exit.

The 2026-07-27 native ARM64 trial independently accepted the two-surface
`click` 8.3.1 to 8.3.3 derivative using the official non-yanked PyPI wheel.
The offline compatibility probe invokes a real Click command through
`CliRunner`. Both surfaces preserve the accepted cleanup OS inventory and
every non-target Python distribution version multiset; `pip check`, official
source hashes, package-local bytecode boundaries, Coffer UI runtime hashes,
lineage, and build-input absence pass.

Trivy did not report the Click finding and remained unchanged at Horizon 31
High and Skyline 16 High. Docker Scout alone removed exactly
`CVE-2026-7246`, changing Horizon from 34 to 33 High and Skyline from 19 to 18
High. Neither scanner introduced a Critical/High finding, and Trivy found no
secret. The result remains isolated with `production_candidate=false` and
changes no production Containerfile or constraints policy. Owner-only evidence
is retained under ignored `work/ui-python-overlay-trial-click/evidence/`;
generated images, contexts, wheel copies, archives, scanner caches, and the
harness-started Podman machine are absent after exit.
