"""Create a deterministic, synthetic recruitment demo without contacting external services."""

import argparse
import os
import random
import sys
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


def _default_database_url() -> str:
    return f"sqlite:///{(BACKEND_ROOT / 'demo.db').as_posix()}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", _default_database_url()))
    parser.add_argument("--jobs", type=int, default=100)
    parser.add_argument("--candidates", type=int, default=1000)
    parser.add_argument("--reset", action="store_true", help="Delete the target SQLite database before seeding.")
    args = parser.parse_args()
    if args.jobs < 2 or args.candidates < args.jobs:
        parser.error("--jobs must be at least 2 and --candidates must be >= --jobs")
    return args


def _reset_sqlite_database(database_url: str) -> None:
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise ValueError("--reset is supported only for a SQLite demo database")
    path = Path(parsed.path.lstrip("/"))
    if parsed.netloc:
        path = Path(f"//{parsed.netloc}{parsed.path}")
    elif len(parsed.path) > 2 and parsed.path[0] == "/" and parsed.path[2] == ":":
        path = Path(parsed.path[1:])
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()
    if path.exists():
        path.unlink()


def _synthetic_job(index: int, recruiter: str, rng: random.Random, model: dict) -> dict:
    title, department, required, preferred = model["roles"][index % len(model["roles"])]
    location = model["locations"][index % len(model["locations"])]
    experience_min = rng.randrange(0, 9)
    experience_max = experience_min + rng.randrange(2, 6)
    return {
        "title": title,
        "department": department,
        "location": location,
        "work_mode": ("remote", "hybrid", "onsite")[index % 3],
        "experience_min": experience_min,
        "experience_max": experience_max,
        "required_skills": list(required),
        "preferred_skills": list(preferred),
        "qualifications": f"{('Bachelor', 'Master', 'Diploma')[index % 3]} degree or equivalent experience",
        "salary_min": (700_000 + (index % 9) * 250_000),
        "salary_max": (1_200_000 + (index % 9) * 400_000),
        "currency": "INR",
        "openings": 1 + index % 5,
        "constraints": f"{location}; {('full-time', 'contract', 'full-time')[index % 3]}",
        "description": (
            f"{title} in {department}. Build and maintain production systems using "
            f"{', '.join(required)}; collaborate across the {department} organization."
        ),
        "channels": [("LinkedIn", "Company Careers Page", "Naukri", "Employee Referrals")[index % 4]],
        "status": ("published", "published", "published", "draft", "closed")[index % 5],
        "created_by": recruiter,
    }


def _resume(index: int, name: str, email: str, location: str, years: int | None, skills: list[str], model: dict) -> str:
    if index % 43 == 0:
        return f"{name}\n{email}\n{location}\nInterested in {skills[0]} opportunities."
    industry = model["industries"][index % len(model["industries"])]
    experience = (
        f"{years} years of experience delivering {industry} solutions"
        if years is not None
        else "Experience details available on request"
    )
    return (
        f"{name}\n{email}\n{location}\n{experience}. "
        f"Core skills: {', '.join(skills)}. "
        f"Delivered measurable improvements for {industry} teams, collaborated with product and operations, "
        f"and used {skills[0]} to deliver reliable services. "
        f"Education: {('B.Tech', 'M.Tech', 'B.Sc', 'MBA')[index % 4]} in {industry}. "
        f"Certifications: {('AWS Certified', 'PMP', 'Google Cloud', 'Scrum Master')[index % 4]}."
    )


def seed_demo(args: argparse.Namespace) -> None:
    if args.reset:
        _reset_sqlite_database(args.database_url)
    os.environ["DATABASE_URL"] = args.database_url
    os.environ["SEED_DEMO_DATA"] = "false"
    os.environ.pop("OPENAI_API_KEY", None)

    from sqlalchemy import select

    from app.db import Base, SessionLocal, engine
    from app.models import Approval, AuditLog, Candidate, Interview, Interviewer, Job, Offer, Setting, User, utcnow
    from app.seed import seed
    from app.services.decision import screen
    from app.services.matching import find_duplicates
    from app.services.recruitment import screen_candidate

    Base.metadata.create_all(engine)
    rng = random.Random(20261006)
    catalog = {
        "roles": [
            ("Backend Engineer", "Engineering", ["Python", "PostgreSQL", "Docker"], ["AWS", "FastAPI", "Kubernetes"]),
            ("Data Analyst", "Analytics", ["SQL", "Excel", "Power BI"], ["Python", "Tableau", "Statistics"]),
            ("Product Manager", "Product", ["Product Strategy", "Analytics", "Roadmapping"], ["SQL", "Agile", "Research"]),
            ("Security Engineer", "Security", ["Security", "Linux", "Networking"], ["Python", "AWS", "Terraform"]),
            ("UX Designer", "Design", ["Figma", "User Research", "Prototyping"], ["Accessibility", "Design Systems"]),
            ("Sales Manager", "Sales", ["B2B Sales", "CRM", "Negotiation"], ["Forecasting", "HubSpot", "Communication"]),
            ("Cloud Architect", "Infrastructure", ["AWS", "Terraform", "Kubernetes"], ["Python", "Networking", "Security"]),
            ("HR Business Partner", "People", ["Employee Relations", "Talent Strategy"], ["Analytics", "Coaching"]),
            ("QA Engineer", "Quality", ["Testing", "Automation", "Playwright"], ["Python", "CI/CD", "API Testing"]),
            ("Marketing Manager", "Marketing", ["Campaigns", "SEO", "Analytics"], ["HubSpot", "Content", "Research"]),
        ],
        "locations": [
            "Bengaluru", "Hyderabad", "Mumbai", "Pune", "Chennai", "Delhi", "Singapore", "London", "Toronto", "Remote"
        ],
        "industries": [
            "healthcare", "financial services", "retail", "education", "logistics", "SaaS", "manufacturing", "media"
        ],
        "first_names": [
            "Aarav", "Aditi", "Amara", "Anaya", "Arjun", "Dev", "Diya", "Ishaan", "Kavya", "Maya", "Neel",
            "Nisha", "Rohan", "Sana", "Vihaan", "Zoya",
        ],
        "last_names": [
            "Kapoor", "Iyer", "Joshi", "Khan", "Mehta", "Nair", "Patel", "Rao", "Shah", "Singh", "Verma", "Das",
        ],
        "skills": [
            "Python", "Java", "JavaScript", "TypeScript", "Go", "SQL", "PostgreSQL", "AWS", "Azure", "Docker",
            "Kubernetes", "Terraform", "FastAPI", "React", "Power BI", "Excel", "Tableau", "Figma", "Agile",
            "Product Strategy", "User Research", "Security", "Linux", "Networking", "Playwright", "CI/CD",
            "B2B Sales", "CRM", "Negotiation", "Analytics", "Statistics", "Machine Learning", "Communication",
        ],
        "stage_weights": [
            ("applied", 24),
            ("screened", 18),
            ("shortlisted", 13),
            ("interview_scheduled", 10),
            ("interviewed", 11),
            ("selected", 5),
            ("offered", 5),
            ("hired", 4),
            ("rejected", 6),
            ("declined", 2),
            ("withdrawn", 2),
        ],
    }

    with SessionLocal() as db:
        marker = db.get(Setting, "scaled_demo_seed_v1")
        if marker and not args.reset:
            print("Synthetic demo data already exists; use --reset to recreate the dedicated demo database.")
            return
        if not marker and db.scalars(select(User)).first():
            raise RuntimeError("Target database already contains data; use a fresh SQLite path or pass --reset.")
        seed(db)
        users = db.scalars(select(User).order_by(User.id)).all()
        recruiters = [user for user in users if user.role in {"admin", "recruiter"}]
        jobs = db.scalars(select(Job).order_by(Job.id)).all()
        missing_jobs = max(0, args.jobs - len(jobs))
        for index in range(missing_jobs):
            jobs.append(Job(**_synthetic_job(index, recruiters[index % len(recruiters)].name, rng, catalog)))
        db.add_all(jobs[len(jobs) - missing_jobs :] if missing_jobs else [])
        db.flush()

        existing_candidates = db.scalars(select(Candidate).order_by(Candidate.id)).all()
        for candidate in existing_candidates:
            if candidate.screened_at is None:
                screen_candidate(db, candidate.job, candidate, "demo-seed")

        interviewers = db.scalars(select(Interviewer).order_by(Interviewer.id)).all()
        candidates_to_create = max(0, args.candidates - len(existing_candidates))
        stage_names, stage_weights = zip(*catalog["stage_weights"], strict=True)
        cumulative = []
        total_weight = 0
        for weight in stage_weights:
            total_weight += weight
            cumulative.append(total_weight)
        now = utcnow()
        offers: list[Offer] = []
        interviews: list[Interview] = []
        activities: list[AuditLog] = []

        for offset in range(candidates_to_create):
            index = offset + len(existing_candidates) + 1
            job = jobs[(index - 1) % len(jobs)]
            first = catalog["first_names"][index % len(catalog["first_names"])]
            last = catalog["last_names"][(index // 3) % len(catalog["last_names"])]
            name = f"{first} {last} {index:04d}"
            email = f"candidate{index:04d}@example.test"
            if index % 50 == 0:
                email = f"candidate{index - 1:04d}@example.test"
            if index % 97 == 0:
                email = "not-an-email"
            location = catalog["locations"][index % len(catalog["locations"])]
            years = None if index % 43 == 0 else float(rng.randint(0, 18))
            if index % 61 == 0:
                years = 20.0
            skills = sorted(rng.sample(catalog["skills"], k=rng.randint(3, 8)))
            resume = _resume(index, name, email, location, int(years) if years is not None else None, skills, catalog)
            if index % 97 == 0 and index > 97:
                resume = existing_candidates[-1].resume_text
            candidate = Candidate(
                job_id=job.id,
                name=name,
                email=email,
                phone=f"+1-555-{index % 1000:03d}-{index % 10000:04d}",
                location=location,
                source=("LinkedIn", "Referral", "Careers Page", "Agency", "Indeed")[index % 5],
                resume_filename=f"synthetic_resume_{index:04d}.txt",
                resume_text=resume,
                status="applied",
                created_at=now - timedelta(days=rng.randint(1, 540)),
            )
            result = screen(job, resume)
            candidate.parsed = {
                **result.parsed,
                "certifications": [f"Certification {index % 7 + 1}"],
                "availability": "unavailable" if index % 23 == 0 else "available",
            }
            candidate.score = result.score
            candidate.score_breakdown = result.breakdown
            candidate.category = result.category
            candidate.confidence = result.confidence
            candidate.matched_skills = result.matched_skills
            candidate.missing_skills = result.missing_skills
            candidate.flags = list(result.flags)
            candidate.screened_at = candidate.created_at + timedelta(hours=rng.randint(1, 72))
            candidate.summary = (
                f"Structured demo profile with {years if years is not None else 'unreported'} years of experience; "
                f"{len(result.matched_skills)} role-related skills matched and {len(result.missing_skills)} required skills missing."
            )
            stage_roll = rng.randrange(total_weight)
            candidate.status = next(
                stage for stage, boundary in zip(stage_names, cumulative, strict=True) if stage_roll < boundary
            )
            if candidate.status in {
                "shortlisted",
                "interview_scheduled",
                "interviewed",
                "selected",
                "offered",
                "hired",
                "declined",
            }:
                candidate.shortlisted_at = candidate.screened_at + timedelta(days=rng.randint(1, 12))
            if candidate.status == "rejected":
                candidate.hr_note = ("Required experience not evidenced", "Role scope mismatch", "Candidate withdrew")[index % 3]
            duplicates = find_duplicates(db, candidate) if index % 43 == 0 or index % 50 == 0 or index % 97 == 0 else []
            if duplicates:
                candidate.flags = [*candidate.flags, f"Potential duplicate profile(s): {', '.join(str(d['candidate_id']) for d in duplicates[:5])}"]
            db.add(candidate)
            db.flush()
            activities.append(
                AuditLog(
                    ts=candidate.created_at,
                    actor=recruiters[index % len(recruiters)].name,
                    action="candidate_added",
                    entity_type="candidate",
                    entity_id=candidate.id,
                    details={"source": candidate.source, "synthetic": True},
                )
            )
            activities.append(
                AuditLog(
                    ts=candidate.screened_at,
                    actor="demo-agent",
                    action="candidate_screened",
                    entity_type="candidate",
                    entity_id=candidate.id,
                    details={
                        "score": candidate.score,
                        "category": candidate.category,
                        "confidence": candidate.confidence,
                        "prompt_version": "offline-demo-seed",
                    },
                )
            )

            if candidate.status in {"interview_scheduled", "interviewed", "selected", "offered", "hired"} and index % 3 != 0:
                cancelled = candidate.status == "interview_scheduled" and index % 11 == 0
                completed = candidate.status != "interview_scheduled"
                if cancelled:
                    candidate.status = "shortlisted"
                starts = candidate.shortlisted_at + timedelta(days=rng.randint(2, 14))
                interview = Interview(
                    job_id=job.id,
                    candidate_id=candidate.id,
                    interviewer_id=interviewers[index % len(interviewers)].id if interviewers else None,
                    round_name=("Technical", "Hiring Manager", "Portfolio Review")[index % 3],
                    start_time=starts,
                    end_time=starts + timedelta(hours=1),
                    status="cancelled" if cancelled else ("completed" if completed else "scheduled"),
                    questions=[{"category": "Technical", "skill": skills[0], "question": f"Describe your work with {skills[0]}."}],
                    checklist=["Role-related evidence", "Structured feedback", "Candidate questions"],
                    feedback=(
                        [
                            {
                                "rating": 3 + index % 3,
                                "recommendation": ("hire", "strong_hire", "no_hire")[index % 3],
                                "strengths": f"Demonstrated practical {skills[0]} experience",
                                "concerns": "Validate role scope and availability",
                                "submitted_by": "demo-manager",
                                "submitted_at": starts.isoformat(),
                            }
                        ]
                        if completed
                        else []
                    ),
                    feedback_summary="Synthetic structured feedback; hiring outcome requires human review." if completed else "",
                )
                interviews.append(interview)
                activities.append(
                    AuditLog(
                        ts=starts,
                        actor="demo-recruiter",
                        action=(
                            "interview_cancelled"
                            if cancelled
                            else ("interview_completed" if completed else "interview_scheduled")
                        ),
                        entity_type="candidate",
                        entity_id=candidate.id,
                        details={"round_name": interview.round_name, "synthetic": True},
                    )
                )
                if index % 71 == 0:
                    activities.append(
                        AuditLog(
                            ts=candidate.created_at,
                            actor="demo-calendar",
                            action="calendar_integration_failed",
                            entity_type="candidate",
                            entity_id=candidate.id,
                            details={"error_code": "synthetic_provider_unavailable", "retryable": True},
                        )
                    )
            if candidate.status in {"offered", "hired", "declined"}:
                offer_status = "accepted" if candidate.status == "hired" else candidate.status
                sent_at = candidate.shortlisted_at + timedelta(days=rng.randint(10, 35))
                offers.append(
                    Offer(
                        job_id=job.id,
                        candidate_id=candidate.id,
                        salary=(job.salary_min + job.salary_max) / 2,
                        currency=job.currency,
                        start_date=(now + timedelta(days=45)).date().isoformat(),
                        content="Synthetic demonstration offer; not a binding employment offer.",
                        status=offer_status,
                        created_at=sent_at - timedelta(hours=1),
                        sent_at=sent_at,
                        responded_at=sent_at + timedelta(days=rng.randint(1, 9)) if offer_status in {"accepted", "declined"} else None,
                    )
                )
            if index % 29 == 0 and candidate.status not in {"hired", "withdrawn"}:
                db.add(
                    Approval(
                        type="human_review",
                        title=f"Review synthetic profile #{candidate.id}",
                        job_id=job.id,
                        candidate_id=candidate.id,
                        payload={"suggested_category": candidate.category, "flags": candidate.flags},
                        rationale="Synthetic demonstration approval; a recruiter must decide.",
                        status="pending",
                        requested_by="demo-agent",
                        created_at=candidate.screened_at,
                    )
                )

        db.add_all(interviews)
        db.add_all(offers)
        db.add_all(activities)
        db.add(Setting(key="scaled_demo_seed_v1", value=f"jobs={args.jobs};candidates={args.candidates};seed=20261006"))
        db.commit()
        print(f"Seeded demo database: {len(jobs)} jobs, {len(existing_candidates) + candidates_to_create} applications.")
        print(
            f"Additional records: {len(interviews)} interviews, {len(offers)} offers, "
            f"{len(activities)} recruiter activity events, {len(stage_names)} pipeline stages."
        )
        print("All candidate records and contacts are synthetic; no external AI or mail/calendar service was contacted.")


if __name__ == "__main__":
    seed_demo(_parse_args())
