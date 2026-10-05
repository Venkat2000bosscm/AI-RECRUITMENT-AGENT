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

## Docker (PostgreSQL)

```bash
cp .env.example .env      # optionally set OPENAI_API_KEY
docker compose up --build # UI http://localhost:8080, API http://localhost:8000
```

## Configuration

See `.env.example`. Without `OPENAI_API_KEY` everything runs on offline templates and the deterministic decision layer. Set `OPENAI_BASE_URL`/`OPENAI_MODEL` to use any OpenAI-compatible provider (Azure OpenAI, local vLLM/Ollama, etc.). Screening thresholds (`STRONG_MATCH_THRESHOLD`, `PARTIAL_MATCH_THRESHOLD`, `MIN_CONFIDENCE`) are configurable.

## Tests

```bash
cd backend && pytest && ruff check .
cd frontend && npm run build
```

## Production notes

- Replace the demo `X-User-Id` header identity with SSO/OIDC.
- Swap local connectors in `integrations.py` for approved ATS, job-board, calendar (Google/Microsoft) and email providers.
- Configure data retention, encryption at rest and access reviews for candidate data.
- AI outputs are decision support only — final hiring decisions remain with authorised people.
