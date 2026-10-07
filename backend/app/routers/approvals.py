from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agent.workflow import run_agent
from ..db import get_db
from ..deps import current_user
from ..models import Approval, User
from ..schemas import ApprovalOut, DecisionRequest
from ..services import guardrails, recruitment

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


@router.get("", response_model=list[ApprovalOut])
def list_approvals(
    status: str | None = "pending",
    job_id: int | None = None,
    candidate_id: int | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    q = select(Approval).order_by(Approval.created_at.desc())
    if status and status != "all":
        q = q.where(Approval.status == status)
    if job_id:
        q = q.where(Approval.job_id == job_id)
    if candidate_id:
        q = q.where(Approval.candidate_id == candidate_id)
    return db.scalars(q.offset(offset).limit(limit)).all()


@router.post("/{approval_id}/decide", response_model=ApprovalOut)
def decide(
    approval_id: int,
    req: DecisionRequest,
    continue_agent: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    guardrails.ensure_permission(user, "decide_approval")
    approval = db.get(Approval, approval_id)
    if approval is None:
        raise HTTPException(404, "Approval not found")
    guardrails.ensure_can_decide(user, approval.type)
    recruitment.decide_approval(db, approval, req.approved, f"{user.name} ({user.role})", req.comment, req.overrides)
    db.commit()
    if continue_agent and approval.job_id and not guardrails.is_agent_paused(db):
        run_agent(db, approval.job_id)
    return approval
