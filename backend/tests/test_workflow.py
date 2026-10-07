from tests.conftest import ADMIN, MANAGER, RECRUITER, VIEWER


def pending(client, type_):
    return [a for a in client.get("/api/approvals").json() if a["type"] == type_]


def decide(client, approval_id, approved=True, headers=RECRUITER, **overrides):
    r = client.post(f"/api/approvals/{approval_id}/decide", json={"approved": approved, "overrides": overrides}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_new_job_requires_jd_approval_before_publish(client):
    intake = client.post(
        "/api/jobs/intake", json={"text": "Need a Python developer with 3-5 years in FastAPI and AWS, remote"}, headers=RECRUITER
    ).json()
    assert "Python" in intake["requirement"]["required_skills"]
    job = client.post(
        "/api/jobs", json={"title": "Python Developer", "required_skills": ["Python", "FastAPI"]}, headers=RECRUITER
    ).json()
    run = client.post(f"/api/jobs/{job['id']}/agent/run", headers=RECRUITER).json()
    assert [s["action"] for s in run["steps"] if s["phase"] == "planning"][:2] == ["draft_jd", "request_jd_approval"]
    job = client.get(f"/api/jobs/{job['id']}").json()
    assert job["status"] == "pending_approval" and "Python Developer" in job["description"]
    [approval] = [a for a in pending(client, "jd_publication") if a["job_id"] == job["id"]]
    decide(client, approval["id"])
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "published"


def test_protected_criteria_rejected(client):
    r = client.post("/api/jobs", json={"title": "Engineer", "constraints": "Only unmarried women under 30"}, headers=RECRUITER)
    assert r.status_code == 422


def test_rbac(client):
    assert client.post("/api/jobs", json={"title": "Valid title"}, headers=VIEWER).status_code == 403


def test_full_pipeline_to_onboarding(client):
    run = client.post("/api/jobs/1/agent/run", headers=RECRUITER).json()
    assert "shortlist" in run["outcome"]
    [shortlist] = pending(client, "shortlist")
    top = shortlist["payload"]["candidate_ids"][0]
    decide(client, shortlist["id"], candidate_ids=[top])  # HR edits the shortlist; agent continues automatically
    cand = client.get(f"/api/candidates/{top}").json()
    assert cand["status"] == "shortlisted"

    [interview_approval] = [a for a in pending(client, "interview_schedule") if a["candidate_id"] == top]
    decide(client, interview_approval["id"])
    [interview] = client.get(f"/api/candidates/{top}/interviews").json()
    assert interview["status"] == "scheduled" and interview["questions"]
    assert any(e["kind"] == "interview_invite" for e in client.get(f"/api/emails?candidate_id={top}").json())

    r = client.post(
        f"/api/interviews/{interview['id']}/feedback",
        json={"rating": 5, "recommendation": "strong_hire", "strengths": "Deep Python"},
        headers=MANAGER,
    )
    assert r.status_code == 200 and r.json()["feedback_summary"]

    [hiring] = [a for a in pending(client, "hiring_decision") if a["candidate_id"] == top]
    assert client.post(f"/api/approvals/{hiring['id']}/decide", json={"approved": True}, headers=RECRUITER).status_code == 403
    decide(client, hiring["id"], headers=MANAGER)  # agent drafts the offer next
    [offer_approval] = [a for a in pending(client, "offer") if a["candidate_id"] == top]
    decide(client, offer_approval["id"], headers=MANAGER, salary=3200000)
    [offer] = client.get(f"/api/offers?candidate_id={top}").json()
    assert offer["status"] == "sent" and offer["salary"] == 3200000 and "32.0 LPA" in offer["content"]

    client.post(f"/api/offers/{offer['id']}/response", json={"accepted": True}, headers=RECRUITER)
    [onboarding] = [a for a in pending(client, "onboarding") if a["candidate_id"] == top]
    decide(client, onboarding["id"], headers=ADMIN)
    tasks = client.get(f"/api/candidates/{top}/onboarding").json()
    assert len(tasks) == 6 and client.get(f"/api/candidates/{top}").json()["status"] == "hired"
    summary = client.get("/api/analytics/summary").json()
    assert summary["offers"]["accepted"] == 1
    assert any(a["action"] == "approval_approved" for a in client.get("/api/audit").json())


def test_pause_stops_agent(client):
    client.post("/api/agent/pause", json={"paused": True}, headers=RECRUITER)
    run = client.post("/api/jobs/1/agent/run", headers=RECRUITER).json()
    assert run["outcome"] == "Agent is paused by HR"


def test_upload_resume(client):
    files = {
        "files": (
            "cand.txt",
            b"Asha Rao\nasha@example.com\nBackend engineer with 6 years of experience in Python, FastAPI, PostgreSQL, AWS and Docker. B.Tech CSE. Built REST APIs and microservices. "
            * 4,
            "text/plain",
        )
    }
    r = client.post("/api/jobs/1/candidates/upload", files=files, headers=RECRUITER)
    assert r.status_code == 200, r.text
    assert r.json()[0]["category"] == "strong_match"
