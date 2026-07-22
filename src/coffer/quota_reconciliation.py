from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
import http.client
import ssl
from typing import Protocol
from urllib.parse import urlsplit

from coffer.db import RepositoryStore
from coffer.quota import (
    MAX_RECONCILIATION_BATCH,
    SHA256_DIGEST,
    QuotaStore,
    ReconciliationCursor,
    StaleReconciliationCandidate,
)
from coffer.tokens import REPOSITORY_NAME


PROBE_HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "content-length",
        "host",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
MANIFEST_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
    )
)


class ManifestPresence(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True, slots=True)
class ProbeObservation:
    presence: ManifestPresence
    status_code: int | None


class ManifestProbe(Protocol):
    def probe(self, *, repository: str, digest: str) -> ProbeObservation: ...


class RepositoryResolver(Protocol):
    def resolve(self, *, project_id: str, repository_id: str) -> str | None: ...


class RepositoryStoreResolver:
    def __init__(self, repositories: RepositoryStore) -> None:
        self._repositories = repositories

    def resolve(self, *, project_id: str, repository_id: str) -> str | None:
        repository = self._repositories.get(project_id, repository_id)
        if repository is None:
            return None
        canonical = f"p/{project_id}/{repository.name}"
        return canonical if REPOSITORY_NAME.fullmatch(canonical) is not None else None


class HTTPDistributionManifestProbe:
    def __init__(
        self,
        upstream_url: str,
        *,
        timeout_seconds: float = 10.0,
        headers: Mapping[str, str] | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        parsed = urlsplit(upstream_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Distribution probe requires one credential-free HTTP(S) origin")
        if not 0 < timeout_seconds <= 60:
            raise ValueError("Distribution probe timeout must be between 0 and 60 seconds")
        if parsed.scheme == "http" and ssl_context is not None:
            raise ValueError("an SSL context is valid only for an HTTPS origin")
        supplied_headers = dict(headers or {})
        if any(name.lower() in PROBE_HOP_BY_HOP_HEADERS for name in supplied_headers):
            raise ValueError("Distribution probe headers contain a forbidden field")
        supplied_headers.setdefault("Accept", MANIFEST_ACCEPT)
        self._scheme = parsed.scheme
        self._host = parsed.hostname
        self._port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self._timeout = timeout_seconds
        self._headers = supplied_headers
        self._ssl_context = ssl_context or (
            ssl.create_default_context() if parsed.scheme == "https" else None
        )

    def _connection(self) -> http.client.HTTPConnection:
        if self._scheme == "https":
            return http.client.HTTPSConnection(
                self._host,
                self._port,
                timeout=self._timeout,
                context=self._ssl_context,
            )
        return http.client.HTTPConnection(
            self._host, self._port, timeout=self._timeout
        )

    def probe(self, *, repository: str, digest: str) -> ProbeObservation:
        if REPOSITORY_NAME.fullmatch(repository) is None:
            raise ValueError("Distribution probe repository is not canonical")
        if SHA256_DIGEST.fullmatch(digest) is None:
            raise ValueError("Distribution probe digest is not canonical")
        connection = self._connection()
        try:
            connection.request(
                "HEAD",
                f"/v2/{repository}/manifests/{digest}",
                headers=self._headers,
            )
            response = connection.getresponse()
            status = response.status
            if status == 404:
                return ProbeObservation(ManifestPresence.ABSENT, status)
            if status != 200:
                return ProbeObservation(ManifestPresence.INDETERMINATE, status)
            content_digests = [
                value.strip()
                for name, value in response.getheaders()
                if name.lower() == "docker-content-digest"
            ]
            if content_digests == [digest]:
                return ProbeObservation(ManifestPresence.PRESENT, status)
            return ProbeObservation(ManifestPresence.INDETERMINATE, status)
        except (OSError, TimeoutError, http.client.HTTPException):
            return ProbeObservation(ManifestPresence.INDETERMINATE, None)
        finally:
            connection.close()


@dataclass(frozen=True, slots=True)
class ReconciliationRun:
    scanned: int
    present: int
    absent: int
    indeterminate: int
    stale: int
    next_cursor: ReconciliationCursor | None


class QuotaReconciler:
    def __init__(
        self,
        quotas: QuotaStore,
        repositories: RepositoryResolver,
        probe: ManifestProbe,
        *,
        stale_after: timedelta = timedelta(minutes=5),
        batch_limit: int = 100,
    ) -> None:
        if stale_after.total_seconds() < 0:
            raise ValueError("reconciliation stale_after must not be negative")
        if (
            isinstance(batch_limit, bool)
            or not isinstance(batch_limit, int)
            or not 1 <= batch_limit <= MAX_RECONCILIATION_BATCH
        ):
            raise ValueError(
                f"reconciliation batch_limit must be between 1 and {MAX_RECONCILIATION_BATCH}"
            )
        self._quotas = quotas
        self._repositories = repositories
        self._probe = probe
        self._stale_after = stale_after
        self._batch_limit = batch_limit

    def run_once(
        self,
        *,
        now: datetime | None = None,
        after: ReconciliationCursor | None = None,
    ) -> ReconciliationRun:
        observed_at = now or datetime.now(UTC)
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("reconciliation time must be timezone-aware")
        page = self._quotas.list_reconciliation_candidates(
            stale_before=observed_at - self._stale_after,
            limit=self._batch_limit,
            after=after,
        )
        present = 0
        absent = 0
        indeterminate = 0
        stale = 0
        for candidate in page.candidates:
            repository = self._repositories.resolve(
                project_id=candidate.project_id,
                repository_id=candidate.repository_id,
            )
            if repository is None:
                indeterminate += 1
                continue
            observation = self._probe.probe(
                repository=repository, digest=candidate.manifest_digest
            )
            try:
                if observation.presence == ManifestPresence.PRESENT:
                    self._quotas.reconcile_present(
                        candidate.reservation_id,
                        expected_version=candidate.version,
                    )
                    present += 1
                elif observation.presence == ManifestPresence.ABSENT:
                    self._quotas.reconcile_absent(
                        candidate.reservation_id,
                        expected_version=candidate.version,
                    )
                    absent += 1
                else:
                    indeterminate += 1
            except StaleReconciliationCandidate:
                stale += 1
        return ReconciliationRun(
            scanned=len(page.candidates),
            present=present,
            absent=absent,
            indeterminate=indeterminate,
            stale=stale,
            next_cursor=page.next_cursor,
        )
