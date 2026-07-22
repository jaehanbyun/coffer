# M2 Authenticated Distribution Fixture

This fixture proves the Coffer-issued Distribution JWT contract without pretending to be a real Keystone acceptance environment.

It generates an ephemeral RSA key and synthetic application credential under ignored `work/m2/`, starts the Coffer token realm on IPv4 loopback, advertises it to Docker Desktop through `host.docker.internal`, starts the pinned M0 Distribution/MinIO images on port 5001, and exercises Docker's unmodified challenge/login/push/pull path. The synthetic authenticator is isolated to this fixture and must never be used in a deployment.

Run:

```bash
make -C poc/m2 verify
```

The verification asserts:

- the registry advertises the expected realm and service;
- Docker Basic login succeeds, and a separate live `offline_token=true` request obtains only a short-lived RS256 token through Coffer with no refresh token;
- a `member` principal can push and pull its project repository but cannot delete;
- a `reader` principal can pull but cannot push;
- a live layer is downloaded after registry restart and its SHA-256 matches the manifest digest, independently of Docker's local cache;
- a cross-project push is denied;
- an unregistered same-project repository receives no grant and is denied;
- a same-project blob mount succeeds, while an existing cross-project blob and a nonexistent blob both receive the same 401 denial and remain absent from the target repository;
- an invalid fixture secret returns 401 and an unknown service returns 400;
- expired, not-yet-valid, altered-signature, wrong-algorithm, wrong-audience, and wrong-issuer tokens all receive 401 from Distribution;
- Distribution accepts a valid token signed by the second `kid` in an overlapping two-key JWKS;
- the token-service log contains correlated decision records, while captured token-service, registry, and denial logs contain neither a fixture secret nor a full bearer token.

The synthetic realm uses the production explicit-repository and `oslo.policy` authorizer against a disposable SQLite control database. The script removes both generated private keys, the environment file, control database, downloaded blob, Docker credential directory, and fixture volume on exit. It retains only public JWKS and redacted logs under ignored `work/m2/` for diagnosis. The two-key check proves overlapping verification metadata, not live key reload or a no-downtime production rotation procedure. Plain HTTP, MinIO, synthetic identity, and the v3.1.1 image are local-test constraints, not production evidence.
