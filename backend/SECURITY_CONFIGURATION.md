# Backend security configuration

The backend fails startup when required security configuration is missing or unsafe. Store all secrets in the deployment platform's environment configuration, never in Git.

## Required variables

- `JWT_SECRET` is mandatory. It must be at least 32 characters and must not be a known/default value such as `dev_secret`, `secret`, `changeme`, or `default`.
- `MONGO_URL` and `DB_NAME` are mandatory and must identify the intended MongoDB deployment and database. Never point tests at production or a shared developer database.
- `CORS_ORIGINS` is a comma-separated allowlist of complete HTTP(S) origins, for example `https://control.example.com,https://admin.example.com:8443`. Wildcards, credentials, paths, queries, fragments, malformed hostnames, and malformed ports are forbidden. Localhost is not added automatically; development origins such as `http://localhost:3000` must be explicit. An empty value produces an empty allowlist.

## Seed controls

- `ALLOW_SEED_ENDPOINT` defaults to `false` and must be explicitly set to `true` before the endpoint is usable.
- Every seed request requires an authenticated `owner`; `admin` is not sufficient.
- Forced seed is available only when normalized `APP_ENV` is exactly `local`, `development`, `dev`, or `test`.
- Production, staging, blank, unknown, and misspelled `APP_ENV` values deny forced seed.

## Railway and Emergent deployment

Configure `JWT_SECRET`, `MONGO_URL`, `DB_NAME`, `CORS_ORIGINS`, `APP_ENV`, and `ALLOW_SEED_ENDPOINT` in the Railway or Emergent environment-variable settings. Do not place real values in repository files, build logs, screenshots, or support messages. Production deployments should leave `ALLOW_SEED_ENDPOINT=false`.

Invalid JWT or CORS configuration intentionally prevents startup. This is fail-closed behavior and should be corrected in deployment configuration rather than bypassed in code.
