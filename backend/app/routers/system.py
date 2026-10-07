from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agent.workflow import graph_mermaid, run_agent
from ..config import settings
from ..db import get_db
from ..deps import current_user
from ..models import Approval, AuditLog, Candidate, EmailMessage, Interview, Job, Offer, User, utcnow
from ..schemas import AuditOut, EmailOut, PauseRequest, PipelineStagesRequest, UserOut
from ..services import guardrails, llm
from ..services.audit import log
from ..services.decision import HUMAN_REVIEW, PARTIAL, STRONG, WEAK
from ..services.pipeline import DEFAULT_STAGES, get_stages, save_stages

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/health/ready")
def readiness(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ready", "database": "ok"}


@router.get("/config")
def config(db: Session = Depends(get_db)):
    return {
        "llm_mode": "llm" if llm.llm_available() else "template",
        "llm_model": settings.openai_model if llm.llm_available() else None,
        "demo_mode": settings.demo_mode,
        "agent_paused": guardrails.is_globally_paused(db),
        "feature_flags": {"candidate_rediscovery": True, "explainable_scoring": True, "google_workspace": False},
        "scoring_weights": settings.score_weights,
        "thresholds": {
            "strong": settings.strong_match_threshold,
            "partial": settings.partial_match_threshold,
            "min_confidence": settings.min_confidence,
        },
    }


@router.get("/pipeline/stages")
def pipeline_stages(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return {"stages": get_stages(db)}


@router.put("/pipeline/stages")
def update_pipeline_stages(
    req: PipelineStagesRequest, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    guardrails.ensure_permission(user, "edit_job")
    stages = [stage.model_dump() for stage in req.stages]
    keys = [stage["key"] for stage in stages]
    required = {stage["key"] for stage in DEFAULT_STAGES}
    if len(keys) != len(set(keys)):
        raise HTTPException(422, "Pipeline stage keys must be unique")
    if not required.issubset(keys):
        missing = ", ".join(sorted(required - set(keys)))
        raise HTTPException(422, f"Built-in workflow stages cannot be removed: {missing}")
    save_stages(db, stages)
    log(db, user.name, "pipeline_stages_updated", "system", stages=stages)
    db.commit()
    return {"stages": stages}


@router.get("/users", response_model=list[UserOut])
def users(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return db.scalars(select(User)).all()


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@router.post("/agent/pause")
def pause(req: PauseRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    guardrails.ensure_permission(user, "pause_agent")
    guardrails.set_global_pause(db, req.paused)
    log(db, user.name, "agent_paused_globally" if req.paused else "agent_resumed_globally", "system")
    db.commit()
    return {"agent_paused": req.paused}


@router.post("/agent/run-all")
def run_all(db: Session = Depends(get_db), user: User = Depends(current_user)):
    guardrails.ensure_permission(user, "run_agent")
    jobs = db.scalars(select(Job).where(Job.status.in_(["draft", "published"]))).all()
    return [{"job_id": j.id, "outcome": run_agent(db, j.id).outcome} for j in jobs]


@router.get("/agent/graph")
def graph(user: User = Depends(current_user)):
    return {"mermaid": graph_mermaid()}


@router.get("/audit", response_model=list[AuditOut])
def audit(
    entity_type: str | None = None,
    entity_id: int | None = None,
    actor: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000))
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    if entity_id:
        q = q.where(AuditLog.entity_id == entity_id)
    if actor:
        q = q.where(AuditLog.actor == actor)
    return db.scalars(q).all()


@router.get("/emails", response_model=list[EmailOut])
def emails(candidate_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = select(EmailMessage).order_by(EmailMessage.id.desc()).limit(200)
    if candidate_id:
        q = q.where(EmailMessage.candidate_id == candidate_id)
    return db.scalars(q).all()


@router.get("/analytics/summary")
def analytics(job_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    cq = select(Candidate)
    if job_id:
        cq = cq.where(Candidate.job_id == job_id)
    candidates = db.scalars(cq).all()
    screened = [c for c in candidates if c.screened_at]
    categories = {k: 0 for k in (STRONG, PARTIAL, WEAK, HUMAN_REVIEW)}
    for c in screened:
        categories[c.category] = categories.get(c.category, 0) + 1
    pipeline: dict[str, int] = {}
    for c in candidates:
        pipeline[c.status] = pipeline.get(c.status, 0) + 1
    overrides = [c for c in screened if c.hr_category_override and c.hr_category_override != c.category]
    shortlist_hours = [(c.shortlisted_at - c.created_at) / timedelta(hours=1) for c in candidates if c.shortlisted_at]
    approval_query = select(Approval)
    interview_query = select(Interview)
    offer_query = select(Offer)
    job_query = select(Job)
    if job_id:
        approval_query = approval_query.where(Approval.job_id == job_id)
        interview_query = interview_query.where(Interview.job_id == job_id)
        offer_query = offer_query.where(Offer.job_id == job_id)
        job_query = job_query.where(Job.id == job_id)
    approvals = db.scalars(approval_query).all()
    decided = [a for a in approvals if a.decided_at]
    approval_hours = [(a.decided_at - a.created_at) / timedelta(hours=1) for a in decided]
    interviews = db.scalars(interview_query).all()
    offers = db.scalars(offer_query).all()
    jobs = db.scalars(job_query).all()
    llm_calls = llm.usage_stats["llm_calls"]
    est_cost = (llm.usage_stats["prompt_chars"] / 4 * 0.15 + llm.usage_stats["completion_chars"] / 4 * 0.6) / 1_000_000
    source_effectiveness: dict[str, dict[str, int | float]] = {}
    for candidate in candidates:
        metrics = source_effectiveness.setdefault(
            candidate.source or "unknown", {"applications": 0, "screened": 0, "shortlisted": 0, "hired": 0}
        )
        metrics["applications"] += 1
        metrics["screened"] += int(candidate.screened_at is not None)
        metrics["shortlisted"] += int(candidate.shortlisted_at is not None)
        metrics["hired"] += int(candidate.status == "hired")
    for metrics in source_effectiveness.values():
        metrics["hire_rate_pct"] = round(100 * metrics["hired"] / metrics["applications"], 1)
    candidate_by_id = {candidate.id: candidate for candidate in candidates}
    hire_durations = [
        (offer.responded_at - candidate_by_id[offer.candidate_id].created_at) / timedelta(days=1)
        for offer in offers
        if offer.status == "accepted" and offer.responded_at and offer.candidate_id in candidate_by_id
    ]
    total_candidates = len(candidates)
    funnel_order = (
        "applied",
        "screened",
        "shortlisted",
        "interview_scheduled",
        "interviewed",
        "selected",
        "offered",
        "hired",
        "rejected",
        "declined",
        "withdrawn",
    )
    funnel = [
        {
            "stage": stage,
            "count": pipeline.get(stage, 0),
            "share_pct": round(100 * pipeline.get(stage, 0) / total_candidates, 1) if total_candidates else 0,
        }
        for stage in funnel_order
    ]
    recruiter_workload: dict[str, int] = {}
    for job in jobs:
        owner = job.created_by or "unassigned"
        recruiter_workload[owner] = recruiter_workload.get(owner, 0) + int(
            job.status in {"draft", "published", "pending_approval"}
        )
    now = utcnow()
    return {
        "jobs": {
            "total": len(jobs),
            "published": sum(j.status == "published" for j in jobs),
            "draft": sum(j.status == "draft" for j in jobs),
        },
        "candidates": {"total": len(candidates), "screened": len(screened)},
        "categories": categories,
        "pipeline": pipeline,
        "funnel": funnel,
        "source_effectiveness": source_effectiveness,
        "avg_time_to_hire_days": round(sum(hire_durations) / len(hire_durations), 1) if hire_durations else None,
        "recruiter_workload": recruiter_workload,
        "upcoming_interviews": sum(
            interview.status == "scheduled" and interview.start_time is not None and interview.start_time >= now
            for interview in interviews
        ),
        "human_review_pct": round(100 * categories[HUMAN_REVIEW] / len(screened), 1) if screened else 0,
        "hr_override_pct": round(100 * len(overrides) / len(screened), 1) if screened else 0,
        "avg_score": round(sum(c.score for c in screened) / len(screened), 3) if screened else None,
        "avg_hours_to_shortlist": round(sum(shortlist_hours) / len(shortlist_hours), 1) if shortlist_hours else None,
        "approvals": {
            "pending": sum(a.status == "pending" for a in approvals),
            "approved": sum(a.status == "approved" for a in approvals),
            "rejected": sum(a.status == "rejected" for a in approvals),
            "avg_hours_to_decision": round(sum(approval_hours) / len(approval_hours), 1) if approval_hours else None,
        },
        "interviews": {
            "scheduled": sum(i.status == "scheduled" for i in interviews),
            "completed": sum(i.status == "completed" for i in interviews),
        },
        "offers": {s: sum(o.status == s for o in offers) for s in ("pending_approval", "sent", "accepted", "declined")},
        "emails_sent": len(db.scalars(select(EmailMessage.id)).all()),
        "ai_usage": {
            **llm.usage_stats,
            "estimated_llm_cost_usd": round(est_cost, 4),
            "mode": "llm" if llm_calls or llm.llm_available() else "template",
        },
    }
