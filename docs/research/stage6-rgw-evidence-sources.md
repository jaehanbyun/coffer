# Stage 6 RGW, KMS, and Multipart Evidence Sources

- Date: 2026-07-26
- Status: source mapping, no-network collector core, verified-HTTPS live
  adapter, qualified disposable-pilot schedule, and fixture checkpoint
  executor plus exact-prefix cleanup, RGW, and external fault action contracts
  implemented; phase materializers and live pilot qualification pending
- Scope: the RGW auxiliary payload consumed by
  `poc/load-soak/collector/phase_evidence.py`
- External operations: read-only inspection of exact released upstream source
  and current Coffer source; no RGW, S3, Barbican, Distribution, load, or
  remote endpoint was contacted

## Outcome

The existing native RGW surface proves daemon identity, admin-socket
collection, and ingress health. It does not prove the three auxiliary fields:

- `kms_errors`;
- `multipart_uploads`; and
- `unexpected_errors`.

Only `multipart_uploads` has a complete direct source today: a paginated S3
`ListMultipartUploads` request against the exact Coffer bucket. Ceph's API
defines that operation as the list of current in-progress uploads, and its
authorization mapping grants `s3:ListBucketMultipartUploads` with bucket
`READ`. The final artifact needs only the total count and page-response hashes;
object keys and upload IDs must remain inside an owner-only disposable raw
capture.

Neither released Ceph v20.2.2 nor Distribution v3.1.1 exposes a KMS-attributed
error counter:

- Ceph v20.2.2 has a global `failed_req` counter described as aborted
  requests. The same counter is incremented from the generic request abort
  path, and the RGW performance-counter schema contains no KMS counter.
- Distribution v3.1.1 exposes a storage action timer labeled only by driver
  and action. The wrapper updates that timer after both successful and failed
  calls, without an outcome or error-class label.
- Barbican health checks report service/backend health. Barbican documents
  that detailed health may expose sensitive service information; a healthy
  Barbican endpoint still does not prove that RGW retrieved and used the
  selected key for an S3 operation.

The missing error boundary must therefore be supplied by one bounded,
phase-local RGW/SSE-KMS probe result. The probe executes only fixed S3
operations against the exact pilot bucket, classifies results against the
declared fault window, and records safe aggregate outcome classes. The
collector combines that canonical result with the direct multipart listing; it
must not infer zero from missing observations.

## Exact Source Map

| Artifact field | Accepted source | Disposition |
|---|---|---|
| `kms_errors` | Canonical nonsynthetic RGW/SSE-KMS probe result for the exact phase and window | Count only unexpected KMS-class outcomes. A fail-closed wrong-key or declared Barbican outage is an expected injected result and must be observed and bound, but does not increment this promotion field. A missing positive-path probe, an unclassified KMS response, or a result outside the declared window refuses collection. |
| `multipart_uploads` | Complete paginated S3 `ListMultipartUploads` result for the exact Coffer bucket | Direct point-in-time count. Preserve page count and hashes in the owner-only capture. Strip bucket, key, upload ID, endpoint, and credential material from the final artifact. `after` must be zero; the independent telemetry gate permits a nonzero `during` value. |
| `unexpected_errors` | The same canonical probe result, reduced to unexpected non-KMS RGW/S3/storage outcomes | Count only probe operations that terminated in an unapproved status or error class. Do not reuse HAProxy workload errors, Ceph's global `failed_req`, or Distribution's action count. Those are independent surfaces with different request populations. |

The existing `coffer.load-profile-result/v1` and
`coffer.load-fault-result/v1` remain the end-client workload authorities.
Their `unexpected_errors` field is already compiled into the HAProxy auxiliary
surface. Copying it into RGW would duplicate one event and would still not
show which storage/KMS operation failed.

## Canonical Probe Contract

`rgw_artifacts.py` accepts one owner-only canonical
`coffer.load-rgw-probe-result/v1` document for each phase. A later disposable
pilot adapter will produce it from verified-TLS S3 calls; local tests use an
explicit fake adapter. The canonical result must bind:

- `execution_source="pilot"` and `synthetic=false`;
- the exact phase, phase-window hash, native-target hash, probe source hash,
  and immutable RGW configuration hash;
- an exact bucket-scope hash and selected KMS-policy hash without retaining
  either underlying identifier;
- probe start/completion times contained by the phase window;
- fixed operation classes only: `put_zero`, `put_positive`, `head`, `get`,
  `copy_zero`, `copy_positive`, and `list_multipart`;
- fixed result classes only:
  `success`, `expected_wrong_key`, `expected_kms_outage`,
  `unexpected_kms_error`, and `unexpected_storage_error`;
- required-operation counts, expected injected-result counts, unexpected KMS
  count, unexpected non-KMS count, and one canonical event-set hash; and
- no exception text, HTTP body, URL, bucket, object key, upload ID, access
  key, secret key, Barbican secret/key ID, token, certificate, or request
  header.

Every configured positive-path operation must be observed exactly once or at
its bounded declared repetition count. An injected wrong-key/outage window
must identify the exact expected result class and expected count in the
phase-bound probe configuration. A declared fault that was not observed,
an expected fault outside its window, an unknown operation/result, a duplicate
event, or an omitted operation is a collection failure rather than a zero.

The current telemetry schema requires `kms_errors == 0` in all three phases.
Within this contract the field means unexpected KMS errors, not the number of
expected fail-closed responses deliberately injected during recovery testing.
The expected injected result counts remain bound in the raw/canonical probe
hashes so a collector cannot hide a fault that never ran.

## Multipart Acquisition Contract

The live adapter must:

1. read endpoint, bucket, CA file, access key, and secret key only from
   owner-only runtime inputs;
2. require verified HTTPS, explicit path-style/v4 configuration, finite
   connect/read timeouts, and no ambient credential fallback;
3. call only `ListMultipartUploads` for the exact selected bucket;
4. follow every continuation marker until `IsTruncated` is false, while
   enforcing bounded pages and uploads;
5. reject repeated markers, malformed pages, response bucket drift, or an
   incomplete listing;
6. reduce each page to upload count and canonical page hash before retention;
   and
7. emit only count, page count, observation time, configuration/bucket hashes,
   and a canonical capture hash.

The S3 credential is a dedicated read-only evidence identity whose bucket
policy permits the minimum multipart-list operation. It is not the
Distribution writer credential and must not be placed in the target, result,
plan, logs, process arguments, or retained artifact. Credential provisioning,
delivery, rotation, and teardown remain part of the disposable pilot.

Ceph documents `GET /{bucket}?uploads` as returning current in-progress
uploads and supports continuation markers with a maximum page size of 1,000.
The current Barbican fixture already demonstrates boto3 pagination, but its
fixed lab constants and retained key/upload identities make it an
implementation reference only, not production evidence.

## Counter and Health Boundaries

The generic Ceph `failed_req` delta may remain a diagnostic alongside the
owner-only raw capture, but it cannot populate either error field:

- it includes request classes unrelated to Coffer and KMS;
- it cannot distinguish an expected injected failure from an unexpected
  failure;
- it cannot map Distribution's multiple S3 calls back to one client
  operation; and
- its process-local lifetime makes a reset/restart indistinguishable from a
  clean phase without additional binding.

Likewise, `ceph_daemon_socket_up`, RGW ingress health, Barbican health,
Distribution process health, and Ceph mgr scrape health prove reachability or
collection freshness only. None is an error count. The existing native parser
continues to own daemon and ingress availability; the new artifact does not
duplicate or replace those checks.

Distribution's `registry_storage_action_*` metric is useful for action volume
and latency. It cannot count storage errors because v3.1.1 labels only the
driver and action and updates the timer regardless of the returned error.
Adding an inferred `result` label in Coffer without instrumenting the exact
upstream error boundary would fabricate precision and is rejected.

## Final Artifact Contract

`rgw_artifacts.py` must:

1. validate the exact native target, topology, phase, window, source hashes,
   and owner-only canonical inputs;
2. validate a complete phase-bound probe result;
3. acquire or validate one complete point-in-time multipart capture;
4. require the probe configuration hash and multipart configuration hash to
   describe the same selected RGW target and bucket scope;
5. reduce unexpected KMS and non-KMS outcomes without counting declared
   expected failure injections;
6. emit one `coffer.load-telemetry-source-artifact/v2` document with source
   class `rgw-load-state-aggregate` and exactly the three nonnegative integer
   fields; and
7. retain only source/target/window/configuration/canonical-input hashes,
   observation bounds, and the normalized payload.

Raw probe and multipart captures remain mode 0600 beneath an owner-only
directory and are disposable after the signed phase bundle is compiled.
Final artifacts must not retain host, daemon, URL, project, bucket, repository,
object, key, upload, identity, credential, certificate, KMS, or request
identifiers.

## Rejected Shortcuts

| Shortcut | Reason rejected |
|---|---|
| Set all three fields to fixture lifecycle defaults | Desired fixture state is not observed pilot state |
| Use Ceph `failed_req` as `kms_errors` | The counter is generic and has no KMS attribution |
| Use Ceph `failed_req` as `unexpected_errors` | The request population includes expected and unrelated failures |
| Use Distribution storage action count or latency as an error count | v3.1.1 has no result/error label |
| Treat RGW, Distribution, or Barbican health as zero errors | Reachability does not execute the SSE-KMS data path |
| Reuse HAProxy workload `unexpected_errors` | Duplicates a separate client-facing surface and loses storage attribution |
| Count declared wrong-key/outage responses as promotion errors | They are required fail-closed evidence; failure to observe the declared response is the error |
| Accept the old Barbican fixture listing as live evidence | It uses fixed lab constants and retains object/upload identities |
| Sample only the first multipart page | Can report false zero or an incomplete count |
| Retain key or upload IDs to prove uniqueness | Expands the sensitive content boundary without improving the aggregate gate |

## Primary Sources

- [Ceph Tentacle v20.2.2 RGW performance-counter
  schema](https://github.com/ceph/ceph/blob/v20.2.2/src/rgw/rgw_perf_counters.h)
  and [counter
  definitions](https://github.com/ceph/ceph/blob/v20.2.2/src/rgw/rgw_perf_counters.cc)
- [Ceph RGW metric collection and restart
  behavior](https://docs.ceph.com/en/latest/radosgw/metrics/)
- [Ceph List Bucket Multipart Uploads
  operation](https://docs.ceph.com/en/latest/radosgw/s3/bucketops/#list-bucket-multipart-uploads)
  and [S3 authorization
  mapping](https://docs.ceph.com/en/latest/radosgw/s3/authentication/)
- [Distribution v3.1.1 storage metric
  namespace](https://github.com/distribution/distribution/blob/v3.1.1/metrics/prometheus.go)
  and [storage action
  instrumentation](https://github.com/distribution/distribution/blob/v3.1.1/registry/storage/driver/base/base.go)
- [Distribution Prometheus configuration
  contract](https://distribution.github.io/distribution/about/configuration/#prometheus)
- [Barbican health-check configuration and sensitive-detail
  warning](https://docs.openstack.org/barbican/latest/configuration/config.html)

## Implemented Collector Boundary

`poc/load-soak/collector/rgw_artifacts.py` now:

1. validates the exact target, phase window, RGW/bucket/KMS configuration,
   source hashes, required operations, and declared fault counts;
2. refuses synthetic, incomplete, out-of-window, cross-target, unknown,
   missing-operation, or missing-expected-fault probe results;
3. validates complete, bounded, unique-page multipart captures without
   accepting configured or fixture defaults;
4. reduces only `unexpected_kms_error` to `kms_errors`, expected wrong-key and
   outage outcomes to zero promotion errors, and unexpected non-KMS outcomes
   to `unexpected_errors`;
5. emits one retainable `coffer.load-telemetry-source-artifact/v2` with the
   existing `rgw-load-state-aggregate` source class; and
6. enforces canonical mode-0600, single-link, distinct inputs and atomic,
   idempotent mode-0600 output with fixed secret-safe CLI failures.

Thirty-six focused fake-adapter tests cover every phase, declared fault
semantics, nonzero failure retention, operation/result completeness, phase
time bounds, multipart completion/pages, target/config/source drift,
owner-only files, aliases, idempotence, retention, and CLI behavior. No live
S3 client, credential, endpoint, RGW, KMS, Barbican, container, VM, or remote
state is used.

## Exact Next Action

Implement and locally prove the bounded concrete fault command controller
required by the completed 53-action adapter. Use fixed owner-only executable
descriptors, no shell expansion, a minimal environment, bounded process-group
termination, and canonical self-hashed observations. Keep remote invocation
disabled while the selected released Distribution/Ceph inputs remain
unqualified.
