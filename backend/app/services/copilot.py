from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Candidate, Job
from .decision import text_similarity
from .parsing import parse_resume

RECRUITMENT_GUARDRAILS = (
    "Candidate ranking is decision support, not a hiring decision. Assess only job-related skills, experience, "
    "and qualifications. Protected characteristics must not influence screening."
)


def retrieve_context(db: Session, question: str, job_id: int | None = None, limit: int = 6) -> list[dict]:
    docs: list[dict] = [
        {
            "type": "policy",
            "id": "responsible-ai",
            "text": RECRUITMENT_GUARDRAILS,
            "excerpt": RECRUITMENT_GUARDRAILS,
        }
    ]
    jobs_query = select(Job).order_by(Job.created_at.desc()).limit(1000)
    if job_id is not None:
        jobs_query = jobs_query.where(Job.id == job_id)
    for job in db.scalars(jobs_query):
        text = " ".join(
            [
                job.title,
                job.department,
                job.status,
                job.location,
                " ".join(job.required_skills),
                " ".join(job.preferred_skills),
                job.description[:1200],
            ]
        )
        docs.append(
            {
                "type": "job",
                "id": job.id,
                "text": text,
                "excerpt": f"{job.title}: {', '.join(job.required_skills[:6]) or 'skills not specified'} ({job.status})",
            }
        )
    candidates_query = select(Candidate).order_by(Candidate.created_at.desc()).limit(5000)
    if job_id is not None:
        candidates_query = candidates_query.where(Candidate.job_id == job_id)
    for candidate in db.scalars(candidates_query):
        parsed = candidate.parsed or parse_resume(candidate.resume_text)
        skills = candidate.matched_skills or parsed.get("skills", [])
        text = " ".join(
            [
                candidate.status,
                candidate.category or "",
                " ".join(skills),
                " ".join(candidate.missing_skills or []),
                str(parsed.get("years_experience") or ""),
            ]
        )
        docs.append(
            {
                "type": "candidate",
                "id": candidate.id,
                "text": text,
                "excerpt": (
                    f"Candidate #{candidate.id}: {candidate.status}, score "
                    f"{candidate.score if candidate.score is not None else 'not screened'}, "
                    f"skills {', '.join(skills[:5]) or 'not parsed'}, "
                    f"confidence {candidate.confidence if candidate.confidence is not None else 'not available'}"
                ),
            }
        )
    ranked = sorted(
        (
            {**doc, "relevance": round(text_similarity(question, doc["text"]), 4)}
            for doc in docs
        ),
        key=lambda doc: doc["relevance"],
        reverse=True,
    )
    relevant = [doc for doc in ranked if doc["relevance"] > 0][:limit]
    if all(doc["type"] != "policy" for doc in relevant):
        relevant.append({"type": "policy", "id": "responsible-ai", "relevance": 0, "excerpt": RECRUITMENT_GUARDRAILS})
    return relevant[: limit + 1]
