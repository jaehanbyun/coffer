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

Test one constraint-bound Python fix, or one dependency-coupled exact package
set, at a time on top of the accepted cleanup derivative:

```console
make -C poc/ui-images trial-python-overlay
make -C poc/ui-images trial-python-click
make -C poc/ui-images trial-python-cumulative
make -C poc/ui-images trial-python-cryptography-pyopenssl
make -C poc/ui-images trial-python-django
make -C poc/ui-images trial-python-httplib2
make -C poc/ui-images trial-python-lxml
make -C poc/ui-images trial-python-msgpack
make -C poc/ui-images trial-python-pillow
make -C poc/ui-images trial-python-urllib3
make -C poc/ui-images trial-python-pyjwt
make -C poc/ui-images trial-python-ujson
```

The checked-in `python_targets.json` manifest is the only target-selection
boundary. Its v4 contract binds each allowed target to one or more exact
package components. Every component records its official wheel URL, filename,
SHA-256, wheel architecture, dependency metadata, exact before/after versions,
and scanner-specific expected findings; the target also binds the
compatibility probe, explicit installed UI surfaces, and trial label.
Component names, wheel filenames, and findings must be disjoint, companions
must be sorted, and the target key must exactly identify the component set.

`trial-python-cumulative` selects the checked-in `accepted` entry from
`python_matrices.json`. The matrix manifest is bound to the exact
`python_targets.json` SHA-256 and names the complete sorted target set for each
surface. Horizon receives all 12 accepted package components; Skyline receives
ten and does not install the Horizon-only Django or Pillow wheels. The runner
creates a separate no-network build context for each surface, runs every
selected compatibility probe, collects exact aggregate package/runtime
evidence, and requires the scanner-specific cumulative finding delta. The
result remains fail-closed and cannot change a production Containerfile.

The 2026-07-27 clean native ARM64 cumulative trial accepted this matrix as a
compatibility and remediation mechanism. Horizon High changed from Trivy 31
to 1 and Scout 34 to 3; Skyline changed from Trivy 16 to 1 and Scout 19 to 3.
Every declared finding was removed, no Critical/High finding was introduced,
and Trivy found no secret. The accepted result SHA-256 is
`a920ce2076908469c06103fbd0f19953cbf6e67a4dead964faaf85d20ed21e0a`.
Only owner-readable evidence remains under ignored
`work/ui-python-overlay-trial-matrix-accepted/evidence/`; all bounded images,
contexts, wheel copies, archives, scanner caches, and the harness-started
Podman machine are absent after exit.

This result is still not a production candidate. Both surfaces retain
`CVE-2026-44393` in `oslo.messaging` 17.3.0, for which the scanners report no
fixed version. Docker Scout additionally reports `CVE-2024-6345` and
`CVE-2025-47273` in Ubuntu's system `setuptools` 68.1.2. Those residuals,
canonical AMD64 evidence, signed publication, and live Kolla acceptance remain
separate gates; no finding waiver or private OpenStack constraints override is
implied.

Both `trivy` and `scout` keys are mandatory;
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
generic overlay retains every official wheel filename for pip parsing and
removes the bounded wheel directory and target contract from the final image.

Pure-Python wheels must declare `wheel_architecture=any` and use the exact
`py3-none-any` tag. Native CPython wheels must declare either `arm64` with an
`aarch64` platform tag or `amd64` with an `x86_64` tag. The target loader,
runner preflight, evidence manifest, and classifier all reject a wheel whose
declared architecture does not match the trial runtime.

Each fixed trial installs only the declared official wheel set with
`--no-index`, `--no-deps`, and `--force-reinstall`. It requires the OS package
inventory to remain byte-for-byte equivalent to the accepted cleanup result,
preserves every installed Python distribution version including duplicate
development/install metadata, and permits no Python package delta except every
and only declared component.
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

The 2026-07-27 native ARM64 trial independently accepted the two-surface
`msgpack` 1.1.2 to 1.2.1 derivative using the exact official CPython 3.12
manylinux ARM64 wheel. The offline compatibility probe requires the native
`msgpack._cmsgpack` extension and performs a two-object streaming binary
pack/unpack round trip. Both surfaces preserve the accepted cleanup OS
inventory and every non-target Python distribution version multiset;
`pip check`, official source hashes, package-local bytecode boundaries,
Coffer UI runtime hashes, lineage, and build-input absence pass.

Both scanners removed exactly `GHSA-6v7p-g79w-8964`. Horizon changed from
Trivy 31 to 30 High and Scout 34 to 33 High; Skyline changed from Trivy 16 to
15 High and Scout 19 to 18 High. Neither scanner introduced a Critical/High
finding, and Trivy found no secret. The result remains isolated with
`production_candidate=false` and changes no production Containerfile or
constraints policy. Owner-only evidence is retained under ignored
`work/ui-python-overlay-trial-msgpack/evidence/`; generated images, contexts,
wheel copies, archives, scanner caches, and the harness-started Podman machine
are absent after exit.

The 2026-07-27 native ARM64 trial independently accepted the two-surface
`ujson` 5.11.0 to 5.13.0 derivative using the exact official CPython 3.12
manylinux ARM64 wheel. The offline compatibility probe requires the native
extension and performs a Unicode, nested-value JSON encode/decode round trip.
Both surfaces preserve the accepted cleanup OS inventory and every non-target
Python distribution version multiset; `pip check`, official source hashes,
exact top-level extension file boundaries, Coffer UI runtime hashes, lineage,
and build-input absence pass.

The selected 5.13.0 release is newer than the scanners' first fixed releases
5.12.0 and 5.12.1. The classifier compares numeric release components and
requires the selected target to reach at least one reported fixed floor; a
lower or nonnumeric floor fails closed.

Both scanners removed exactly `CVE-2026-32874`, `CVE-2026-32875`, and
`CVE-2026-44660`. Horizon changed from Trivy 31 to 28 High and Scout 34 to 31
High; Skyline changed from Trivy 16 to 13 High and Scout 19 to 16 High. Each
scanner also removed one Medium finding. Neither scanner introduced a
Critical/High finding, and Trivy found no secret. The result remains isolated
with `production_candidate=false` and changes no production Containerfile or
constraints policy. Owner-only evidence is retained under ignored
`work/ui-python-overlay-trial-ujson/evidence/`; generated images, contexts,
wheel copies, archives, scanner caches, and the harness-started Podman machine
are absent after exit.

The 2026-07-27 native ARM64 trial independently accepted the two-surface
`lxml` 6.0.2 to 6.1.1 derivative using the exact official CPython 3.12
manylinux ARM64 wheel. The offline compatibility probe requires the native
`lxml.etree` extension, exercises XML parsing and XPath, and requires the
candidate defaults for both `ETCompatXMLParser` and `iterparse` to reject an
external entity. Both surfaces preserve the accepted cleanup OS inventory and
every non-target Python distribution version multiset; `pip check`, official
source hashes, package-local extension boundaries, Coffer UI runtime hashes,
lineage, and build-input absence pass.

Baseline runtime evidence deliberately runs only the compatibility portion of
the probe because the installed 6.0.2 version is the vulnerable control.
Candidate runtime evidence additionally enforces the fixed security behavior.
The evidence records this distinction as `probe_mode=baseline|candidate`;
baseline mode is not a security qualification or waiver.

Both scanners removed exactly `CVE-2026-41066`. Horizon changed from Trivy 31
to 30 High and Scout 34 to 33 High; Skyline changed from Trivy 16 to 15 High
and Scout 19 to 18 High. Neither scanner introduced a Critical/High finding,
and Trivy found no secret. The result remains isolated with
`production_candidate=false` and changes no production Containerfile or
constraints policy. Owner-only evidence is retained under ignored
`work/ui-python-overlay-trial-lxml/evidence/`; generated images, contexts,
wheel copies, archives, scanner caches, and the harness-started Podman machine
are absent after exit.

The 2026-07-27 native ARM64 trial independently accepted the Horizon-only
`Pillow` 12.1.1 to 12.3.0 derivative using the exact official CPython 3.12
manylinux ARM64 wheel. The offline compatibility probe requires the native
`PIL._imaging` extension and performs an in-memory RGB PNG encode, signature
check, decode, load, and exact pixel round trip. Horizon preserves the accepted
cleanup OS inventory and every non-target Python distribution version
multiset; `pip check`, official source hashes, package-local native extension
boundaries, Coffer UI runtime hashes, lineage, and build-input absence pass.

Both scanners removed exactly the declared 12 High findings. Horizon changed
from Trivy 31 to 19 High and Scout 34 to 22 High. Each scanner also removed
six Medium findings. Neither scanner introduced a Critical/High finding, and
Trivy found no secret. Skyline does not contain Pillow and therefore has no
overlay or scan evidence in this trial.

The result remains isolated with `production_candidate=false` and changes no
production Containerfile or constraints policy. Owner-only evidence is
retained under ignored `work/ui-python-overlay-trial-pillow/evidence/`;
generated images, contexts, wheel copies, archives, scanner caches, and the
harness-started Podman machine are absent after exit.

The 2026-07-27 native ARM64 trial accepted the dependency-coupled
`cryptography` 43.0.3 to 49.0.0 and `pyOpenSSL` 24.2.1 to 26.3.0 derivative
on both surfaces. The exact two-wheel offline build is necessary because the
old pyOpenSSL requires cryptography below 44 while the selected pyOpenSSL
requires cryptography 49.x. The compatibility probe requires the native
cryptography Rust binding, performs an AES-GCM round trip, and constructs and
configures a pyOpenSSL TLS context. Both surfaces preserve the accepted
cleanup OS inventory and every non-target Python distribution version
multiset; `pip check`, official source hashes, per-component file boundaries,
Coffer UI runtime hashes, lineage, and build-input absence pass.

Both scanners removed exactly `CVE-2026-26007`, `CVE-2026-27459`, and
`GHSA-537c-gmf6-5ccf`. Horizon changed from Trivy 31 to 28 High and Scout 34
to 31 High; Skyline changed from Trivy 16 to 13 High and Scout 19 to 16 High.
Neither scanner introduced a Critical/High finding, and Trivy found no
secret. The accepted isolated result SHA-256 is
`1195c893ca4d634652a5d0b77517d3e8b45536883d577e1585d4129cfda4dfbe`.

The first build deliberately stopped before evidence collection when the TLS
probe assumed a pyOpenSSL context getter that does not exist. That bounded
state was removed, the probe was corrected to use supported setters, and a
clean rerun passed. The result remains
`production_candidate=false`, changes no production Containerfile or
constraints policy, and applies no waiver. Owner-only evidence is retained
under ignored
`work/ui-python-overlay-trial-cryptography-pyopenssl/evidence/`; generated
images, contexts, wheel copies, archives, scanner caches, and the
harness-started Podman machine are absent after exit.
