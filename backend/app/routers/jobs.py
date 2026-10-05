from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agent.workflow import run_agent
from ..db import get_db
from ..deps import current_user
from ..models import AgentRun, Job, User
from ..schemas import AgentRunOut, ApprovalOut, IntakeRequest, JobCreate, JobOut, JobUpdate, PauseRequest
from ..services import guardrails, llm, recruitment
from ..services.audit import log

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def job_out(job: Job) -> JobOut:
    out = JobOut.model_validate(job)
    out.candidate_count = len(job.candidates)
    pipeline: dict[str, int] = {}
    for c in job.candidates:
        pipeline[c.status] = pipeline.get(c.status, 0) + 1
    out.pipeline = pipeline
    return out


def get_job(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


def _check_criteria(payload: dict) -> None:
    text = " ".join(str(payload.get(k, "")) for k in ("constraints", "qualifications", "title"))
    text += " " + " ".join(payload.get("required_skills") or []) + " " + " ".join(payload.get("preferred_skills") or [])
    found = guardrails.find_protected_criteria(text)
    if found:
        raise HTTPException(
            422,
            f"Hiring criteria reference protected attributes ({', '.join(found)}). Remove them - candidates may only be "
            "evaluated on job-related criteria.",
        )


@router.get("", response_model=list[JobOut])
def list_jobs(db: Session = Depends(get_db)):
    return [job_out(j) for j in db.scalars(select(Job).order_by(Job.created_at.desc())).all()]


@router.post("/intake")
def intake(req: IntakeRequest, user: User = Depends(current_user)):
    guardrails.ensure_permission(user, "create_job")
    structured, source = llm.extract_requirement(req.text)
    return {"requirement": structured, "source": source, "protected_terms": guardrails.find_protected_criteria(req.text)}


@router.post("", response_model=JobOut)
def create_job(req: JobCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    guardrails.ensure_permission(user, "create_job")
    _check_criteria(req.model_dump())
    job = Job(**req.model_dump(), created_by=user.name)
    db.add(job)
    db.flush()
    log(db, user.name, "job_created", "job", job.id, title=job.title)
    db.commit()
    return job_out(job)


@router.get("/{job_id}", response_model=JobOut)
def read_job(job_id: int, db: Session = Depends(get_db)):
    return job_out(get_job(db, job_id))


@router.patch("/{job_id}", response_model=JobOut)
def update_job(job_id: int, req: JobUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    guardrails.ensure_permission(user, "edit_job")
    job = get_job(db, job_id)
    changes = req.model_dump(exclude_unset=True)
    _check_criteria(
        {
            **{k: getattr(job, k) for k in ("constraints", "qualifications", "title", "required_skills", "preferred_skills")},
            **changes,
        }
    )
    for k, v in changes.items():
        setattr(job, k, v)
    log(db, user.name, "job_updated", "job", job.id, fields=sorted(changes))
    db.commit()
    return job_out(job)


@router.post("/{job_id}/generate-jd", response_model=JobOut)
def generate_jd(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    guardrails.ensure_permission(user, "edit_job")
    job = get_job(db, job_id)
    recruitment.generate_jd(db, job, user.name)
    db.commit()
    return job_out(job)


@router.post("/{job_id}/submit-jd", response_model=ApprovalOut)
def submit_jd(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    guardrails.ensure_permission(user, "publish_job")
    job = get_job(db, job_id)
    if job.status not in ("draft", "pending_approval"):
        raise HTTPException(400, f"Job is already {job.status}")
    approval = recruitment.submit_jd(db, job, user.name)
    db.commit()
    return approval


@router.post("/{job_id}/close", response_model=JobOut)
def close_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    guardrails.ensure_permission(user, "edit_job")
    job = get_job(db, job_id)
    job.status = "closed"
    log(db, user.name, "job_closed", "job", job.id)
    db.commit()
    return job_out(job)


@router.post("/{job_id}/pause", response_model=JobOut)
def pause_job_agent(job_id: int, req: PauseRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    guardrails.ensure_permission(user, "pause_agent")
    job = get_job(db, job_id)
    job.agent_paused = req.paused
    log(db, user.name, "agent_paused" if req.paused else "agent_resumed", "job", job.id)
    db.commit()
    return job_out(job)


@router.post("/{job_id}/agent/run", response_model=AgentRunOut)
def run(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    guardrails.ensure_permission(user, "run_agent")
    get_job(db, job_id)
    log(db, user.name, "agent_run_triggered", "job", job_id)
    return run_agent(db, job_id)


@router.get("/{job_id}/agent/runs", response_model=list[AgentRunOut])
def runs(job_id: int, db: Session = Depends(get_db)):
    return db.scalars(select(AgentRun).where(AgentRun.job_id == job_id).order_by(AgentRun.id.desc()).limit(20)).all()
