"""Decision layer: fast, explainable structured decisions (matching, classification, routing, escalation).

Runs before any expensive LLM call, following the proposal's cost pattern:
low-cost processing -> decision layer -> LLM only when necessary -> human review for uncertain cases.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from ..config import settings
from ..models import Candidate, Job
from .guardrails import redact_resume
from .parsing import canonical_skill, parse_resume

STRONG = "strong_match"
PARTIAL = "partial_match"
WEAK = "weak_match"
HUMAN_REVIEW = "human_review"

_STOPWORDS = set(
    "a an and are as at be by for from has have in is it its of on or that the to was were will with you your we our "
    "this their they he she i my me role team work working years year experience".split()
)


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z][a-z0-9+#.]{1,}", text.lower()) if t not in _STOPWORDS]


def text_similarity(a: str, b: str) -> float:
    """Cosine similarity of term-frequency vectors with log damping (lightweight retrieval signal)."""
    ta, tb = Counter(_tokens(a)), Counter(_tokens(b))
    if not ta or not tb:
        return 0.0
    va = {k: 1 + math.log(v) for k, v in ta.items()}
    vb = {k: 1 + math.log(v) for k, v in tb.items()}
    dot = sum(va[k] * vb[k] for k in va.keys() & vb.keys())
    norm = math.sqrt(sum(v * v for v in va.values())) * math.sqrt(sum(v * v for v in vb.values()))
    return dot / norm if norm else 0.0


def job_profile_text(job: Job) -> str:
    return " ".join(
        [job.title, job.description, " ".join(job.required_skills), " ".join(job.preferred_skills), job.qualifications]
    )


@dataclass
class ScreeningResult:
    parsed: dict
    score: float
    breakdown: dict
    category: str
    confidence: float
    matched_skills: list[str]
    missing_skills: list[str]
    flags: list[str] = field(default_factory=list)


def experience_fit(years: float | None, minimum: int, maximum: int) -> float:
    if years is None:
        return 0.5
    if minimum <= 0 or years >= minimum:
        if maximum and years > maximum + 5:
            return 0.85
        return 1.0
    return max(0.0, years / minimum)


def classify(score: float) -> str:
    if score >= settings.strong_match_threshold:
        return STRONG
    if score >= settings.partial_match_threshold:
        return PARTIAL
    return WEAK


def screen(job: Job, resume_text: str) -> ScreeningResult:
    clean_text, redacted = redact_resume(resume_text)
    parsed = parse_resume(clean_text, job.required_skills + job.preferred_skills)
    cand_skills = {s.lower() for s in parsed["skills"]}

    required = [canonical_skill(s) for s in job.required_skills]
    preferred = [canonical_skill(s) for s in job.preferred_skills]
    matched_req = [s for s in required if s.lower() in cand_skills]
    matched_pref = [s for s in preferred if s.lower() in cand_skills]
    missing = [s for s in required if s.lower() not in cand_skills]

    req_score = len(matched_req) / len(required) if required else 1.0
    pref_score = len(matched_pref) / len(preferred) if preferred else None
    exp_score = experience_fit(parsed["years_experience"], job.experience_min, job.experience_max)
    sim = text_similarity(clean_text, job_profile_text(job))
    sim_score = min(1.0, sim / 0.35)  # cosine of resumes vs JD rarely exceeds ~0.35

    weights = {"required_skills": 0.5, "preferred_skills": 0.15, "experience": 0.2, "similarity": 0.15}
    components = {"required_skills": req_score, "experience": exp_score, "similarity": sim_score}
    if pref_score is None:
        weights["required_skills"] += weights.pop("preferred_skills")
    else:
        components["preferred_skills"] = pref_score
    score = sum(weights[k] * components[k] for k in weights)

    flags: list[str] = []
    confidence = (
        0.6
        + min(min(abs(score - t) for t in (settings.strong_match_threshold, settings.partial_match_threshold)), 0.15)
        / 0.15
        * 0.35
    )
    if parsed["years_experience"] is None:
        flags.append("Experience could not be determined from resume")
        confidence -= 0.15
    if len(clean_text) < 300:
        flags.append("Resume is very short / possibly incomplete")
        confidence -= 0.2
    if not parsed["email"]:
        flags.append("No contact email found")
        confidence -= 0.05
    if not parsed["education"] and job.qualifications:
        flags.append("Qualifications not found in resume")
    if redacted:
        flags.append("Personal attributes redacted and excluded from scoring")
    if job.experience_max and parsed["years_experience"] and parsed["years_experience"] > job.experience_max + 5:
        flags.append("Experience well above stated range - check role fit/expectations")
    confidence = round(max(0.05, min(0.99, confidence)), 2)

    category = classify(score)
    if confidence < settings.min_confidence:
        flags.append(f"Low confidence ({confidence:.2f}) - routed to human review")
        category = HUMAN_REVIEW

    breakdown = {k: round(v, 3) for k, v in components.items()}
    breakdown["weights"] = weights
    return ScreeningResult(
        parsed=parsed,
        score=round(score, 3),
        breakdown=breakdown,
        category=category,
        confidence=confidence,
        matched_skills=matched_req + matched_pref,
        missing_skills=missing,
        flags=flags,
    )


def effective_category(candidate: Candidate) -> str | None:
    return candidate.hr_category_override or candidate.category


def application_strategy(job: Job, application_count: int, now: datetime | None = None) -> dict | None:
    """Adaptive strategy: recommend changes when application volume is low after publishing."""
    if job.status != "published" or job.published_at is None:
        return None
    now = now or datetime.utcnow()
    days_live = (now - job.published_at).total_seconds() / 86400
    target = settings.low_application_threshold
    if application_count >= target:
        return None
    if days_live < 3 and application_count > 0:
        return None
    current = set(job.channels or [])
    suggestions = [c for c in ["LinkedIn", "Naukri", "Indeed", "Employee Referrals", "Company Careers Page"] if c not in current]
    actions = []
    if suggestions:
        actions.append({"type": "expand_channels", "channels": suggestions[:2]})
    if len(job.required_skills) > 5:
        actions.append(
            {"type": "relax_requirements", "move_to_preferred": job.required_skills[5:], "reason": "Too many must-have skills"}
        )
    if job.experience_min >= 5:
        actions.append({"type": "widen_experience", "experience_min": max(0, job.experience_min - 1)})
    actions.append({"type": "increase_sourcing", "detail": "Run targeted sourcing / referral campaign"})
    return {
        "application_count": application_count,
        "target": target,
        "days_live": round(days_live, 1),
        "actions": actions,
    }
