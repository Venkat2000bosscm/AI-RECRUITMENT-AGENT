"""Guardrail layer: tool permissions, role checks, pause controls and fairness safeguards."""

import re

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import Job, Setting, User

PROTECTED_ATTRIBUTE_PATTERNS = {
    "age": r"\b(age|aged|years old|date of birth|dob|young|younger|under \d{2})\b",
    "gender": r"\b(gender|male|female|man|woman|men|women|sex)\b",
    "marital_status": r"\b(marital status|married|unmarried|single|divorced|spouse)\b",
    "religion": r"\b(religion|religious|hindu|muslim|christian|sikh|jain|buddhist)\b",
    "caste": r"\b(caste|community)\b",
    "nationality": r"\b(nationality|native of)\b",
    "pregnancy": r"\b(pregnan\w*|maternity)\b",
    "disability": r"\b(disabilit\w*|handicap\w*)\b",
    "photo": r"\b(photo|photograph|appearance|looks)\b",
}

RESUME_REDACTION_PATTERN = re.compile(
    r"^\s*(date of birth|dob|age|gender|sex|marital status|religion|caste|nationality|"
    r"father'?s name|mother'?s name|spouse)\s*[:\-].*$",
    re.IGNORECASE | re.MULTILINE,
)

# Tool / action policy. "roles" = who may perform it; "approval" = requires a human approval record.
ACTION_POLICY: dict[str, dict] = {
    "create_job": {"roles": {"admin", "recruiter", "hiring_manager"}, "approval": False},
    "edit_job": {"roles": {"admin", "recruiter", "hiring_manager"}, "approval": False},
    "publish_job": {"roles": {"admin", "recruiter", "hiring_manager"}, "approval": True},
    "add_candidate": {"roles": {"admin", "recruiter"}, "approval": False},
    "screen_candidates": {"roles": {"admin", "recruiter"}, "approval": False},
    "override_candidate": {"roles": {"admin", "recruiter", "hiring_manager"}, "approval": False},
    "shortlist": {"roles": {"admin", "recruiter", "hiring_manager"}, "approval": True},
    "schedule_interview": {"roles": {"admin", "recruiter"}, "approval": True},
    "submit_feedback": {"roles": {"admin", "recruiter", "hiring_manager"}, "approval": False},
    "hiring_decision": {"roles": {"admin", "hiring_manager"}, "approval": True},
    "draft_offer": {"roles": {"admin", "recruiter", "hiring_manager"}, "approval": False},
    "offer": {"roles": {"admin", "hiring_manager"}, "approval": True},
    "onboarding": {"roles": {"admin", "recruiter", "hiring_manager"}, "approval": True},
    "decide_approval": {"roles": {"admin", "recruiter", "hiring_manager"}, "approval": False},
    "run_agent": {"roles": {"admin", "recruiter", "hiring_manager"}, "approval": False},
    "pause_agent": {"roles": {"admin", "recruiter", "hiring_manager"}, "approval": False},
    "send_email": {"roles": {"admin", "recruiter", "hiring_manager"}, "approval": False},
}

# Approval types that only specific roles may decide.
APPROVAL_DECIDER_ROLES: dict[str, set[str]] = {
    "hiring_decision": {"admin", "hiring_manager"},
    "offer": {"admin", "hiring_manager"},
}
DEFAULT_DECIDER_ROLES = {"admin", "recruiter", "hiring_manager"}


def ensure_permission(user: User, action: str) -> None:
    policy = ACTION_POLICY.get(action)
    if policy is None or user.role not in policy["roles"]:
        raise HTTPException(status_code=403, detail=f"Role '{user.role}' is not permitted to perform '{action}'.")


def ensure_can_decide(user: User, approval_type: str) -> None:
    allowed = APPROVAL_DECIDER_ROLES.get(approval_type, DEFAULT_DECIDER_ROLES)
    if user.role not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Role '{user.role}' cannot decide '{approval_type}' approvals (requires {sorted(allowed)}).",
        )


def find_protected_criteria(text: str) -> list[str]:
    """Return protected attributes referenced in hiring criteria (must not be used for filtering)."""
    lowered = text.lower()
    return sorted(attr for attr, pattern in PROTECTED_ATTRIBUTE_PATTERNS.items() if re.search(pattern, lowered))


def redact_resume(text: str) -> tuple[str, bool]:
    """Strip personal-attribute lines from resume text before scoring / LLM use."""
    redacted, count = RESUME_REDACTION_PATTERN.subn("[redacted personal attribute]", text)
    return redacted, count > 0


def is_globally_paused(db: Session) -> bool:
    setting = db.get(Setting, "agent_paused")
    return bool(setting and setting.value == "true")


def set_global_pause(db: Session, paused: bool) -> None:
    setting = db.get(Setting, "agent_paused")
    if setting is None:
        db.add(Setting(key="agent_paused", value="true" if paused else "false"))
    else:
        setting.value = "true" if paused else "false"


def is_agent_paused(db: Session, job: Job | None = None) -> bool:
    return is_globally_paused(db) or bool(job and job.agent_paused)
