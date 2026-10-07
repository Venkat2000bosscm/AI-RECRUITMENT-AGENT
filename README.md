# AI-Powered Recruitment Assistance Agent

A human-in-the-loop AI agent that supports HR teams across the recruitment lifecycle — from hiring requirement to onboarding — while keeping people accountable for every high-impact decision.

```
Hiring Goal → Planning → Reasoning → Tool Usage → Execution → Monitoring → Adaptation → Human Approval → Completion
```

## Features

| Area | What the agent does | Human control |
|---|---|---|
| Requirement intake | Turns a natural-language hiring request into structured criteria (skills, experience, budget, location, work mode). Rejects protected-attribute criteria. | HR reviews/edits before creating the requisition |
| Job descriptions | Generates a JD (LLM or offline template) | **Approval required** before publishing to channels |
| Application monitoring | Tracks volume; when applications are low it proposes a sourcing strategy (more channels, relaxed preferred skills) | **Approval required** before strategy changes |
| Resume screening | Parses PDF/DOCX/TXT, redacts personal attributes, scores against the JD and classifies as **Strong / Partial / Weak / Human Review** with explainable breakdown, matched skills, gaps and flags | Low-confidence profiles routed to HR; HR can override any signal |
| Shortlisting | Proposes a shortlist from strong/partial matches | **Approval required**; HR can edit the list |
| Interviews | Matches interviewers by expertise, finds free calendar slots, generates questions + checklist, summarises feedback | **Approval required** before sending invitations |
| Hiring decision | Summarises feedback and recommends | **Hiring manager/admin must decide** |
| Offers | Drafts offer from approved template, warns if outside budget | **Hiring manager/admin approval** before sending |
| Onboarding | Generates onboarding tasks after acceptance | **Approval required** before initiating |
| Governance | RBAC (recruiter / hiring manager / admin / viewer), full audit log, global & per-job agent pause, email outbox | — |
| KPIs | Screening volume, human-review rate, override rate, time-to-shortlist, funnel, AI calls & estimated LLM cost | — |
| Recruiter workspace | Candidate search and filters, configurable pipeline stages, profile event timeline, source-level funnel analytics | Recruiter reviews evidence and controls stage changes |
| Talent rediscovery | Reranks previously imported profiles against an open role with skill, experience, text-relevance and confidence explanations | Results are recommendations; no candidate is moved automatically |
| Recruiter copilot | Retrieves role-related job/candidate evidence and cites record IDs; offline answers work without an LLM key | Human verifies source records before acting |

## Architecture

```
frontend/  React + Vite dashboard (requisitions, candidates, approvals, interviews, offers, audit)
backend/
  app/agent/workflow.py      LangGraph agent: plan → tool → monitor → (adapt | approval checkpoint | finish)
  app/services/decision.py   Fast decision layer: matching, classification, confidence, sourcing strategy
  app/services/llm.py        Main LLM (any OpenAI-compatible API) with deterministic offline fallback
  app/services/parsing.py    Resume / requirement parsing (PDF, DOCX, TXT)
  app/services/guardrails.py RBAC policy, protected-attribute redaction & criteria checks
  app/services/integrations.py  Job board / email / calendar connectors (local implementations, swappable)
  app/services/recruitment.py   Workflow operations + approval execution + audit
  app/routers/               REST API (/api/...)
```

The agent never executes a high-impact action directly: it creates an `Approval` with rationale and proposed actions, then stops. When a human approves (optionally with overrides), the action executes and the agent continues.

See [docs/architecture.md](./docs/architecture.md) for data flow, integrations, migration workflow, competitive positioning, and known production gaps.

## Quick start (local)

```bash
# Backend (Python 3.10+)
cd backend
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000     # seeds demo data into SQLite on first start

# Frontend (Node 18+)
cd frontend
npm install
npm run dev                                   # http://localhost:5173
```

Use the **Signed in as** selector in the sidebar to switch between demo users (Recruiter, Hiring Manager, Admin, Viewer). Open *Senior Python Backend Engineer* and click **Run agent** to screen the sample resumes and walk through the approval flow.

API docs: http://localhost:8000/docs

### Larger synthetic demo

The normal local quick start seeds the small built-in sample. To create an isolated, repeatable demonstration with **100 jobs and 1,000 synthetic applications**:

```bash
cd backend
python -m scripts.seed_demo --jobs 100 --candidates 1000
```

This creates `backend/demo.db` by default. It does not overwrite a populated database; pass `--reset` only when you intend to delete and recreate that dedicated SQLite demo database. Seeding is deterministic, uses `.example.test` synthetic contacts, and never calls an external model, SMTP server, Google service, or job board. Start the app against that same database:

```powershell
# From the backend directory
$env:DATABASE_URL = "sqlite:///./demo.db"
$env:SEED_DEMO_DATA = "false"
uvicorn app.main:app --reload --port 8000
```

The demo dataset includes interview schedules/feedback, offers, source channels, recruiter activity, rejection reasons, and controlled duplicate, incomplete-resume, conflicting-experience, invalid-email, and workflow-status edge cases.

## Docker (PostgreSQL)

```bash
cp .env.example .env      # replace POSTGRES_PASSWORD with a long random URL-safe secret
docker compose up --build # UI http://localhost:8080, API http://localhost:8000
```

## Configuration

See `.env.example`. Without `OPENAI_API_KEY` everything runs on offline templates and the deterministic decision layer. Set `OPENAI_BASE_URL`/`OPENAI_MODEL` to use any OpenAI-compatible provider (Azure OpenAI, local vLLM/Ollama, etc.). Screening thresholds (`STRONG_MATCH_THRESHOLD`, `PARTIAL_MATCH_THRESHOLD`, `MIN_CONFIDENCE`) are configurable.

Scoring weights are configurable with `SCORE_WEIGHT_REQUIRED_SKILLS`, `SCORE_WEIGHT_PREFERRED_SKILLS`, `SCORE_WEIGHT_EXPERIENCE`, and `SCORE_WEIGHT_TEXT_RELEVANCE`; active weights are normalized and recorded with each explanation. `DEMO_MODE=true` deliberately enables the selectable demo identities and is **not authentication**. Setting `DEMO_MODE=false` also requires `SEED_DEMO_DATA=false` and `AUTO_CREATE_SCHEMA=false`; protected endpoints fail closed until a real identity provider is integrated.

## Tests

```bash
cd backend
python -m pytest
ruff check app scripts tests migrations
alembic upgrade head

cd ../frontend
npm ci
npm run build
```

GitHub Actions runs backend tests/lint and the frontend production build on pushes and pull requests.

## Database migrations

Fresh production databases are created with Alembic:

```bash
cd backend
alembic upgrade head
```

For an existing prototype database, back it up and verify its schema before marking the baseline:

```bash
cd backend
alembic stamp head
```

`alembic stamp` records a revision without changing the schema; use it only if the database already matches the checked-in models. Demo mode keeps `AUTO_CREATE_SCHEMA=true` for a frictionless local start. Production deployments should set `AUTO_CREATE_SCHEMA=false`, `SEED_DEMO_DATA=false`, and provide the database URL through deployment secrets.

## Production notes

- `X-User-Id` is demo-only. A real OIDC/SSO adapter, tenant-scoped authorization, API-key lifecycle, and organization isolation are not implemented. Do not expose this build to real candidate data or disable demo mode as a substitute for authentication.
- Swap local connectors in `integrations.py` for approved ATS, job-board, calendar (Google/Microsoft) and email providers.
- Google Calendar, Meet, and Gmail OAuth are not implemented; the current calendar is an in-database availability simulator and the email connector supports SMTP or an in-app outbox. There is no Google token storage/webhook handling.
- Configure data retention, encryption at rest, access reviews, HTTPS, production secrets, distributed rate limiting, observability, backups, and a durable background queue with retries/idempotency before production traffic.
- AI outputs are decision support only — final hiring decisions remain with authorised people.
