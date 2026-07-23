# Synthetic Inventory Scale Characterization

This disposable harness measures the current Coffer inventory pipeline without
production data, credentials, registry endpoints, or admission changes. It
generates a deterministic `coffer.inventory/v1` artifact, migrates a temporary
SQLite database, creates matching repository/quota authority, imports the empty
ledger baseline, runs the exact SQL comparison, and invokes the live-comparison
core through an injected always-present synthetic authenticated probe.

Run all fixed profiles from the repository root:

```bash
make -C poc/inventory_scale verify
```

Run one profile:

```bash
uv run python poc/inventory_scale/measure.py --profile manifest-1000
```

## Profiles

| Name | Projects | Repositories | Manifests | Unique descriptors |
|---|---:|---:|---:|---:|
| `manifest-100` | 2 | 10 | 100 | 300 |
| `manifest-1000` | 5 | 50 | 1,000 | 3,000 |
| `manifest-5000` | 10 | 200 | 5,000 | 15,000 |

Each synthetic image manifest references one unique config and one unique layer.
There is deliberately no cross-manifest descriptor sharing or nested index in
this first scale pass. The topology makes expected ledger and probe counts
linear and repeatable; it is not a model of customer content distribution.

## Output Contract

The command emits one compact JSON document with:

- aggregate profile and artifact-byte counts;
- monotonic duration, peak CPython `tracemalloc` bytes, and SQL statement count
  for each phase;
- exact aggregate SQL/live status and probe count; and
- no project UUID, repository UUID/name, content digest, URL, header, token, or
  credential.

`live_compare` includes the exact SQL snapshot that the production core always
performs before its synthetic probes. `sql_compare` is measured separately so
that this repeated cost is explicit. Timings are observations, not assertions;
host load, CPython allocation tracing, local filesystem caching, and SQLite all
affect them.

## Interpretation Boundary

These results can reveal current algorithmic, statement, and Python-allocation
growth. They do not qualify PostgreSQL, MariaDB/Galera, RGW, Distribution, TLS,
authentication exchange, credential fan-out, registry latency/rate limits,
all-replica consistency, writer exclusion, backup/rollback, or a production
capacity/SLO. Any batching, concurrency, retry, timeout, or tuning change needs a
separate correctness-preserving decision after a measured bottleneck.

The temporary database directory is removed after each profile. A fixed error is
printed on failure; detailed tenant/content/credential data is never part of the
output contract.

## Observed Local Baseline

One Python 3.13 run on the local Apple Silicon development host on 2026-07-23
produced the following observations with `tracemalloc` enabled:

| Manifests | Artifact bytes | Import seconds / SQL statements / peak bytes | Exact SQL seconds / statements / peak bytes | Live-core seconds / probes / peak bytes |
|---:|---:|---:|---:|---:|
| 100 | 95,480 | 0.082 / 316 / 473,469 | 0.046 / 11 / 645,685 | 0.040 / 100 / 510,421 |
| 1,000 | 944,053 | 0.728 / 3,022 / 1,198,310 | 0.417 / 11 / 4,887,407 | 0.387 / 1,000 / 4,803,340 |
| 5,000 | 4,711,096 | 3.642 / 15,032 / 3,998,543 | 2.085 / 11 / 24,867,168 | 1.968 / 5,000 / 24,779,971 |

Within this bounded range, artifact bytes, phase duration, and peak traced Python
allocation grew approximately linearly. Import issued `3 * manifests + 2 *
projects + 12` statements because reservation and manifest writes remain
per-manifest. Exact comparison retained 11 statements but materialized larger
result sets in Python. The live core also issued 11 SQL statements and exactly
one probe per manifest; its synthetic in-process probe adds no realistic TLS,
authentication, or network delay.

No nonlinear break was observed through 5,000 manifests. That is useful local
algorithm evidence only: the largest artifact is still far below the 64-MiB
loader ceiling, the unique-descriptor topology omits sharing/indexes, and serial
remote probes can dominate once real latency exists. A future provider fixture
must measure authenticated private-TLS latency and failure behavior before any
concurrency or timeout policy is selected.
