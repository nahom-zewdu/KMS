# NLP API development

The Python API loads `nlp/.env` explicitly at startup; it does not depend on
`uv run` loading environment files. Start it from the repository root with:

```sh
cd nlp
.venv/bin/python -m uvicorn api:app --host 127.0.0.1 --port 8000 --reload
```

Required server-side variables:

- `SUPABASE_URL` — the active Supabase project URL. The default issuer is
  `${SUPABASE_URL}/auth/v1`, and the default JWKS URL is
  `${SUPABASE_URL}/auth/v1/.well-known/jwks.json`.
- `SUPABASE_KEY` — server-side Supabase database key; never use it as a user
  access token or expose it to the frontend.

Optional user-token verifier settings:

- `SUPABASE_JWT_ISSUER`
- `SUPABASE_JWT_AUDIENCE` (defaults to `authenticated`)
- `SUPABASE_JWKS_URL`

User API requests must carry a Supabase user access token signed with ES256.
The verifier obtains public keys from JWKS and validates the signature,
issuer, audience, required claims, and authenticated role. Do not configure a
service-role JWT or `SUPABASE_JWT_SECRET` as a substitute for user tokens.

Internal service routes use a separate `INTERNAL_SERVICE_SECRET` and optional
`INTERNAL_SERVICE_ISSUER` / `INTERNAL_SERVICE_AUDIENCE` settings. Keep all
internal service credentials server-side; they are not user identities.

To run focused auth and Ramp regression tests:

```sh
.venv/bin/python -m pytest -q tests/test_authz.py tests/test_ramp_v2.py
```

### Optional real SCIP integration test

The default test suite does not require Node.js or external SCIP binaries. To verify
real cross-file Python semantic indexing, install the upstream tools in an isolated
environment with Node.js 16+:

```bash
npm install --global @sourcegraph/scip-python
# Install the matching SCIP CLI using the upstream installation instructions:
# https://github.com/sourcegraph/scip
```

Then run the opt-in integration test:

```bash
KMS_SCIP_PYTHON_INTEGRATION=1 uv run pytest tests/test_scip_indexer.py -q
```

The verified local toolchain was `scip-python 0.6.8` and SCIP CLI `v0.10.0`.
The test creates a two-file Python fixture, indexes it with `scip-python`, decodes
the generated index with `scip print --json`, and checks that the call in
`consumer.py` resolves to the same SCIP symbol as the definition in
`library.py`.

**Verified locally (2026-11-22):** the full NLP suite passed **245 tests**, with
3 opt-in SCIP integrations skipped in the default run, 6 dependency deprecation
warnings, and 4 subtests passed. The real Python, Go, and TypeScript integrations
were each run separately and passed. The occurrence persistence SQL integration
test also passed against the local PostgreSQL 16 test database. See
`docs/development/milestones/2026-11-22-krt-02-code-intelligence.md` for the
milestone close-out and remaining boundaries.

Compatibility note: `scip-python 0.6.8` omits per-document position encoding.
The integration configures an explicit UTF-32 code-point offset override for
this indexer version. The normalizer rejects unspecified encodings by default;
it does not infer an encoding from a file extension.

Do not run indexers against untrusted repository code outside an isolated
worker/sandbox. The current subprocess runner applies time/output bounds but is
not an OS-level security sandbox.
