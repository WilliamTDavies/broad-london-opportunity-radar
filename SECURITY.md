# Security policy

Report vulnerabilities privately through GitHub’s **Report a vulnerability** feature. Do not open a public issue containing a live token, subscriber address or exploit detail.

Secrets belong in GitHub Actions secrets or Supabase Edge Function secrets. Never put a service-role key in browser JavaScript, Pages output, repository variables, logs or test fixtures. `.env` is ignored; `.env.example` contains names only.

Public adapters access only unauthenticated endpoints, honour robots directives, use bounded concurrency/timeouts and do not bypass CAPTCHAs or access controls. Retrieved descriptions are untrusted: models validate them and HTML/email renderers escape them.

Supabase RLS is enabled and anon/authenticated table privileges are revoked. Edge Functions use restricted CORS, input length/format validation, HMAC-hashed random tokens, expiring confirmation, honeypot and database-backed rate limiting. Generic subscribe responses prevent subscriber enumeration. Confirmation and unsubscribe are idempotent.

Dependencies are version-pinned and CI runs Ruff, mypy, pytest, JavaScript behaviour tests, configuration/state/workflow validation, a fixture end-to-end scan and repository secret/subscriber-data checks. The built-in scanner recognises common private-key, GitHub-token, AWS-key, Resend-key and JWT patterns; a hosting organisation may add a dedicated history-aware scanner for defence in depth. Update dependencies in small reviewed changes and retain adapter fixtures. If a credential is exposed, revoke it first, remove it from all history, then investigate logs and rotate related tokens.
