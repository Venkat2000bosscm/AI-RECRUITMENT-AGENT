import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import current_user
from ..models import Approval, AuditLog, Candidate, EmailMessage, Interview, Offer, OnboardingTask, User
from ..schemas import (
    ApprovalOut,
    CandidateCreate,
    CandidateDetail,
    CandidateOut,
    CandidateSearchPage,
    EmailRequest,
    InterviewOut,
    OfferDraftRequest,
    OnboardingTaskOut,
    OnboardingUpdate,
    OverrideRequest,
    ProposeInterviewRequest,
)
from ..services import decision, guardrails, recruitment
from ..services.audit import log
from ..services.matching import find_duplicates, recommend_candidates
from ..services.parsing import extract_text
from ..services.pipeline import DEFAULT_STAGES, get_stages
from .jobs import get_job

router = APIRouter(prefix="/api", tags=["candidates"])
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_UPLOADS_PER_REQUEST = 20
ALLOWED_EXTENSIONS = (".pdf", ".docx", ".txt", ".md")


def get_candidate(db: Session, candidate_id: int) -> Candidate:
    c = db.get(Candidate, candidate_id)
    if c is None:
        raise HTTPException(404, "Candidate not found")
    return c


def _add(db: Session, job, text: str, user: User, name="", email="", source="manual", filename="") -> Candidate:
    if not text.strip():
        raise HTTPException(400, f"No text could be extracted from {filename or 'resume'}")
    c = Candidate(job_id=job.id, resume_text=text, name=name, email=email, source=source, resume_filename=filename)
    db.add(c)
    db.flush()
    log(db, user.name, "candidate_added", "candidate", c.id, job_id=job.id, source=source)
    return c


@router.get("/jobs/{job_id}/candidates", response_model=list[CandidateOut])
def list_candidates(
    job_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    get_job(db, job_id)
    return db.scalars(
        select(Candidate)
        .where(Candidate.job_id == job_id)
        .order_by(Candidate.score.desc().nullslast(), Candidate.id)
        .offset(offset)
        .limit(limit)
    ).all()


@router.get("/candidates/search", response_model=CandidateSearchPage)
def search_candidates(
    q: str | None = Query(None, max_length=120),
    job_id: int | None = Query(None, ge=1),
    status: str | None = Query(None, max_length=40),
    category: str | None = Query(None, max_length=40),
    location: str | None = Query(None, max_length=120),
    source: str | None = Query(None, max_length=60),
    min_score: float | None = Query(None, ge=0, le=1),
    max_score: float | None = Query(None, ge=0, le=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if min_score is not None and max_score is not None and min_score > max_score:
        raise HTTPException(422, "min_score cannot be greater than max_score")
    query = select(Candidate)
    filters = []
    if job_id is not None:
        filters.append(Candidate.job_id == job_id)
    if status:
        filters.append(Candidate.status == status)
    if category:
        filters.append(or_(Candidate.hr_category_override == category, Candidate.category == category))
    if location:
        filters.append(func.lower(Candidate.location).contains(location.strip().lower()))
    if source:
        filters.append(func.lower(Candidate.source) == source.strip().lower())
    if q and q.strip():
        text = f"%{q.strip().lower()}%"
        filters.append(
            or_(
                func.lower(Candidate.name).like(text),
                func.lower(Candidate.email).like(text),
                func.lower(Candidate.location).like(text),
                func.lower(Candidate.summary).like(text),
                func.lower(Candidate.resume_text).like(text),
            )
        )
    if min_score is not None:
        filters.append(Candidate.score >= min_score)
    if max_score is not None:
        filters.append(Candidate.score <= max_score)
    if filters:
        query = query.where(*filters)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(
        query.order_by(Candidate.score.desc().nullslast(), Candidate.created_at.desc(), Candidate.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/jobs/{job_id}/recommendations")
def job_recommendations(
    job_id: int,
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return recommend_candidates(db, get_job(db, job_id), limit=limit)


@router.get("/candidates/{candidate_id}/duplicates")
def candidate_duplicates(
    candidate_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    candidate = get_candidate(db, candidate_id)
    matches = find_duplicates(db, candidate)
    if matches:
        log(db, "system", "duplicate_candidates_viewed", "candidate", candidate.id, duplicate_count=len(matches))
        db.commit()
    return {"candidate_id": candidate.id, "duplicates": matches}


@router.get("/candidates/{candidate_id}/timeline")
def candidate_timeline(candidate_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    candidate = get_candidate(db, candidate_id)
    events: list[dict] = []
    logs = db.scalars(
        select(AuditLog)
        .where(AuditLog.entity_type == "candidate", AuditLog.entity_id == candidate.id)
        .order_by(AuditLog.ts.desc())
        .limit(200)
    ).all()
    for entry in logs:
        events.append(
            {
                "timestamp": entry.ts,
                "type": entry.action,
                "actor": entry.actor,
                "details": entry.details,
            }
        )
    for interview in db.scalars(
        select(Interview).where(Interview.candidate_id == candidate.id).order_by(Interview.created_at.desc())
    ).all():
        events.append(
            {
                "timestamp": interview.created_at,
                "type": f"interview_{interview.status}",
                "actor": None,
                "details": {
                    "interview_id": interview.id,
                    "round_name": interview.round_name,
                    "start_time": interview.start_time,
                    "feedback_summary": interview.feedback_summary,
                },
            }
        )
    for approval in db.scalars(
        select(Approval).where(Approval.candidate_id == candidate.id).order_by(Approval.created_at.desc())
    ).all():
        events.append(
            {
                "timestamp": approval.created_at,
                "type": f"approval_{approval.status}",
                "actor": approval.decided_by or approval.requested_by,
                "details": {"approval_id": approval.id, "approval_type": approval.type, "title": approval.title},
            }
        )
    for message in db.scalars(
        select(EmailMessage).where(EmailMessage.candidate_id == candidate.id).order_by(EmailMessage.created_at.desc())
    ).all():
        events.append(
            {
                "timestamp": message.created_at,
                "type": f"email_{message.status}",
                "actor": None,
                "details": {"email_id": message.id, "kind": message.kind, "subject": message.subject},
            }
        )
    for offer in db.scalars(select(Offer).where(Offer.candidate_id == candidate.id)).all():
        events.append(
            {
                "timestamp": offer.created_at,
                "type": f"offer_{offer.status}",
                "actor": None,
                "details": {"offer_id": offer.id, "salary": offer.salary, "currency": offer.currency},
            }
        )
    events.sort(key=lambda event: event["timestamp"], reverse=True)
    return {"candidate_id": candidate.id, "events": events[:500]}


@router.post("/jobs/{job_id}/candidates", response_model=CandidateDetail)
def add_candidate(
    job_id: int, req: CandidateCreate, screen: bool = True, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    guardrails.ensure_permission(user, "add_candidate")
    job = get_job(db, job_id)
    c = _add(db, job, req.resume_text, user, req.name, req.email, req.source)
    if screen:
        recruitment.screen_candidate(db, job, c, user.name)
    db.commit()
    return c


@router.post("/jobs/{job_id}/candidates/upload", response_model=list[CandidateOut])
async def upload_resumes(
    job_id: int,
    files: list[UploadFile] = File(...),
    screen: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    guardrails.ensure_permission(user, "add_candidate")
    job = get_job(db, job_id)
    os.makedirs(settings.upload_dir, exist_ok=True)
    if len(files) > MAX_UPLOADS_PER_REQUEST:
        raise HTTPException(413, f"At most {MAX_UPLOADS_PER_REQUEST} resumes may be uploaded at once")
    created = []
    for f in files:
        name = f.filename or "resume.txt"
        if not name.lower().endswith(ALLOWED_EXTENSIONS):
            raise HTTPException(400, f"Unsupported file type: {name}")
        if f.size is not None and f.size > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"{name} exceeds 5 MB")
        data = await f.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"{name} exceeds 5 MB")
        with open(os.path.join(settings.upload_dir, f"{uuid.uuid4().hex}_{os.path.basename(name)}"), "wb") as out:
            out.write(data)
        c = _add(db, job, extract_text(name, data), user, source="upload", filename=name)
        if screen:
            recruitment.screen_candidate(db, job, c, user.name)
        created.append(c)
    db.commit()
    return created


@router.post("/jobs/{job_id}/screen", response_model=list[CandidateOut])
def screen_all(job_id: int, rescreen: bool = False, db: Session = Depends(get_db), user: User = Depends(current_user)):
    guardrails.ensure_permission(user, "screen_candidates")
    job = get_job(db, job_id)
    targets = job.candidates if rescreen else recruitment.unscreened(job)
    for c in targets:
        recruitment.screen_candidate(db, job, c, user.name)
    db.commit()
    return targets


@router.post("/jobs/{job_id}/propose-shortlist", response_model=ApprovalOut | None)
def propose_shortlist(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    guardrails.ensure_permission(user, "shortlist")
    a = recruitment.propose_shortlist(db, get_job(db, job_id), user.name)
    db.commit()
    return a


@router.get("/candidates/{candidate_id}", response_model=CandidateDetail)
def read_candidate(candidate_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return get_candidate(db, candidate_id)


@router.post("/candidates/{candidate_id}/rescreen", response_model=CandidateDetail)
def rescreen(candidate_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    guardrails.ensure_permission(user, "screen_candidates")
    c = get_candidate(db, candidate_id)
    recruitment.screen_candidate(db, c.job, c, user.name)
    db.commit()
    return c


VALID_CATEGORIES = {decision.STRONG, decision.PARTIAL, decision.WEAK, decision.HUMAN_REVIEW}
HR_SETTABLE_STATUSES = {"screened", "shortlisted", "rejected", "withdrawn"}


@router.post("/candidates/{candidate_id}/override", response_model=CandidateDetail)
def override(candidate_id: int, req: OverrideRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    guardrails.ensure_permission(user, "override_candidate")
    c = get_candidate(db, candidate_id)
    if req.category:
        if req.category not in VALID_CATEGORIES:
            raise HTTPException(422, "Invalid category")
        c.hr_category_override = req.category
    if req.status:
        configured = {stage["key"] for stage in get_stages(db)}
        if req.status not in configured:
            raise HTTPException(422, "Status is not configured in the recruitment pipeline")
        custom_stages = configured - {stage["key"] for stage in DEFAULT_STAGES}
        if req.status not in HR_SETTABLE_STATUSES and req.status not in custom_stages:
            raise HTTPException(422, f"Status must be one of {sorted(HR_SETTABLE_STATUSES | custom_stages)}")
        if req.status == "rejected" and not req.note.strip():
            raise HTTPException(422, "A rejection reason is required")
        c.status = req.status
    if req.note:
        c.hr_note = req.note
    log(db, user.name, "candidate_override", "candidate", c.id, category=req.category, status=req.status, note=req.note)
    db.commit()
    return c


@router.post("/candidates/{candidate_id}/interviews", response_model=ApprovalOut)
def propose_interview(
    candidate_id: int, req: ProposeInterviewRequest, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    guardrails.ensure_permission(user, "schedule_interview")
    c = get_candidate(db, candidate_id)
    if c.status not in ("shortlisted", "interview_scheduled", "interviewed"):
        raise HTTPException(400, "Candidate must be shortlisted before scheduling interviews")
    a = recruitment.propose_interview(db, c, user.name, req.interviewer_id, req.round_name)
    db.commit()
    return a


@router.get("/candidates/{candidate_id}/interviews", response_model=list[InterviewOut])
def candidate_interviews(candidate_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    from .interviews import interview_out

    return [interview_out(db, i) for i in db.scalars(select(Interview).where(Interview.candidate_id == candidate_id)).all()]


@router.post("/candidates/{candidate_id}/offer", response_model=ApprovalOut)
def draft_offer(candidate_id: int, req: OfferDraftRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    guardrails.ensure_permission(user, "draft_offer")
    a = recruitment.draft_offer(db, get_candidate(db, candidate_id), user.name, req.salary, req.start_date, req.extra_terms)
    db.commit()
    return a


@router.post("/candidates/{candidate_id}/email")
def email_candidate(candidate_id: int, req: EmailRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    guardrails.ensure_permission(user, "send_email")
    c = get_candidate(db, candidate_id)
    message = recruitment.send_candidate_email(db, req.kind, c.job, c, user.name, message=req.message)
    db.commit()
    return {"ok": bool(message and message.status in {"queued", "sent"}), "status": message.status if message else "skipped"}


@router.get("/candidates/{candidate_id}/onboarding", response_model=list[OnboardingTaskOut])
def onboarding(candidate_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return db.scalars(select(OnboardingTask).where(OnboardingTask.candidate_id == candidate_id)).all()


@router.patch("/onboarding/{task_id}", response_model=OnboardingTaskOut)
def update_onboarding(task_id: int, req: OnboardingUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    guardrails.ensure_permission(user, "onboarding")
    t = db.get(OnboardingTask, task_id)
    if t is None:
        raise HTTPException(404, "Task not found")
    t.status = req.status
    log(db, user.name, "onboarding_task_updated", "onboarding_task", t.id, status=req.status)
    db.commit()
    return t
