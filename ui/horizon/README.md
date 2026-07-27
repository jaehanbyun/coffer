# Coffer Horizon dashboard

This directory contains the independently installable Horizon plugin for the
Coffer OCI Registry control API.

The current Kolla 2026.1 compatibility baseline is Horizon 25.7.3. The plugin discovers
the versioned `oci-registry` endpoint from the current scoped Keystone catalog
and keeps the token in Horizon's server-side request boundary.

The plugin adds **Project → Registry → Repositories**. It supports the bounded
MVP control surface only:

- repository list with forward pagination;
- repository creation and immutable-tag selection;
- repository detail;
- current-project quota usage.

It intentionally has no delete, manifest, tag, signer, scanner, storage,
maintenance, or administrator quota surface.

## Development verification

The exact Horizon source checkout is required so that a passing test cannot
silently move to another framework revision:

```console
make -C ui/horizon sync
make -C ui/horizon verify
uv build --project ui/horizon --out-dir work/horizon-dist
```

The verifier checks Horizon source revision `0a443955...`, Horizon 25.7.3,
Django 4.2.28, keystoneauth1 5.13.1, pytest 9.0.2, and pytest-django 4.12.0.

## Horizon installation contract

The custom image installs the wheel into Horizon's Python environment, then
copies these exact runtime registration files into the corresponding image
directories:

```text
cofferdashboard/enabled/_1910_project_registry_panel_group.py
cofferdashboard/enabled/_1920_project_registry_repositories_panel.py
    -> openstack_dashboard/local/enabled/

cofferdashboard/local_settings.d/_1930_coffer_policy.py
    -> openstack_dashboard/local/local_settings.d/

cofferdashboard/conf/coffer_policy.yaml
cofferdashboard/conf/default_policies/coffer.yaml
    -> openstack_dashboard/conf/
```

Kolla's existing Horizon startup regenerates static/compressed assets when its
settings change. The panel remains invisible when the current scoped service
catalog does not contain an `oci-registry` endpoint. The endpoint must be an
HTTP(S) URL ending in `/v1`; the current scoped token is used only by the
server-side keystoneauth session.

`ui/images/horizon.Containerfile` and `ui/images/install_horizon.py` define the
image boundary. The Kolla companion role owns the opt-in immutable-image swap,
reconfigure, fallback, and recovery-marker lifecycle. Installing this wheel
alone does not prove a deployed cloud integration.
