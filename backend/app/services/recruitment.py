"""Recruitment operations shared by the API and the LangGraph agent.

High-impact actions never execute directly: they create an Approval and only run when a human approves.
"""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Approval, Candidate, Interview, Interviewer, Job, Offer, OnboardingTask, utcnow
from . import decision, llm
from .audit import log
from .integrations import calendar, email, job_boards
from .matching import find_duplicates

DEFAULT_CHANNELS = ["Company Careers Page", "LinkedIn"]
ONBOARDING_TEMPLATE = [
    ("Send welcome email and joining checklist", "HR"),
    ("Create employee record in HRMS", "HR"),
    ("Collect documents and complete background verification", "HR"),
    ("Provision laptop and peripherals", "IT"),
    ("Create email, SSO and tool access", "IT"),
    ("Assign onboarding buddy and 30/60/90-day plan", "Hiring Manager"),
]


# ------------------------------------------------------------------ approvals
def pending_approval(db: Session, type_: str, job_id: int | None = None, candidate_id: int | None = None) -> Approval | None:
    q = select(Approval).where(Approval.type == type_, Approval.status == "pending")
    if job_id is not None:
        q = q.where(Approval.job_id == job_id)
    if candidate_id is not None:
        q = q.where(Approval.candidate_id == candidate_id)
    return db.scalars(q).first()


def request_approval(
    db: Session,
    type_: str,
    title: str,
    actor: str,
    job: Job | None = None,
    candidate: Candidate | None = None,
    payload: dict | None = None,
    rationale: str = "",
) -> Approval:
    existing = pending_approval(db, type_, job.id if job else None, candidate.id if candidate else None)
    if existing:
        return existing
    approval = Approval(
        type=type_,
        title=title,
        job_id=job.id if job else (candidate.job_id if candidate else None),
        candidate_id=candidate.id if candidate else None,
        payload=payload or {},
        rationale=rationale,
        requested_by=actor,
    )
    db.add(approval)
    db.flush()
    log(db, actor, "approval_requested", "approval", approval.id, type=type_, title=title)
    return approval


# ------------------------------------------------------------------ jobs
def generate_jd(db: Session, job: Job, actor: str) -> str:
    text, source = llm.generate_jd(job)
    job.description = text
    log(db, actor, "jd_generated", "job", job.id, source=source)
    return text


def submit_jd(db: Session, job: Job, actor: str, channels: list[str] | None = None) -> Approval:
    if not job.description:
        generate_jd(db, job, actor)
    job.status = "pending_approval"
    return request_approval(
        db,
        "jd_publication",
        f"Approve & publish JD: {job.title}",
        actor,
        job=job,
        payload={"channels": channels or job.channels or DEFAULT_CHANNELS},
        rationale="Job descriptions must be approved by HR before publication.",
    )


def publish_job(db: Session, job: Job, channels: list[str], actor: str) -> list[dict]:
    postings = job_boards.publish(job, channels)
    job.channels = sorted(set(job.channels or []) | set(channels))
    job.status = "published"
    job.published_at = job.published_at or utcnow()
    log(db, actor, "job_published", "job", job.id, postings=postings)
    return postings


# ------------------------------------------------------------------ screening
def screen_candidate(db: Session, job: Job, candidate: Candidate, actor: str) -> Candidate:
    result = decision.screen(job, candidate.resume_text)
    duplicates = find_duplicates(db, candidate)
    if duplicates:
        duplicate_ids = [match["candidate_id"] for match in duplicates]
        result.flags.append(f"Potential duplicate profile(s): {', '.join(map(str, duplicate_ids[:5]))}")
    candidate.parsed = result.parsed
    candidate.name = candidate.name or result.parsed["name"]
    candidate.email = candidate.email or result.parsed["email"]
    candidate.phone = candidate.phone or result.parsed["phone"]
    candidate.location = candidate.location or result.parsed["location"]
    candidate.score = result.score
    candidate.score_breakdown = result.breakdown
    candidate.category = result.category
    candidate.confidence = result.confidence
    candidate.matched_skills = result.matched_skills
    candidate.missing_skills = result.missing_skills
    candidate.flags = result.flags
    candidate.summary, source = llm.summarize_candidate(job, candidate)
    candidate.screened_at = utcnow()
    if candidate.status == "applied":
        candidate.status = "screened"
    log(
        db,
        actor,
        "candidate_screened",
        "candidate",
        candidate.id,
        job_id=job.id,
        score=result.score,
        category=result.category,
        confidence=result.confidence,
        summary_source=source,
        prompt_version=llm.PROMPT_VERSION,
        model=llm.model_name(),
        duplicate_candidate_ids=[match["candidate_id"] for match in duplicates],
    )
    if result.category == decision.HUMAN_REVIEW:
        request_approval(
            db,
            "human_review",
            f"Review low-confidence profile: {candidate.name or candidate.id}",
            actor,
            job=job,
            candidate=candidate,
            payload={"suggested_category": decision.classify(result.score), "flags": result.flags},
            rationale="Decision layer confidence below threshold; human judgement required.",
        )
    return candidate


def unscreened(job: Job) -> list[Candidate]:
    return [c for c in job.candidates if c.screened_at is None]


def _in_shortlist_approval(db: Session, job: Job) -> set[int]:
    ids: set[int] = set()
    for a in db.scalars(select(Approval).where(Approval.job_id == job.id, Approval.type == "shortlist")).all():
        ids |= set(a.payload.get("candidate_ids", [])) | set(a.payload.get("not_recommended_ids", []))
    return ids


def shortlist_candidates_pending(db: Session, job: Job) -> list[Candidate]:
    seen = _in_shortlist_approval(db, job)
    return [
        c
        for c in job.candidates
        if c.status == "screened" and c.id not in seen and decision.effective_category(c) != decision.HUMAN_REVIEW
    ]


def propose_shortlist(db: Session, job: Job, actor: str) -> Approval | None:
    if pending_approval(db, "shortlist", job.id):
        return None
    pool = shortlist_candidates_pending(db, job)
    if not pool:
        return None
    pool.sort(key=lambda c: c.score or 0, reverse=True)
    recommended = [c for c in pool if decision.effective_category(c) in (decision.STRONG, decision.PARTIAL)]
    not_recommended = [c for c in pool if c not in recommended]
    counts = {
        "strong": sum(1 for c in recommended if decision.effective_category(c) == decision.STRONG),
        "partial": sum(1 for c in recommended if decision.effective_category(c) == decision.PARTIAL),
        "weak": len(not_recommended),
    }
    return request_approval(
        db,
        "shortlist",
        f"Shortlist {len(recommended)} candidate(s) for {job.title}",
        actor,
        job=job,
        payload={
            "candidate_ids": [c.id for c in recommended],
            "not_recommended_ids": [c.id for c in not_recommended],
            "candidates": [
                {
                    "id": c.id,
                    "name": c.name,
                    "score": c.score,
                    "category": decision.effective_category(c),
                    "matched_skills": c.matched_skills,
                    "missing_skills": c.missing_skills,
                }
                for c in pool
            ],
        },
        rationale=(
            f"{counts['strong']} strong and {counts['partial']} partial matches recommended; {counts['weak']} weak "
            "matches not recommended. Signals only - HR decides the final shortlist and may edit it."
        ),
    )


def apply_shortlist(db: Session, job: Job, candidate_ids: list[int], excluded_ids: list[int], actor: str) -> None:
    for c in job.candidates:
        if c.id in candidate_ids and c.status in ("screened", "applied"):
            c.status = "shortlisted"
            c.shortlisted_at = utcnow()
            log(db, actor, "candidate_shortlisted", "candidate", c.id, job_id=job.id)
        elif c.id in excluded_ids and c.status in ("screened", "applied"):
            c.status = "rejected"
            log(db, actor, "candidate_not_shortlisted", "candidate", c.id, job_id=job.id)
            send_candidate_email(db, "rejection", job, c, actor)


# ------------------------------------------------------------------ interviews
def pick_interviewer(db: Session, job: Job) -> Interviewer | None:
    interviewers = db.scalars(select(Interviewer)).all()
    if not interviewers:
        return None
    wanted = {s.lower() for s in job.required_skills + job.preferred_skills}
    return max(interviewers, key=lambda i: len(wanted & {e.lower() for e in i.expertise}))


def propose_interview(
    db: Session, candidate: Candidate, actor: str, interviewer_id: int | None = None, round_name: str = "Technical"
) -> Approval:
    job = candidate.job
    interviewer = db.get(Interviewer, interviewer_id) if interviewer_id else pick_interviewer(db, job)
    if interviewer is None:
        raise HTTPException(400, "No interviewers configured")
    slots = calendar.find_slots(db, interviewer)
    if not slots:
        raise HTTPException(409, "No free interviewer slots found in the next 3 weeks")
    kit, source = llm.interview_kit(job, candidate)
    interview = Interview(
        job_id=job.id,
        candidate_id=candidate.id,
        interviewer_id=interviewer.id,
        round_name=round_name,
        start_time=slots[0][0],
        end_time=slots[0][1],
        status="proposed",
        questions=kit.get("questions", []),
        checklist=kit.get("checklist", []),
    )
    db.add(interview)
    db.flush()
    log(db, actor, "interview_proposed", "interview", interview.id, candidate_id=candidate.id, kit_source=source)
    return request_approval(
        db,
        "interview_schedule",
        f"Schedule {round_name} interview: {candidate.name} with {interviewer.name}",
        actor,
        job=job,
        candidate=candidate,
        payload={
            "interview_id": interview.id,
            "interviewer": interviewer.name,
            "start_time": slots[0][0].isoformat(),
            "alternative_slots": [s.isoformat() for s, _ in slots[1:]],
        },
        rationale="Earliest free slot in interviewer's calendar. Approve to send the invitation.",
    )


def confirm_interview(db: Session, interview: Interview, actor: str, start_time: str | None = None) -> None:
    if start_time:
        start = _parse_interview_start(start_time)
        duration = interview.end_time - interview.start_time
        end = start + duration
        if start <= utcnow():
            raise HTTPException(422, "Interview must be scheduled in the future")
        if interview.interviewer_id and not calendar.is_available(
            db, interview.interviewer_id, start, end, exclude_interview_id=interview.id
        ):
            raise HTTPException(409, "The selected interviewer is no longer available at that time")
        interview.start_time, interview.end_time = start, end
    elif interview.interviewer_id and not calendar.is_available(
        db, interview.interviewer_id, interview.start_time, interview.end_time, exclude_interview_id=interview.id
    ):
        raise HTTPException(409, "The selected interviewer is no longer available at that time")
    interview.status = "scheduled"
    candidate = db.get(Candidate, interview.candidate_id)
    interviewer = db.get(Interviewer, interview.interviewer_id) if interview.interviewer_id else None
    candidate.status = "interview_scheduled"
    when = f"{interview.start_time:%a %d %b %Y, %H:%M} UTC"
    send_candidate_email(
        db,
        "interview_invite",
        candidate.job,
        candidate,
        actor,
        round_name=interview.round_name,
        when=when,
        interviewer=interviewer.name if interviewer else "TBD",
    )
    if interviewer:
        email.send(
            db,
            interviewer.email,
            f"Interview scheduled: {candidate.name} ({candidate.job.title})",
            f"You are scheduled to interview {candidate.name} on {when}.\n\nInterview kit is available in the recruitment "
            "assistant.",
            kind="interviewer_notice",
            job_id=candidate.job_id,
            candidate_id=candidate.id,
        )
    log(db, actor, "interview_scheduled", "interview", interview.id, start_time=interview.start_time.isoformat())


def _parse_interview_start(value: str) -> datetime:
    try:
        start = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(422, "start_time must be a valid ISO-8601 datetime") from exc
    if start.tzinfo is not None:
        start = start.astimezone(timezone.utc).replace(tzinfo=None)
    return start


def reschedule_interview(db: Session, interview: Interview, start_time: str, actor: str) -> None:
    if interview.status != "scheduled" or not interview.start_time or not interview.end_time:
        raise HTTPException(400, "Only scheduled interviews with a time can be rescheduled")
    start = _parse_interview_start(start_time)
    duration = interview.end_time - interview.start_time
    end = start + duration
    if start <= utcnow():
        raise HTTPException(422, "Interview must be rescheduled to a future time")
    if interview.interviewer_id and not calendar.is_available(
        db, interview.interviewer_id, start, end, exclude_interview_id=interview.id
    ):
        raise HTTPException(409, "The selected interviewer is not available at that time")
    interview.start_time, interview.end_time = start, end
    candidate = db.get(Candidate, interview.candidate_id)
    interviewer = db.get(Interviewer, interview.interviewer_id) if interview.interviewer_id else None
    when = f"{start:%a %d %b %Y, %H:%M} UTC"
    send_candidate_email(
        db,
        "interview_invite",
        candidate.job,
        candidate,
        actor,
        round_name=interview.round_name,
        when=when,
        interviewer=interviewer.name if interviewer else "TBD",
    )
    log(db, actor, "interview_rescheduled", "interview", interview.id, start_time=start.isoformat())


def cancel_interview(db: Session, interview: Interview, actor: str, reason: str = "") -> None:
    if interview.status not in {"proposed", "scheduled"}:
        raise HTTPException(400, "Only proposed or scheduled interviews can be cancelled")
    interview.status = "cancelled"
    candidate = db.get(Candidate, interview.candidate_id)
    remaining = db.scalars(
        select(Interview).where(
            Interview.candidate_id == candidate.id,
            Interview.id != interview.id,
            Interview.status.in_(["proposed", "scheduled"]),
        )
    ).first()
    if not remaining and candidate.status == "interview_scheduled":
        candidate.status = "shortlisted"
    send_candidate_email(
        db,
        "interview_cancelled",
        candidate.job,
        candidate,
        actor,
        round_name=interview.round_name,
    )
    log(db, actor, "interview_cancelled", "interview", interview.id, reason=reason)


def candidates_needing_interview(db: Session, job: Job) -> list[Candidate]:
    have = {
        i.candidate_id for i in db.scalars(select(Interview).where(Interview.job_id == job.id, Interview.status != "cancelled"))
    }
    return [c for c in job.candidates if c.status == "shortlisted" and c.id not in have]


def submit_feedback(db: Session, interview: Interview, feedback: dict, actor: str) -> Interview:
    interview.feedback = [*interview.feedback, {**feedback, "submitted_by": actor, "submitted_at": utcnow().isoformat()}]
    candidate = db.get(Candidate, interview.candidate_id)
    interview.feedback_summary, source = llm.summarize_feedback(candidate, interview.feedback)
    interview.status = "completed"
    if candidate.status == "interview_scheduled":
        candidate.status = "interviewed"
    log(db, actor, "feedback_submitted", "interview", interview.id, rating=feedback.get("rating"), summary_source=source)
    open_rounds = db.scalars(
        select(Interview).where(Interview.candidate_id == candidate.id, Interview.status.in_(["proposed", "scheduled"]))
    ).all()
    if not open_rounds:
        all_feedback = [
            f for i in db.scalars(select(Interview).where(Interview.candidate_id == candidate.id)) for f in i.feedback
        ]
        ratings = [f.get("rating") for f in all_feedback if f.get("rating")]
        request_approval(
            db,
            "hiring_decision",
            f"Final hiring decision: {candidate.name} ({candidate.job.title})",
            "agent",
            candidate=candidate,
            payload={
                "average_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
                "recommendations": [f.get("recommendation") for f in all_feedback],
                "feedback_summary": interview.feedback_summary,
            },
            rationale="All interview rounds complete. Approve = select candidate; reject = do not hire. "
            "Final decision is made by an authorized hiring decision-maker.",
        )
    return interview


# ------------------------------------------------------------------ offers
def draft_offer(
    db: Session, candidate: Candidate, actor: str, salary: float | None = None, start_date: str = "", extra_terms: str = ""
) -> Approval:
    job = candidate.job
    if candidate.status != "selected":
        raise HTTPException(400, "Offers can only be drafted for candidates selected by the hiring decision-maker")
    if salary is None:
        salary = (job.salary_min + job.salary_max) / 2 if job.salary_max else 0
    if not start_date:
        start_date = (utcnow() + timedelta(days=30)).date().isoformat()
    content, source = llm.draft_offer(job, candidate, salary, start_date, extra_terms)
    offer = Offer(
        job_id=job.id,
        candidate_id=candidate.id,
        salary=salary,
        currency=job.currency,
        start_date=start_date,
        content=content,
        status="pending_approval",
    )
    db.add(offer)
    db.flush()
    warnings = []
    if job.salary_max and not (job.salary_min <= salary <= job.salary_max):
        warnings.append("Proposed salary is outside the approved range for this role")
    log(db, actor, "offer_drafted", "offer", offer.id, candidate_id=candidate.id, salary=salary, source=source)
    return request_approval(
        db,
        "offer",
        f"Approve offer: {candidate.name} - {job.title}",
        actor,
        candidate=candidate,
        payload={
            "offer_id": offer.id,
            "salary": salary,
            "currency": job.currency,
            "start_date": start_date,
            "warnings": warnings,
        },
        rationale="Offer letters and compensation require hiring-manager approval before sending."
        + (" WARNING: " + "; ".join(warnings) if warnings else ""),
    )


def send_offer(db: Session, offer: Offer, actor: str, salary: float | None = None, start_date: str | None = None) -> None:
    candidate = db.get(Candidate, offer.candidate_id)
    if (salary is not None and salary != offer.salary) or (start_date and start_date != offer.start_date):
        offer.salary = salary if salary is not None else offer.salary
        offer.start_date = start_date or offer.start_date
        offer.content, _ = llm.draft_offer(candidate.job, candidate, offer.salary, offer.start_date)
    offer.status = "sent"
    offer.sent_at = utcnow()
    candidate.status = "offered"
    send_candidate_email(db, "offer", candidate.job, candidate, actor, offer_content=offer.content)
    log(db, actor, "offer_sent", "offer", offer.id, salary=offer.salary)


def record_offer_response(db: Session, offer: Offer, accepted: bool, actor: str) -> None:
    if offer.status != "sent":
        raise HTTPException(400, "Only sent offers can receive a response")
    candidate = db.get(Candidate, offer.candidate_id)
    offer.status = "accepted" if accepted else "declined"
    offer.responded_at = utcnow()
    candidate.status = "hired" if accepted else "declined"
    log(db, actor, f"offer_{offer.status}", "offer", offer.id, candidate_id=candidate.id)
    if accepted:
        request_approval(
            db,
            "onboarding",
            f"Start onboarding: {candidate.name}",
            "agent",
            candidate=candidate,
            payload={"tasks": [{"title": t, "owner": o} for t, o in ONBOARDING_TEMPLATE]},
            rationale="Offer accepted. Approve to initiate HR/IT onboarding tasks.",
        )


def offers_needing_follow_up(db: Session, job: Job, days: int = 3) -> list[Offer]:
    cutoff = utcnow() - timedelta(days=days)
    offers = db.scalars(select(Offer).where(Offer.job_id == job.id, Offer.status == "sent")).all()
    return [
        o for o in offers if o.sent_at and o.sent_at < cutoff and (o.last_follow_up_at is None or o.last_follow_up_at < cutoff)
    ]


def start_onboarding(db: Session, candidate: Candidate, tasks: list[dict], actor: str) -> list[OnboardingTask]:
    created = [OnboardingTask(candidate_id=candidate.id, title=t["title"], owner=t["owner"]) for t in tasks]
    db.add_all(created)
    log(db, actor, "onboarding_started", "candidate", candidate.id, tasks=len(created))
    return created


# ------------------------------------------------------------------ strategy
def recent_strategy_approval(db: Session, job: Job, days: int = 3) -> bool:
    cutoff = utcnow() - timedelta(days=days)
    return (
        db.scalars(
            select(Approval).where(Approval.job_id == job.id, Approval.type == "strategy_change", Approval.created_at > cutoff)
        ).first()
        is not None
    )


def propose_strategy(db: Session, job: Job, actor: str) -> Approval | None:
    strategy = decision.application_strategy(job, len(job.candidates))
    if not strategy or recent_strategy_approval(db, job):
        return None
    explanation, _ = llm.explain_strategy(job, strategy)
    return request_approval(
        db, "strategy_change", f"Adapt sourcing strategy: {job.title}", actor, job=job, payload=strategy, rationale=explanation
    )


def apply_strategy(db: Session, job: Job, strategy: dict, actor: str) -> None:
    for action in strategy.get("actions", []):
        if action["type"] == "expand_channels":
            publish_job(db, job, action["channels"], actor)
        elif action["type"] == "relax_requirements":
            moved = set(action["move_to_preferred"])
            job.required_skills = [s for s in job.required_skills if s not in moved]
            job.preferred_skills = [*job.preferred_skills, *[s for s in moved if s not in job.preferred_skills]]
        elif action["type"] == "widen_experience":
            job.experience_min = action["experience_min"]
    log(db, actor, "strategy_applied", "job", job.id, actions=[a["type"] for a in strategy.get("actions", [])])


# ------------------------------------------------------------------ communication
def send_candidate_email(db: Session, kind: str, job: Job, candidate: Candidate, actor: str, **ctx):
    if not candidate.email:
        log(db, actor, "email_skipped", "candidate", candidate.id, kind=kind, reason="no email")
        return
    msg, source = llm.draft_email(kind, job, candidate, **ctx)
    delivery = email.send(
        db, candidate.email, msg["subject"], msg["body"], kind=kind, job_id=job.id, candidate_id=candidate.id
    )
    log(db, actor, f"email_{delivery.status}", "candidate", candidate.id, kind=kind, source=source)
    return delivery


# ------------------------------------------------------------------ approval decisions
def decide_approval(
    db: Session, approval: Approval, approved: bool, actor: str, comment: str = "", overrides: dict | None = None
) -> Approval:
    if approval.status != "pending":
        raise HTTPException(400, f"Approval already {approval.status}")
    overrides = overrides or {}
    approval.status = "approved" if approved else "rejected"
    approval.decided_by = actor
    approval.decided_at = utcnow()
    approval.decision_comment = comment
    if overrides:
        approval.payload = {**approval.payload, "hr_overrides": overrides}
    job = db.get(Job, approval.job_id) if approval.job_id else None
    candidate = db.get(Candidate, approval.candidate_id) if approval.candidate_id else None
    p = approval.payload
    t = approval.type

    if t == "jd_publication":
        if approved:
            publish_job(db, job, overrides.get("channels") or p.get("channels") or DEFAULT_CHANNELS, actor)
        else:
            job.status = "draft"
    elif t == "strategy_change" and approved:
        apply_strategy(db, job, p, actor)
    elif t == "shortlist":
        if approved:
            ids = overrides.get("candidate_ids", p.get("candidate_ids", []))
            excluded = [i for i in p.get("candidate_ids", []) + p.get("not_recommended_ids", []) if i not in ids]
            apply_shortlist(db, job, ids, excluded if overrides.get("reject_others") else [], actor)
    elif t == "human_review":
        category = overrides.get("category") or (p.get("suggested_category") if approved else decision.WEAK)
        candidate.hr_category_override = category
        candidate.hr_note = comment or candidate.hr_note
    elif t == "interview_schedule":
        interview = db.get(Interview, p["interview_id"])
        if approved:
            confirm_interview(db, interview, actor, overrides.get("start_time"))
        else:
            interview.status = "cancelled"
    elif t == "hiring_decision":
        if approved:
            candidate.status = "selected"
        else:
            candidate.status = "rejected"
            send_candidate_email(db, "rejection", candidate.job, candidate, actor)
    elif t == "offer":
        offer = db.get(Offer, p["offer_id"])
        if approved:
            send_offer(db, offer, actor, overrides.get("salary"), overrides.get("start_date"))
        else:
            offer.status = "rejected"
    elif t == "onboarding" and approved:
        start_onboarding(db, candidate, overrides.get("tasks") or p.get("tasks", []), actor)

    log(db, actor, f"approval_{approval.status}", "approval", approval.id, type=t, comment=comment, overrides=overrides)
    return approval
