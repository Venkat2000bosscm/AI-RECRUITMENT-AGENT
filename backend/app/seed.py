from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Candidate, Interviewer, Job, User
from .services import recruitment

SAMPLES = Path(__file__).parent / "sample_data" / "resumes"


def seed(db: Session) -> None:
    if db.scalars(select(User)).first():
        return
    db.add_all(
        [
            User(name="Priya (Recruiter)", email="priya@example.com", role="recruiter"),
            User(name="Arjun (Hiring Manager)", email="arjun@example.com", role="hiring_manager"),
            User(name="Admin", email="admin@example.com", role="admin"),
            User(name="Viewer", email="viewer@example.com", role="viewer"),
            Interviewer(name="Rohit Gupta", email="rohit@example.com", expertise=["Python", "FastAPI", "AWS", "System Design"]),
            Interviewer(name="Divya Menon", email="divya@example.com", expertise=["Kubernetes", "Docker", "CI/CD", "Terraform"]),
            Interviewer(name="Sanjay Rao", email="sanjay@example.com", expertise=["SQL", "Power BI", "Data Analysis", "Python"]),
        ]
    )
    backend = Job(
        title="Senior Python Backend Engineer",
        department="Engineering",
        location="Bengaluru",
        work_mode="hybrid",
        experience_min=5,
        experience_max=8,
        required_skills=["Python", "FastAPI", "PostgreSQL", "AWS", "Docker"],
        preferred_skills=["Kubernetes", "Kafka", "Redis", "CI/CD"],
        qualifications="Bachelor's degree in Computer Science or equivalent experience",
        salary_min=2500000,
        salary_max=4000000,
        currency="INR",
        openings=2,
        constraints="Must be able to work hybrid from Bengaluru 3 days/week",
        created_by="Priya (Recruiter)",
        channels=["Company Careers Page", "LinkedIn"],
    )
    analyst = Job(
        title="Data Analyst",
        department="Business Intelligence",
        location="Hyderabad",
        work_mode="onsite",
        experience_min=2,
        experience_max=5,
        required_skills=["SQL", "Excel", "Power BI"],
        preferred_skills=["Python", "Tableau"],
        salary_min=800000,
        salary_max=1400000,
        currency="INR",
        created_by="Priya (Recruiter)",
    )
    db.add_all([backend, analyst])
    db.flush()
    recruitment.generate_jd(db, backend, "seed")
    recruitment.publish_job(db, backend, backend.channels, "seed")
    for path in sorted(SAMPLES.glob("*.txt")):
        db.add(Candidate(job_id=backend.id, resume_text=path.read_text(), source="LinkedIn", resume_filename=path.name))
    db.commit()
