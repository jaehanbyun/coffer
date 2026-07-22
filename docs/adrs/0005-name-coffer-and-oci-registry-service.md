# ADR 0005: Name the Project Coffer and the Service OCI Registry

- Status: accepted
- Date: 2026-07-21
- Decision owners: project maintainer
- Related plan: `docs/exec-plans/0001-product-discovery.md`

## Context

The initial working name `jangdok` expressed the storage concept in Korean but required explanation for a global OpenStack and OCI audience. OpenStack also distinguishes a project codename from the descriptive service name, the machine-readable Keystone service type, and the user-facing CLI vocabulary. Treating those as one brand would make documentation and future governance unnecessarily ambiguous.

The OpenStack naming guidance says project names are written in lowercase, user/operator documentation should prefer a descriptive service name, and the service name should not include `OpenStack`. Keystone separately defines the catalog `name` as a deployer-brandable display value and `type` as the stable description of the API implemented.

## Decision

Use the following naming contract:

| Concern | Accepted value | Usage |
|---|---|---|
| Project codename | `coffer` | Source repository, packages, processes, configuration, contributor references |
| Descriptive service name | `OCI Registry service` | User, operator, administrator, and application-developer documentation |
| Keystone service type | `oci-registry` | Proposed machine-readable catalog and policy namespace; provisional until accepted by the service-types authority |
| CLI noun | `registry` | `openstack registry repository ...` and related user commands |
| Component prefix | `coffer-` | `coffer-api`, `coffer-auth`, `coffer-worker` |
| Environment prefix | `COFFER_` | Development, test, and deployment variables |

The preferred introductory sentence is:

> The coffer project provides the OCI Registry service for OpenStack clouds.

Do not use `OpenStack Coffer`, `Coffer Registry service`, or the project codename as the service type. A deployer can choose its own Keystone catalog display name without changing `oci-registry` semantics.

## Why Coffer

- In English, a coffer is a durable chest for storing valuable items, which maps to protected OCI artifacts without limiting the project to container images.
- It is short, pronounceable, and suitable as a lowercase package/process prefix.
- It separates implementation identity from the descriptive service name, matching established OpenStack documentation practice.
- It preserves room for images, indexes, signatures, SBOMs, and other OCI artifacts while the MVP remains OCI-only.

## Alternatives Rejected

### Keep `jangdok`

Rejected as the permanent codename because its meaning and pronunciation require explanation for much of the intended global contributor and operator audience. The original name remains part of project history, not a compatibility identifier.

### Use one descriptive name everywhere

Rejected because `oci-registry` is useful as an API/service type but too mechanical as a repository and process identity. OpenStack explicitly separates project and service naming.

### Use `OpenStack` in the service name

Rejected because OpenStack governance guidance says service names should not include `OpenStack`. Documentation can still say that Coffer provides the OCI Registry service for OpenStack clouds.

### Use `artifact-registry` or `container-registry` as the service type

Not selected. `artifact-registry` implies non-OCI package protocols that are explicit MVP non-goals, while `container-registry` underrepresents OCI-native artifacts such as signatures and SBOMs. `oci-registry` states the protocol boundary directly.

## Consequences

- Existing documentation, diagrams, example cloud profiles, and environment variables use Coffer naming immediately; there is no released API or compatibility surface requiring aliases.
- The canonical local repository directory is `/coffer`. A compatibility symlink at the legacy path temporarily preserves the active Codex workspace and can be removed after the project is reopened from the canonical path.
- `oci-registry` is a project proposal, not a currently registered OpenStack service type. External publication or governance submission requires separate approval and community review.
- A preliminary ecosystem search is not legal clearance. Before public launch, perform trademark review and check repository organization, package indexes, domains, and container image namespaces.

## Primary Evidence

- [OpenStack Service and Project Naming](https://governance.openstack.org/tc/reference/service-project-naming.html)
- [OpenStack documentation naming conventions](https://docs.openstack.org/doc-contrib-guide/writing-style/openstack-components.html)
- [Keystone service catalog guidance](https://docs.openstack.org/keystone/latest/contributor/service-catalog.html)
- [OpenStack Legal Issues FAQ for new project names](https://wiki.openstack.org/wiki/LegalIssuesFAQ)
