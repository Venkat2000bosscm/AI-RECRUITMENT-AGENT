from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..schemas import CopilotRequest
from ..services import guardrails, llm
from ..services.audit import log
from ..services.copilot import retrieve_context

router = APIRouter(prefix="/api/copilot", tags=["copilot"])


@router.post("/ask")
def ask(req: CopilotRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    guardrails.ensure_permission(user, "run_agent")
    evidence = retrieve_context(db, req.question, req.job_id)
    answer, source = llm.answer_copilot(req.question, evidence)
    log(
        db,
        user.name,
        "recruiter_copilot_queried",
        "job" if req.job_id else "system",
        req.job_id,
        prompt_version=llm.PROMPT_VERSION,
        model=llm.model_name(),
        source=source,
        evidence=[{"type": item["type"], "id": item["id"]} for item in evidence],
    )
    db.commit()
    return {
        "answer": answer,
        "mode": source,
        "prompt_version": llm.PROMPT_VERSION,
        "sources": [
            {key: item[key] for key in ("type", "id", "excerpt", "relevance") if key in item} for item in evidence
        ],
    }
