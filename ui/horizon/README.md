# Coffer Horizon dashboard

This directory contains the independently installable Horizon plugin for the
Coffer OCI Registry control API.

The current Kolla 2026.1 compatibility baseline is Horizon 25.7.3. The plugin discovers
the versioned `oci-registry` endpoint from the current scoped Keystone catalog
and keeps the token in Horizon's server-side request boundary.

This package is under active plan 0020. Adapter tests may be run before the
panel is enabled; installation and Kolla lifecycle instructions are added with
the complete dashboard milestone.
