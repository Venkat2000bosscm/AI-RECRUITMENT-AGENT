from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import Candidate, Interview, Interviewer, Job, User
from ..schemas import (
    FeedbackRequest,
    InterviewCancelRequest,
    InterviewerOut,
    InterviewOut,
    InterviewRescheduleRequest,
)
from ..services import guardrails, llm, recruitment
from ..services.audit import log

router = APIRouter(prefix="/api", tags=["interviews"])


def interview_out(db: Session, i: Interview) -> InterviewOut:
    out = InterviewOut.model_validate(i)
    c = db.get(Candidate, i.candidate_id)
    iv = db.get(Interviewer, i.interviewer_id) if i.interviewer_id else None
    out.candidate_name = c.name if c else ""
    out.interviewer_name = iv.name if iv else ""
    out.job_title = db.get(Job, i.job_id).title
    return out


def get_interview(db: Session, interview_id: int) -> Interview:
    i = db.get(Interview, interview_id)
    if i is None:
        raise HTTPException(404, "Interview not found")
    return i


@router.get("/interviewers", response_model=list[InterviewerOut])
def interviewers(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return db.scalars(select(Interviewer)).all()


@router.get("/interviews", response_model=list[InterviewOut])
def list_interviews(
    status: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    q = select(Interview).order_by(Interview.start_time)
    if status:
        q = q.where(Interview.status == status)
    return [interview_out(db, i) for i in db.scalars(q.offset(offset).limit(limit)).all()]


@router.get("/interviews/{interview_id}", response_model=InterviewOut)
def read_interview(interview_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return interview_out(db, get_interview(db, interview_id))


@router.post("/interviews/{interview_id}/reschedule", response_model=InterviewOut)
def reschedule(
    interview_id: int,
    req: InterviewRescheduleRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    guardrails.ensure_permission(user, "schedule_interview")
    interview = get_interview(db, interview_id)
    recruitment.reschedule_interview(db, interview, req.start_time, user.name)
    db.commit()
    return interview_out(db, interview)


@router.post("/interviews/{interview_id}/cancel", response_model=InterviewOut)
def cancel(
    interview_id: int,
    req: InterviewCancelRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    guardrails.ensure_permission(user, "schedule_interview")
    interview = get_interview(db, interview_id)
    recruitment.cancel_interview(db, interview, user.name, req.reason)
    db.commit()
    return interview_out(db, interview)


@router.post("/interviews/{interview_id}/feedback", response_model=InterviewOut)
def feedback(interview_id: int, req: FeedbackRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    guardrails.ensure_permission(user, "submit_feedback")
    i = get_interview(db, interview_id)
    if i.status not in ("scheduled", "completed"):
        raise HTTPException(400, "Feedback can only be submitted for scheduled interviews")
    recruitment.submit_feedback(db, i, req.model_dump(), user.name)
    db.commit()
    return interview_out(db, i)


@router.post("/interviews/{interview_id}/regenerate-kit", response_model=InterviewOut)
def regenerate_kit(interview_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    guardrails.ensure_permission(user, "schedule_interview")
    i = get_interview(db, interview_id)
    c = db.get(Candidate, i.candidate_id)
    kit, source = llm.interview_kit(c.job, c)
    i.questions, i.checklist = kit.get("questions", []), kit.get("checklist", [])
    log(db, user.name, "interview_kit_generated", "interview", i.id, source=source)
    db.commit()
    return interview_out(db, i)
