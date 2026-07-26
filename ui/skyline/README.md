# Coffer Skyline Console overlay

This directory contains the exact-source Coffer integration for Skyline
Console `stable/2026.1`. It is a build-time source overlay, not a runtime
plugin. The stock Skyline Console remains unchanged unless an operator
deliberately builds and selects the overlaid image.

Prepare a disposable source tree:

```console
make -C ui/skyline prepare
make -C ui/skyline dependencies
make -C ui/skyline test-core
```

`SOURCE` must be a clean checkout at the revision in `baseline.json`.
`BUILD_DIR` must not exist. Generated trees and dependencies belong under
`work/` and are not committed.
