# Security

## Supported posture

This evaluation prototype reads two explicitly configured monday boards and produces answers/drafts. It implements monday GraphQL queries only: no mutations, send actions, or background writes. The browser talks to a server-side Next.js proxy, so `BACKEND_URL`, monday credentials, and LLM credentials stay server-side.

## Operator responsibilities

- Use a dedicated monday identity limited to the two evaluation boards, or an app token with `boards:read` only.
- Store secrets in ignored `backend/.env` locally and hosting secret stores in production. Never prefix them with `NEXT_PUBLIC_`.
- Restrict `CORS_ALLOW_ORIGINS` to exact trusted frontend origins and add authentication before exposing sensitive business data beyond a controlled evaluation.
- Rotate any credential that appears in logs, screenshots, commits, or chat; remove the affected history before publication.
- Review leadership drafts and data-quality caveats before copying or publishing them.

Raw board rows and prompts are not intentionally logged. Checkpoints retain only bounded analytical/session context and use UUIDv4 IDs. Provider/upstream errors are sanitized before reaching SSE. A shared durable checkpointer, identity-aware authorization, audit logging with redaction, and centralized observability are recommended before multi-user production use.

## Reporting

Do not open a public issue containing credentials or customer data. Report a vulnerability privately to the repository/deployment owner with reproduction steps and sanitized evidence. No public security contact is configured yet.
