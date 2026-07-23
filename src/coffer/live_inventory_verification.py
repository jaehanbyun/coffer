from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from coffer.quota import QuotaStore
from coffer.quota_import import InventoryArtifact
from coffer.quota_import_verification import (
    InventoryVerificationSnapshot,
    verify_inventory_import_snapshot,
)
from coffer.quota_reconciliation import ManifestPresence, ProbeObservation


class LiveInventoryAuthenticationRequired(Exception):
    pass


class LiveInventoryVerificationFailed(Exception):
    def __init__(self, result: LiveInventoryVerificationResult) -> None:
        super().__init__(
            "live Distribution inventory does not match the verified import"
        )
        self.result = result


@dataclass(frozen=True, slots=True)
class LiveRepositoryTarget:
    repository_id: str
    canonical_name: str


class AuthenticatedManifestProbe(Protocol):
    def prepare(self, repositories: tuple[LiveRepositoryTarget, ...]) -> None: ...

    def probe(
        self,
        *,
        repository_id: str,
        repository: str,
        digest: str,
    ) -> ProbeObservation: ...


@dataclass(frozen=True, slots=True)
class LiveInventoryVerificationResult:
    status: str
    inventory_digest: str
    repository_count: int
    manifest_count: int
    present_count: int
    absent_count: int
    indeterminate_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "absent_count": self.absent_count,
            "indeterminate_count": self.indeterminate_count,
            "inventory_digest": self.inventory_digest,
            "manifest_count": self.manifest_count,
            "present_count": self.present_count,
            "repository_count": self.repository_count,
            "status": self.status,
        }


def _authentication_required() -> LiveInventoryAuthenticationRequired:
    return LiveInventoryAuthenticationRequired(
        "authenticated live Distribution probe is required"
    )


def _prepare_probe(
    probe: AuthenticatedManifestProbe | None,
    snapshot: InventoryVerificationSnapshot,
) -> AuthenticatedManifestProbe:
    if probe is None:
        raise _authentication_required()
    targets = tuple(
        LiveRepositoryTarget(route.repository_id, route.canonical_name)
        for route in snapshot.repositories
    )
    try:
        probe.prepare(targets)
    except Exception:
        raise _authentication_required() from None
    return probe


def verify_live_inventory(
    store: QuotaStore,
    artifact: InventoryArtifact,
    probe: AuthenticatedManifestProbe | None,
) -> LiveInventoryVerificationResult:
    snapshot = verify_inventory_import_snapshot(store, artifact)
    authenticated_probe = _prepare_probe(probe, snapshot)
    present = 0
    absent = 0
    indeterminate = 0
    for route in snapshot.repositories:
        for digest in route.manifest_digests:
            try:
                observation = authenticated_probe.probe(
                    repository_id=route.repository_id,
                    repository=route.canonical_name,
                    digest=digest,
                )
                presence = observation.presence
            except Exception:
                presence = ManifestPresence.INDETERMINATE
            if presence is ManifestPresence.PRESENT:
                present += 1
            elif presence is ManifestPresence.ABSENT:
                absent += 1
            else:
                indeterminate += 1

    status = "verified" if absent == 0 and indeterminate == 0 else "refused"
    result = LiveInventoryVerificationResult(
        status=status,
        inventory_digest=artifact.digest,
        repository_count=len(snapshot.repositories),
        manifest_count=sum(
            len(route.manifest_digests) for route in snapshot.repositories
        ),
        present_count=present,
        absent_count=absent,
        indeterminate_count=indeterminate,
    )
    if status != "verified":
        raise LiveInventoryVerificationFailed(result)
    return result
