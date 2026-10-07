import hashlib
import re
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import Candidate, Job
from . import decision


def _normalise_email(value: str) -> str:
    return value.strip().casefold()


def _normalise_phone(value: str) -> str:
    return "".join(re.findall(r"\d", value))


def _resume_fingerprint(value: str) -> str:
    words = re.findall(r"[a-z0-9]+", value.casefold())
    return hashlib.sha256(" ".join(words).encode("utf-8")).hexdigest() if words else ""


def find_duplicates(db: Session, candidate: Candidate) -> list[dict]:
    email = _normalise_email(candidate.email)
    phone = _normalise_phone(candidate.phone)
    fingerprint = _resume_fingerprint(candidate.resume_text)
    if not any((email, phone, fingerprint)):
        return []

    matches: dict[int, dict] = defaultdict(lambda: {"reasons": set()})
    rows = db.scalars(select(Candidate).where(Candidate.id != candidate.id).limit(10000)).all()
    for existing in rows:
        if email and _normalise_email(existing.email) == email:
            matches[existing.id]["reasons"].add("email")
        if phone and len(phone) >= 7 and _normalise_phone(existing.phone) == phone:
            matches[existing.id]["reasons"].add("phone")
        if fingerprint and fingerprint == _resume_fingerprint(existing.resume_text):
            matches[existing.id]["reasons"].add("resume")

    return [
        {"candidate_id": candidate_id, "reasons": sorted(match["reasons"])}
        for candidate_id, match in sorted(matches.items())
    ]


def recommend_candidates(
    db: Session, job: Job, limit: int = 25, include_current_job: bool = False
) -> list[dict]:
    query = select(Candidate).where(Candidate.resume_text != "").order_by(Candidate.created_at.desc())
    if not include_current_job:
        query = query.where(Candidate.job_id != job.id)
    candidates = db.scalars(query.options(selectinload(Candidate.job)).limit(10000)).all()
    jobs = {candidate.job_id: candidate.job.title for candidate in candidates}
    ranked: list[dict] = []
    for candidate in candidates:
        if candidate.status in {"hired", "offered", "withdrawn"}:
            continue
        result = decision.screen(job, candidate.resume_text)
        ranked.append(
            {
                "candidate_id": candidate.id,
                "name": candidate.name or result.parsed["name"],
                "source": candidate.source,
                "current_job_id": candidate.job_id,
                "current_job_title": jobs.get(candidate.job_id, ""),
                "current_status": candidate.status,
                "score": result.score,
                "category": result.category,
                "confidence": result.confidence,
                "matched_skills": result.matched_skills,
                "missing_skills": result.missing_skills,
                "flags": result.flags,
                "score_breakdown": result.breakdown,
                "explanation": (
                    f"{len(result.matched_skills)} role skills matched; "
                    f"{len(result.missing_skills)} required skills missing. "
                    f"Experience fit: {result.breakdown['experience']:.0%}; "
                    f"text relevance: {result.breakdown['similarity']:.0%}."
                ),
            }
        )
    ranked.sort(key=lambda item: (item["score"], item["confidence"]), reverse=True)
    return ranked[:limit]
