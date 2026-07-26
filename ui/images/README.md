# Coffer Kolla UI images

The Horizon plugin and Skyline source overlay are packaged into custom Kolla
images. A running dashboard is never modified in place.

Both image builds require an exact `@sha256:` base image reference. Prepare one
directory with the matching Containerfile, wheel, and the Horizon installer
when applicable:

```text
horizon.Containerfile
install_horizon.py
coffer_horizon-0.1.0-py3-none-any.whl

skyline-console.Containerfile
skyline_console-8.0.0+coffer.1-py3-none-any.whl
```

Build, scan, sign, and push the image through the operator's normal image
pipeline. Resolve both the custom and stock fallback images to immutable OCI
digests. Then produce the controller-side public contract consumed by the
Coffer companion role:

```console
python3 ui/images/write_contract.py \
  --surface horizon \
  --artifact work/horizon-dist/coffer_horizon-0.1.0-py3-none-any.whl \
  --base-image registry.example/horizon@sha256:BASE_DIGEST \
  --image registry.example/coffer-horizon@sha256:CUSTOM_DIGEST \
  --output /etc/kolla/config/coffer/ui/horizon-image.json

python3 ui/images/write_contract.py \
  --surface skyline \
  --artifact \
    work/skyline-console-coffer-wheel/skyline_console-8.0.0+coffer.1-py3-none-any.whl \
  --base-image registry.example/skyline-console@sha256:BASE_DIGEST \
  --image registry.example/coffer-skyline-console@sha256:CUSTOM_DIGEST \
  --output /etc/kolla/config/coffer/ui/skyline-image.json
```

The contract contains no credential. It binds the wheel hash, exact upstream
revision, custom image digest, and exact fallback digest. The companion role
copies it as a per-host recovery marker before swapping an existing dashboard
container. Disabling the surface by reconfigure restores the recorded fallback
image and removes the marker only after the container reconciliation succeeds.

These files provide a build and deployment contract. They do not claim an
image was built, scanned, signed, pushed, or deployed until those operations
have separate evidence.
