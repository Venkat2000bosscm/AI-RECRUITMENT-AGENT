"""LangGraph orchestrator for a single requisition.

Operating model: Hiring Goal -> Planning -> Reasoning -> Tool Usage -> Execution -> Monitoring -> Adaptation
-> Human Approval -> Completion.

Each run loops plan -> tool -> monitor until the workflow reaches a human-approval checkpoint (or there is
nothing left to do). Durable state lives in the database, so runs are idempotent and can be triggered
manually, on a schedule, or after an approval decision.
"""

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AgentRun, Approval, Job
from ..services import guardrails, recruitment

ACTOR = "agent"
MAX_STEPS = 12


class AgentState(TypedDict):
    job_id: int
    next_action: str
    reason: str
    done_actions: Annotated[list[str], operator.add]
    steps: Annotated[list[dict], operator.add]
    outcome: str


def _step(phase: str, action: str, detail: str) -> dict:
    return {"phase": phase, "action": action, "detail": detail}


def build_graph(db: Session):
    def load(state: AgentState) -> Job:
        db.flush()
        job = db.get(Job, state["job_id"])
        db.expire(job, ["candidates"])
        return job

    # ------------------------------------------------------------ planning & reasoning
    def plan(state: AgentState) -> dict:
        job = load(state)
        done = set(state["done_actions"])

        def choose(action: str, reason: str) -> dict:
            return {"next_action": action, "reason": reason, "steps": [_step("planning", action, reason)]}

        if len(state["done_actions"]) >= MAX_STEPS:
            return choose("finish", "Step budget reached")
        if guardrails.is_agent_paused(db, job):
            return choose("finish", "Agent is paused by HR")
        if job.status == "closed":
            return choose("finish", "Requisition closed")
        if job.status == "draft":
            if not job.description and "draft_jd" not in done:
                return choose("draft_jd", "No job description yet - drafting from approved requirement")
            if "request_jd_approval" not in done:
                return choose("request_jd_approval", "JD ready - HR approval required before publishing")
        if job.status == "pending_approval":
            return choose("finish", "Waiting for HR to approve the JD")
        if job.status == "published":
            if recruitment.unscreened(job) and "screen" not in done:
                return choose("screen", f"{len(recruitment.unscreened(job))} new application(s) to screen")
            if "adapt_strategy" not in done and not recruitment.recent_strategy_approval(db, job):
                from ..services.decision import application_strategy

                if application_strategy(job, len(job.candidates)):
                    return choose("adapt_strategy", "Application volume below target - recommending strategy change")
            if (
                "propose_shortlist" not in done
                and recruitment.shortlist_candidates_pending(db, job)
                and not recruitment.pending_approval(db, "shortlist", job.id)
            ):
                return choose("propose_shortlist", "Screened candidates ready for shortlist review")
            if "schedule_interviews" not in done and recruitment.candidates_needing_interview(db, job):
                return choose("schedule_interviews", "Shortlisted candidates need interviews")
            if "draft_offers" not in done and [
                c
                for c in job.candidates
                if c.status == "selected" and not recruitment.pending_approval(db, "offer", candidate_id=c.id)
            ]:
                return choose("draft_offers", "Selected candidates need offer drafts")
            if "follow_up_offers" not in done and recruitment.offers_needing_follow_up(db, job):
                return choose("follow_up_offers", "Offers awaiting response for 3+ days")
        pending = db.scalars(select(Approval).where(Approval.job_id == job.id, Approval.status == "pending")).all()
        if pending:
            return choose("finish", f"Waiting on {len(pending)} HR approval(s): " + ", ".join(sorted({a.type for a in pending})))
        return choose("finish", "No actions required right now")

    # ------------------------------------------------------------ tools
    def draft_jd(state: AgentState) -> dict:
        job = load(state)
        recruitment.generate_jd(db, job, ACTOR)
        return {
            "done_actions": ["draft_jd"],
            "steps": [_step("tool", "generate_jd", f"Drafted JD ({len(job.description)} chars)")],
        }

    def request_jd_approval(state: AgentState) -> dict:
        job = load(state)
        a = recruitment.submit_jd(db, job, ACTOR)
        return {
            "done_actions": ["request_jd_approval"],
            "steps": [_step("approval", "jd_publication", f"Approval #{a.id} requested")],
        }

    def screen(state: AgentState) -> dict:
        job = load(state)
        pending = recruitment.unscreened(job)
        for c in pending:
            recruitment.screen_candidate(db, job, c, ACTOR)
        cats: dict[str, int] = {}
        for c in pending:
            cats[c.category] = cats.get(c.category, 0) + 1
        return {
            "done_actions": ["screen"],
            "steps": [
                _step("tool", "screen_candidates", f"Screened {len(pending)}: " + ", ".join(f"{k}={v}" for k, v in cats.items()))
            ],
        }

    def adapt_strategy(state: AgentState) -> dict:
        job = load(state)
        a = recruitment.propose_strategy(db, job, ACTOR)
        detail = f"Strategy approval #{a.id} requested" if a else "No strategy change needed"
        return {"done_actions": ["adapt_strategy"], "steps": [_step("adaptation", "propose_strategy", detail)]}

    def propose_shortlist(state: AgentState) -> dict:
        job = load(state)
        a = recruitment.propose_shortlist(db, job, ACTOR)
        detail = f"Shortlist approval #{a.id}: {a.rationale}" if a else "Nothing to shortlist"
        return {"done_actions": ["propose_shortlist"], "steps": [_step("approval", "shortlist", detail)]}

    def schedule_interviews(state: AgentState) -> dict:
        job = load(state)
        out = []
        for c in recruitment.candidates_needing_interview(db, job):
            try:
                a = recruitment.propose_interview(db, c, ACTOR)
                out.append(f"{c.name} @ {a.payload['start_time'][:16]}")
            except Exception as exc:  # noqa: BLE001 - surface and continue with other candidates
                out.append(f"{c.name}: {getattr(exc, 'detail', exc)}")
        return {"done_actions": ["schedule_interviews"], "steps": [_step("tool", "calendar.find_slots", "; ".join(out))]}

    def draft_offers(state: AgentState) -> dict:
        job = load(state)
        out = []
        for c in job.candidates:
            if c.status == "selected" and not recruitment.pending_approval(db, "offer", candidate_id=c.id):
                a = recruitment.draft_offer(db, c, ACTOR)
                out.append(f"{c.name}: approval #{a.id}")
        return {"done_actions": ["draft_offers"], "steps": [_step("approval", "offer", "; ".join(out))]}

    def follow_up_offers(state: AgentState) -> dict:
        job = load(state)
        offers = recruitment.offers_needing_follow_up(db, job)
        for o in offers:
            cand = next(c for c in job.candidates if c.id == o.candidate_id)
            recruitment.send_candidate_email(db, "offer_follow_up", job, cand, ACTOR)
            from ..models import utcnow

            o.last_follow_up_at = utcnow()
        return {
            "done_actions": ["follow_up_offers"],
            "steps": [_step("tool", "email.send", f"Followed up on {len(offers)} offer(s)")],
        }

    # ------------------------------------------------------------ monitoring
    def monitor(state: AgentState) -> dict:
        db.flush()
        job = load(state)
        counts: dict[str, int] = {}
        for c in job.candidates:
            counts[c.status] = counts.get(c.status, 0) + 1
        return {
            "steps": [
                _step(
                    "monitoring", "pipeline_snapshot", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "no candidates"
                )
            ]
        }

    def finish(state: AgentState) -> dict:
        return {"outcome": state["reason"], "steps": [_step("completion", "finish", state["reason"])]}

    tools = {
        "draft_jd": draft_jd,
        "request_jd_approval": request_jd_approval,
        "screen": screen,
        "adapt_strategy": adapt_strategy,
        "propose_shortlist": propose_shortlist,
        "schedule_interviews": schedule_interviews,
        "draft_offers": draft_offers,
        "follow_up_offers": follow_up_offers,
    }
    graph = StateGraph(AgentState)
    graph.add_node("plan", plan)
    graph.add_node("monitor", monitor)
    graph.add_node("finish", finish)
    for name, fn in tools.items():
        graph.add_node(name, fn)
        graph.add_edge(name, "monitor")
    graph.add_edge(START, "plan")
    graph.add_conditional_edges("plan", lambda s: s["next_action"], {**{k: k for k in tools}, "finish": "finish"})
    graph.add_edge("monitor", "plan")
    graph.add_edge("finish", END)
    return graph.compile()


def run_agent(db: Session, job_id: int) -> AgentRun:
    graph = build_graph(db)
    final = graph.invoke(
        {"job_id": job_id, "next_action": "", "reason": "", "done_actions": [], "steps": [], "outcome": ""},
        {"recursion_limit": 100},
    )
    run = AgentRun(job_id=job_id, steps=final["steps"], outcome=final["outcome"])
    db.add(run)
    db.commit()
    return run


def graph_mermaid() -> str:
    return build_graph(None).get_graph().draw_mermaid()  # type: ignore[arg-type]
