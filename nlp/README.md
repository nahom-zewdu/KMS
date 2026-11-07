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