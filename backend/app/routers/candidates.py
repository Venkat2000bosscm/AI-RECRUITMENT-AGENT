import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import current_user
from ..models import Candidate, Interview, OnboardingTask, User
from ..schemas import (
    ApprovalOut,
    CandidateCreate,
    CandidateDetail,
    CandidateOut,
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
from ..services.parsing import extract_text
from .jobs import get_job

router = APIRouter(prefix="/api", tags=["candidates"])
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
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
def list_candidates(job_id: int, db: Session = Depends(get_db)):
    return db.scalars(
        select(Candidate).where(Candidate.job_id == job_id).order_by(Candidate.score.desc().nullslast(), Candidate.id)
    ).all()


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
    created = []
    for f in files:
        name = f.filename or "resume.txt"
        if not name.lower().endswith(ALLOWED_EXTENSIONS):
            raise HTTPException(400, f"Unsupported file type: {name}")
        data = await f.read()
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
def read_candidate(candidate_id: int, db: Session = Depends(get_db)):
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
        if req.status not in HR_SETTABLE_STATUSES:
            raise HTTPException(422, f"Status must be one of {sorted(HR_SETTABLE_STATUSES)}")
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
def candidate_interviews(candidate_id: int, db: Session = Depends(get_db)):
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
    recruitment.send_candidate_email(db, req.kind, c.job, c, user.name, message=req.message)
    db.commit()
    return {"ok": True}


@router.get("/candidates/{candidate_id}/onboarding", response_model=list[OnboardingTaskOut])
def onboarding(candidate_id: int, db: Session = Depends(get_db)):
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
