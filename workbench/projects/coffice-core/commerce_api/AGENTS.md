# Independent commerce API project

- All changes and runtime files for this project stay inside `commerce_api/`.
- Do not edit the existing DOM downloads, ReverseAPI scripts, workbench, database,
  schedules, credentials, production downloads, locks, or checkpoints to implement
  this CLI. Existing shared locks may be acquired and released for coordination.
- One CLI entry point; platform folders contain API and service implementations.
- Production business requests use independent HTTP. Browser/CDP is restricted to
  explicit authentication, confirmed authentication recovery, and development-only
  request discovery. Never silently fall back to browser fetch or DOM downloads.
- Reuse existing login, Challenge, group-reply, notification and profile resolution
  through the legacy integration adapters; do not rewrite their policies.
- Runtime state, captures, test downloads and encrypted credentials belong to
  `.runtime/`, which must remain Git-ignored. Never log secrets, signed URLs, SMS
  answers, passwords, full responses or CDP endpoints.
- Read the parent `.env` only for existing integration configuration. Never persist
  Windows environment settings or change the parent's Python dependencies.
- Use the explicitly selected Python interpreter and `-B -m` for execution.
- Tests use isolated temporary stores, mocked services and fictional fixtures.
  Remove test state and services after testing. Keep production data intact.
- Video-channel downloads and product mutations are outside the current scope.
