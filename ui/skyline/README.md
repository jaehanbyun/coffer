# Coffer Skyline Console overlay

This directory contains the exact-source Coffer integration for Skyline
Console `stable/2026.1`. It is a build-time source overlay, not a runtime
plugin. The stock Skyline Console remains unchanged unless an operator
deliberately builds and selects the overlaid image.

Prepare a disposable source tree:

```console
make -C ui/skyline prepare
make -C ui/skyline dependencies
make -C ui/skyline verify
```

`SOURCE` must be a clean checkout at the revision in `baseline.json`.
`BUILD_DIR` must not exist. Generated trees and dependencies belong under
`work/` and are not committed. The verified deployable is a
`skyline-console` wheel with local version `8.0.0+coffer.1`; the build includes
the generated locale catalog and immutable production static bundle.

The upstream full-source lint currently has seven pre-existing failures in
Nova hypervisor/instance files at the pinned clean revision. `verify` runs the
upstream linter over every Coffer-owned file and every central file changed by
the overlay, plus the focused tests and production build. It does not hide or
reclassify the unrelated upstream baseline failures as Coffer results.

The repository detail overlay includes a native Ant Design image and OCI
artifact browser with bounded tag/digest search, forward/back navigation,
safe metadata and copyable pull references. Its Docker, Podman, Helm, and ORAS
connection dialog derives the host from authenticated Coffer discovery and
uses the existing hidden-secret OpenStackClient login flow. Skyline never
queries Distribution or object storage directly and never renders a registry
token or application-credential secret.

`ui/images/skyline-console.Containerfile` installs the verified wheel over an
exact digest-pinned Kolla Skyline Console base. The companion role selects that
custom image only when explicitly enabled, records the exact stock fallback,
and restores it before removing its recovery marker. It never modifies
`skyline_apiserver` or running static files in place.
