# Private-Edge Quota PoC

This fixture validates accepted-for-PoC ADR 0009 without modifying
Distribution or buffering blob bodies in Coffer. The edge is the only service
published to the host. Distribution and MinIO remain private on the Compose
network; manifest PUTs pass the bounded admission seam while all other
registry traffic streams through the generic proxy.

Run:

```bash
make -C poc/quota verify
```

The harness generates an ephemeral RSA key and synthetic application
credential under ignored, owner-only `work/quota`, builds the Coffer edge, and
verifies pinned Docker 29.5.3, Podman 5.6.0, and Skopeo 1.20.0 requests. Docker
runs in an ephemeral private Docker-in-Docker service, so the host does not
need an insecure-registry setting. Podman and Skopeo also run as isolated
client containers on the same private network. The generated credential file
is mounted read-only and is not copied into Compose environment metadata.

The test proves concurrent one-winner 201/429 admission, an idempotent 201
retry, project-without-quota 503, Distribution with no host port or port
binding, and logical usage stability while an unpublished blob increases S3
objects. The validated run observed 28 to 30 objects for that final staging
step. SQLite is a local concurrency fixture; the schema and transaction use a
shared SQL boundary, and production promotion requires PostgreSQL/MariaDB
migrations, a reconciliation worker, and multi-replica evidence.

The outer Compose command can use Docker Desktop or another compatible Docker
API. When using an existing Podman machine, export its API socket as
`DOCKER_HOST` before running `make`; the fixture itself still performs the
three client proofs inside the private network. Cleanup removes its containers,
volumes, client auth state, private key, generated JWKS, and application
credential values even when a check fails.
