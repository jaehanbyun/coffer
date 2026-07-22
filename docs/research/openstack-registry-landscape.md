# OpenStack OCI Registry Landscape

- Status: evidence summary
- Researched: 2026-07-21
- Scope: current official OpenStack governance, service types, projects, deployment tooling, consumers, and relevant historical work

## Conclusion

No current first-class, Keystone-integrated OCI/container registry service, registered service type, or active service-creation proposal was verified in the researched official sources. The [OpenStack project-team catalog](https://governance.openstack.org/tc/reference/projects/) lists Glance, Magnum, Zun, Swift, OpenStack-Helm, Kolla, and related teams but no registry service team. The canonical [service-types authority](https://opendev.org/openstack/service-types-authority/src/branch/master/service-types.yaml) includes image, object store, container infrastructure management, and application container services but no OCI/container-registry service type.

This is a time-bounded no-evidence result, not proof that no community conversation exists. The search covered current governance, service types, official documentation/source for the projects below, specification trees, retirement records, and current OpenDev/Gerrit exact-term results. It may not include unindexed PTG Etherpads, mailing-list discussions, or downstream/private initiatives.

## Current Projects and Reuse Boundaries

| Component | Current verified role | Coffer implication |
|---|---|---|
| OpenStack-Helm | The active [registry chart](https://docs.openstack.org/openstack-helm/latest/chart/registry.html) deploys upstream `docker.io/library/registry:2`. Current documented defaults include one replica, filesystem storage on a 2 GiB PVC, disabled public ingress, and registry auth disabled for its OCI image-registry endpoint. | Reuse/adapt packaging conventions for development or a future Helm deployment. It is infrastructure packaging, not a Keystone-integrated multi-tenant registry control plane. |
| Ironic | Current [OCI registry support](https://docs.openstack.org/ironic/latest/admin/oci-container-registry.html) can retrieve disk images and deployment artifacts from `oci://` locations. The feature is experimental, direct-Ironic only, and currently authenticates with pre-shared pull secrets/basic auth rather than Keystone-to-registry exchange. | Strong first OpenStack consumer and proof of current OCI-artifact demand. Add an Ironic interoperability test after the core Docker/ORAS flow. |
| Glance | The [Glance mission](https://governance.openstack.org/tc/reference/projects/glance.html) is bootable disk images and compute initialization data. Its [`docker` container format](https://docs.openstack.org/glance/latest/user/formats.html) means a Docker filesystem tar archive, not OCI indexes/manifests/layers/tags. | Reuse design experience for ownership, visibility/sharing, import, and storage operations. Do not fork its API/data model for OCI. A Glance↔OCI bridge is separate work. |
| Zun | Zun manages running application containers. [API microversions 1.30 and 1.31](https://docs.openstack.org/zun/latest/reference/api-microversion-history.html) add private-registry records and `registry_id`; its [private registry guide](https://docs.openstack.org/zun/latest/admin/private_registry.html) deploys upstream `registry:2`. | Treat Zun as a consumer/integration target. Its registry resource stores endpoint credentials for image pull; it is not a manifest/blob/tag data plane. |
| Magnum | Magnum's current mission is orchestration-engine lifecycle. Its historical Heat driver contained a cluster-local Swift-backed Registry V2, but that driver and remaining templates were removed in 2026 ([driver removal](https://opendev.org/openstack/magnum/commit/31b84327db8867ce67df6b7cf0189ad46e8a4f87), [template removal](https://opendev.org/openstack/magnum/commit/0c6e7d49066431c0ba2350ccad816ae987c0f045)). | Historical input only. Integrate later with the current CAPI/Kubernetes path after a concrete credential/pull-secret requirement is established. |
| Kolla | Kolla builds/deploys containerized OpenStack and documents use of an external local registry in its [multinode guide](https://docs.openstack.org/kolla-ansible/latest/user/multinode.html) and [image builder](https://docs.openstack.org/kolla/latest/admin/image-building.html). | Make Coffer a compatible push/pull target and reuse deployment conventions; there is no Kolla registry control plane to extract. |
| Keystone | Keystone supplies authentication, projects, roles, service discovery, application credentials, and audit context. [Application credentials](https://docs.openstack.org/keystone/latest/user/application_credentials.html) support workload authentication within a project. | Use Keystone as identity/project/role authority. A Coffer token adapter is still required because OCI clients follow the Bearer challenge rather than `X-Auth-Token` on every data request. |
| Swift | Swift is a durable object service and documents [backing-store patterns](https://docs.openstack.org/swift/latest/overview_backing_store.html) for other services. | It is a possible blob backend, not an OCI implementation. Distribution v3 lacks a Swift driver; RGW/S3 is the shorter MVP path. Swift requires a separate focused architecture if later demanded. |

## Historical False Friends

- **`glance-registry`** proxied Glance database operations. It was not a container registry or public OCI endpoint; the [deprecation specification](https://specs.openstack.org/openstack/glance-specs/specs/newton/approved/glance/deprecate-registry.html) explains that role, and the service was removed in Victoria.
- **Glare/Glance Artifacts** was experimental arbitrary-artifact work. It was removed from Glance and its standalone repository is outside current official deliverables; it is not a maintained OCI base.
- **TripleO `ansible-role-container-registry`** deployed Docker Distribution as infrastructure. Its [repository](https://opendev.org/openstack/ansible-role-container-registry) is retired with TripleO.
- **Magnum's Swift-backed registry** was cluster-scoped machinery in the removed Heat driver, not a regional cloud service.

## Product and Architecture Implications

1. Coffer's defensible scope is OpenStack-native identity, project isolation, service discovery, policy, quota/lifecycle orchestration, and operations around a mature OCI data plane.
2. Glance and Zun provide useful resource/policy conventions but the wrong canonical data models for registry content.
3. Use immutable Keystone project IDs for the security namespace and treat human-readable names as aliases.
4. Start interoperability with standard clients, then Ironic `oci://`; follow with Kolla and Zun. Defer Magnum until its current CAPI path has a confirmed need.
5. Before external publication, discuss the problem and ownership boundary with relevant OpenStack communities. A future official service needs a service-type addition and a governance home or new project-team proposal.
6. Do not describe the OpenStack-Helm registry chart as competition or prior service implementation; it is a useful deployment artifact that Coffer may eventually supersede or extend.

## Open Questions

- Whether an existing team would consider the service within its mission, or whether an independent emerging project is the correct starting point.
- Whether the OpenStack community will accept Coffer's proposed `oci-registry` service type and which governance home is appropriate.
- Whether Ironic's current authentication path can consume a Coffer-generated pull credential without storing a long-lived secret.
- Whether Glance↔OCI import/export is valuable enough to plan after the registry MVP.
