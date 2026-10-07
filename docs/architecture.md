# Architecture and readiness

## Current product shape

The project extends the existing FastAPI, SQLAlchemy, LangGraph, React, and Vite application; it is not a replacement implementation.

```text
React dashboard
    │ /api (Vite proxy or Nginx)
FastAPI routers ── role policy ── SQLAlchemy models
    ├── job intake / JD approvals
    ├── resume parsing / explainable ranking / recruiter review
    ├── shortlist / interview / feedback / hiring approval / offer / onboarding
    ├── candidate search / rediscovery / duplicate signals / copilot retrieval
    └── audit trail / funnel and source analytics
          │
          ├── SQLite local demo or PostgreSQL deployment
          ├── deterministic offline templates and matching
          └── optional OpenAI-compatible text generation
```

## Recruitment lifecycle

1. A recruiter creates a requisition or submits natural-language requirements; the deterministic parser is always available.
2. The agent drafts a job description and requests approval before publishing.
3. Resumes are imported and parsed. Matching uses role skills, experience fit, and lexical text relevance; configurable weights and component contributions are returned for review.
4. A recruiter searches/filters candidates, inspects the profile timeline, and may request cross-job talent rediscovery. Potential duplicate profiles are flagged, not merged.
5. Shortlists, interview invitations, final hiring decisions, offers, and onboarding remain explicit human-approved steps. Interview availability checks detect overlapping proposed/scheduled events at confirmation and reschedule time.
6. Feedback, application source, funnel transitions, human overrides, pending actions, and time-to-hire indicators feed the dashboard.

The candidate table currently models an **application/profile per job**, not a canonical person with many applications. Duplicate detection is an advisory signal. `Setting.pipeline_stages` stores configurable stage order, labels, and colors; built-in workflow keys remain present for compatibility.

## AI and responsible use

- Deterministic screening uses required/preferred skills, experience, and text relevance; protected attributes are not intended as ranking features.
- AI-generated text is optional. Offline templates permit a no-credentials demo.
- Candidate summaries sent to an external LLM contain structured non-identifying evidence; raw resumes, email addresses, and names are excluded from that prompt.
- Screening audit entries carry prompt version/model identity and duplicate signals. Recruiter copilot retrieval includes source record IDs and a responsible-use policy; retrieval is lexical over current database records, not a vector store.
- Low-confidence profiles and proposed actions use approval records. AI does not automatically make a final hire/reject decision.

## Integrations and operational boundary

The current `CalendarConnector` is a local database simulator; it does not connect to Google Calendar or create Meet links. `EmailConnector` sends via configured SMTP or leaves messages queued in the local outbox. Google OAuth consent/state handling, encrypted refresh-token persistence, Calendar/Gmail API clients, webhook subscriptions, and vendor integration tests are not present.

The current demo identity is the `X-User-Id` header with a selectable local user. `DEMO_MODE=false` makes protected operations fail closed; it does not provide an authentication system. Organization/tenant isolation, external SSO, API-key issuance/rotation, distributed rate limiting, background workers, durable retry queues, and retention/consent workflows remain prerequisites to production.

## Database lifecycle

- SQLAlchemy models define the baseline relational schema and indexes for common candidate, job, approval, interview, offer, and audit queries.
- Alembic is configured under `backend/migrations`. Fresh databases use `alembic upgrade head`.
- Local demo startup can create tables automatically. Production should turn `AUTO_CREATE_SCHEMA` off and run migrations as a deployment step.
- For the pre-Alembic prototype database, take a backup and verify schema compatibility before `alembic stamp head`. Stamping does not migrate an existing database.
- `python -m scripts.seed_demo --jobs 100 --candidates 1000` builds an isolated, deterministic synthetic SQLite data set. The command refuses to append to an initialized unmarked database; `--reset` is intentionally destructive to the selected SQLite file.

## Competitive positioning

This is a demo-stage product, not a feature-equivalent ATS. Its current practical differentiators are:

| Capability | Current implementation | Positioning |
|---|---|---|
| Explainable ranking | Skill/experience/text components and explicit weights; source IDs in recommendations | Inspectable signals rather than opaque ranking claims |
| Human checkpoints | Approval records around high-impact workflow actions | Human decision ownership stays visible |
| Talent rediscovery | Local cross-job profile reranking with skill-gap evidence | Internal-profile reuse without claiming an external sourcing network |
| Reproducible demo | Offline AI fallback and seeded synthetic pipeline records | No provider credentials or real candidate data required |
| Workflow visibility | Candidate stage board, profile event history, sourcing and funnel metrics | Connects matching recommendations to approvals, interviews, and outcomes |

LinkedIn Recruiter has a proprietary sourcing network; established ATS products provide mature integrations and operational workflows; analytics-focused platforms offer broad reporting. This project does not yet provide those integrations, large-scale operational guarantees, or validated hiring-quality outcomes. A responsible comparison requires a separately scoped evaluation against current vendor editions and customer requirements.

## Deployment checklist (not yet production-ready)

1. Implement and test OIDC/SSO, tenant scoping, per-tenant roles, audit-safe authorization, and account lifecycle.
2. Complete Google OAuth and calendar/mail API integration, including secret encryption, revocation/refresh, event idempotency, push verification, timezone handling, and mocked integration tests.
3. Add canonical candidate identity/application records, consent and retention controls, and migration/backfill strategy.
4. Add a durable worker/queue, retry policy, outbox state transitions, idempotency keys, and dead-letter monitoring.
5. Configure managed PostgreSQL, TLS, secret manager, deployment-time Alembic migration, backup/restore validation, rate limiting, observability, and load/security tests.
6. Validate matching and fairness with representative, legally approved evaluation data and independent human oversight before use in hiring.
