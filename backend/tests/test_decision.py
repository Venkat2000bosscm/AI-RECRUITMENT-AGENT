from app.models import Job
from app.services import decision, guardrails, parsing


def make_job(**kw):
    defaults = dict(
        title="Backend Engineer",
        description="",
        qualifications="",
        experience_min=3,
        experience_max=6,
        required_skills=["Python", "FastAPI", "PostgreSQL"],
        preferred_skills=["Docker"],
    )
    return Job(**{**defaults, **kw})


def test_extract_skills_aliases_and_boundaries():
    skills = parsing.extract_skills("Worked with Postgres, k8s, ReactJS and node.js. Java developer, not javascript")
    assert {"PostgreSQL", "Kubernetes", "React", "Node.js", "Java", "JavaScript"} <= set(skills)
    assert "Go" not in parsing.extract_skills("Ready to go the extra mile")


def test_years_experience_explicit_and_ranges():
    assert parsing.extract_years_experience("Engineer with 7 years of experience") == 7
    assert parsing.extract_years_experience("Acme (2015 - 2018)\nBeta (2018 - 2021)") == 6


def test_education_detection():
    assert parsing.extract_education("B.E. Information Technology") == ["Bachelor's"]
    assert "Master's" in parsing.extract_education("M.Tech Computer Science")


def test_screen_strong_and_weak():
    job = make_job()
    strong = decision.screen(
        job, "Jane Doe\njane@x.com\n5 years of experience building Python FastAPI services on PostgreSQL with Docker. " * 3
    )
    assert strong.category == decision.STRONG
    assert not strong.missing_skills
    weak = decision.screen(job, "John\njohn@x.com\nSales executive with 6 years of experience in retail account management. " * 4)
    assert weak.category == decision.WEAK
    assert set(weak.missing_skills) == {"Python", "FastAPI", "PostgreSQL"}


def test_low_confidence_routes_to_human_review():
    result = decision.screen(make_job(), "Python developer.")
    assert result.category == decision.HUMAN_REVIEW
    assert any("human review" in f for f in result.flags)


def test_protected_attributes_redacted_and_detected():
    text, redacted = guardrails.redact_resume("Name\nDate of Birth: 01/01/1990\nGender: Female\nPython")
    assert redacted and "1990" not in text and "Female" not in text
    assert guardrails.find_protected_criteria("Prefer male candidates under 30") == ["age", "gender"]
