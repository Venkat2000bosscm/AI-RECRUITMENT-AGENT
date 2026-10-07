from datetime import datetime, timedelta, timezone

from tests.conftest import RECRUITER


def test_candidate_search_is_filtered_and_paginated(client):
    response = client.get("/api/candidates/search?job_id=1&q=python&page=1&page_size=3")

    assert response.status_code == 200
    result = response.json()
    assert result["page"] == 1
    assert result["page_size"] == 3
    assert result["total"] >= len(result["items"]) > 0
    assert len(result["items"]) <= 3
    assert all(candidate["job_id"] == 1 for candidate in result["items"])


def test_candidate_search_rejects_invalid_pagination(client):
    assert client.get("/api/candidates/search?page=0").status_code == 422
    assert client.get("/api/candidates/search?min_score=0.8&max_score=0.2").status_code == 422


def test_duplicate_detection_does_not_merge_profiles(client):
    created = client.post(
        "/api/jobs/1/candidates",
        json={
            "resume_text": "Synthetic profile for duplicate detection",
            "name": "Demo Candidate",
            "email": "same@example.test",
            "source": "manual",
        },
        headers=RECRUITER,
    )
    assert created.status_code == 200, created.text
    duplicate = client.post(
        "/api/jobs/2/candidates",
        json={
            "resume_text": "A distinct resume to retain a separate application",
            "name": "Demo Candidate",
            "email": "SAME@example.test",
            "source": "manual",
        },
        headers=RECRUITER,
    )
    assert duplicate.status_code == 200, duplicate.text

    result = client.get(f"/api/candidates/{duplicate.json()['id']}/duplicates")
    assert result.status_code == 200
    assert result.json()["duplicates"] == [{"candidate_id": created.json()["id"], "reasons": ["email"]}]


def test_recommendations_return_explainable_cross_job_matches(client):
    response = client.get("/api/jobs/2/recommendations?limit=5")

    assert response.status_code == 200
    results = response.json()
    assert results
    assert len(results) <= 5
    assert all(result["current_job_id"] != 2 for result in results)
    assert all(
        {"required_skills", "experience", "similarity", "weights", "contributions"}
        <= set(result["score_breakdown"])
        for result in results
    )
    assert all(result["explanation"] for result in results)


def test_pipeline_stages_are_configurable_without_removing_workflow_stages(client):
    existing = client.get("/api/pipeline/stages").json()["stages"]
    existing.append({"key": "reference_check", "label": "Reference check", "color": "#455566"})

    saved = client.put("/api/pipeline/stages", json={"stages": existing}, headers=RECRUITER)

    assert saved.status_code == 200
    assert saved.json()["stages"][-1]["key"] == "reference_check"
    candidate = client.get("/api/jobs/1/candidates?limit=1").json()[0]
    moved = client.post(
        f"/api/candidates/{candidate['id']}/override",
        json={"status": "reference_check", "note": "Reference process started"},
        headers=RECRUITER,
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["status"] == "reference_check"


def test_pipeline_configuration_cannot_remove_builtin_stages(client):
    stages = client.get("/api/pipeline/stages").json()["stages"][1:]
    response = client.put("/api/pipeline/stages", json={"stages": stages}, headers=RECRUITER)
    assert response.status_code == 422


def test_production_mode_fails_closed_without_identity_provider(client, monkeypatch):
    from app import deps
    from app.config import Settings

    production_settings = Settings(demo_mode=False, seed_demo_data=False, auto_create_schema=False)
    monkeypatch.setattr(deps, "settings", production_settings)

    assert client.get("/api/health").status_code == 200
    response = client.get("/api/candidates/search")
    assert response.status_code == 503
    assert "authentication is not configured" in response.json()["detail"]


def test_copilot_retrieves_recruitment_evidence_and_audits_sources(client):
    response = client.post(
        "/api/copilot/ask",
        json={"question": "What candidates match Python skills?", "job_id": 1},
        headers=RECRUITER,
    )

    assert response.status_code == 200
    result = response.json()
    assert result["answer"]
    assert result["mode"] == "template"
    assert result["prompt_version"]
    assert any(source["type"] == "candidate" for source in result["sources"])
    assert any(row["action"] == "recruiter_copilot_queried" for row in client.get("/api/audit").json())


def test_analytics_include_funnel_source_effectiveness_and_job_scope(client):
    created = client.post(
        "/api/jobs/2/candidates?screen=false",
        json={"resume_text": "Synthetic analyst profile", "name": "Analyst Demo", "email": "analyst@example.test"},
        headers=RECRUITER,
    )
    assert created.status_code == 200, created.text
    global_summary = client.get("/api/analytics/summary").json()
    job_summary = client.get("/api/analytics/summary?job_id=1").json()

    assert global_summary["funnel"]
    assert global_summary["source_effectiveness"]
    assert "LinkedIn" in global_summary["source_effectiveness"]
    assert global_summary["candidates"]["total"] > job_summary["candidates"]["total"] >= 8
    assert isinstance(job_summary["upcoming_interviews"], int)


def test_candidate_timeline_includes_screening_and_related_approvals(client):
    assert client.post("/api/jobs/1/screen", headers=RECRUITER).status_code == 200
    candidate = client.get("/api/jobs/1/candidates?limit=1").json()[0]

    result = client.get(f"/api/candidates/{candidate['id']}/timeline")

    assert result.status_code == 200
    assert any(event["type"] == "candidate_screened" for event in result.json()["events"])


def test_invalid_email_is_visible_as_failed_outbox_delivery(client):
    created = client.post(
        "/api/jobs/1/candidates",
        json={"resume_text": "Synthetic profile", "name": "No Email Candidate", "email": "not-an-email"},
        headers=RECRUITER,
    )
    assert created.status_code == 200

    sent = client.post(
        f"/api/candidates/{created.json()['id']}/email",
        json={"kind": "general", "message": "Demo"},
        headers=RECRUITER,
    )

    assert sent.status_code == 200
    assert sent.json() == {"ok": False, "status": "failed"}


def test_llm_candidate_summary_prompt_omits_direct_identifiers(monkeypatch):
    from app.models import Candidate, Job
    from app.services import llm

    prompts = []
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(llm, "_chat", lambda prompt, json_mode=False: prompts.append(prompt) or "Summary")
    job = Job(
        title="Backend Engineer",
        department="Engineering",
        location="Remote",
        work_mode="remote",
        experience_min=3,
        experience_max=6,
        required_skills=["Python"],
        preferred_skills=["PostgreSQL"],
        qualifications="",
        salary_min=0,
        salary_max=0,
        currency="INR",
        openings=1,
        constraints="",
    )
    candidate = Candidate(
        name="Sensitive Person Name",
        email="person@example.test",
        resume_text="Sensitive Person Name; person@example.test; private raw resume text",
        parsed={"years_experience": 5, "education": ["Bachelor's"], "email": "person@example.test"},
        score=0.8,
        category="strong_match",
        confidence=0.9,
        matched_skills=["Python"],
        missing_skills=[],
        flags=[],
    )

    llm.summarize_candidate(job, candidate)

    assert len(prompts) == 1
    assert "person@example.test" not in prompts[0]
    assert "Sensitive Person Name" not in prompts[0]
    assert "private raw resume text" not in prompts[0]
    assert '"years_experience": 5' in prompts[0]


def _propose_and_approve_interview(client, candidate_id):
    moved = client.post(
        f"/api/candidates/{candidate_id}/override",
        json={"status": "shortlisted"},
        headers=RECRUITER,
    )
    assert moved.status_code == 200, moved.text
    proposed = client.post(
        f"/api/candidates/{candidate_id}/interviews",
        json={"round_name": "Technical"},
        headers=RECRUITER,
    )
    assert proposed.status_code == 200, proposed.text
    [approval] = [
        approval
        for approval in client.get(f"/api/approvals?candidate_id={candidate_id}").json()
        if approval["type"] == "interview_schedule"
    ]
    return approval


def test_concurrent_approval_cannot_double_book_interviewer(client):
    candidates = client.get("/api/jobs/1/candidates?limit=2").json()
    first_approval = _propose_and_approve_interview(client, candidates[0]["id"])
    first_start = first_approval["payload"]["start_time"]
    scheduled = client.post(
        f"/api/approvals/{first_approval['id']}/decide",
        json={"approved": True},
        headers=RECRUITER,
    )
    assert scheduled.status_code == 200, scheduled.text

    second_approval = _propose_and_approve_interview(client, candidates[1]["id"])
    collision = client.post(
        f"/api/approvals/{second_approval['id']}/decide",
        json={"approved": True, "overrides": {"start_time": first_start}},
        headers=RECRUITER,
    )
    assert collision.status_code == 409
    assert "no longer available" in collision.json()["detail"]


def test_interview_reschedule_normalizes_timezone_and_can_be_cancelled(client):
    candidate = client.get("/api/jobs/1/candidates?limit=1").json()[0]
    approval = _propose_and_approve_interview(client, candidate["id"])
    scheduled = client.post(
        f"/api/approvals/{approval['id']}/decide",
        json={"approved": True},
        headers=RECRUITER,
    )
    interview_id = scheduled.json()["payload"]["interview_id"]
    local_start = (datetime.now(timezone.utc) + timedelta(days=30)).astimezone(
        timezone(timedelta(hours=5, minutes=30))
    )

    rescheduled = client.post(
        f"/api/interviews/{interview_id}/reschedule",
        json={"start_time": local_start.isoformat()},
        headers=RECRUITER,
    )
    assert rescheduled.status_code == 200, rescheduled.text
    stored = datetime.fromisoformat(rescheduled.json()["start_time"])
    assert stored == local_start.astimezone(timezone.utc).replace(tzinfo=None)

    cancelled = client.post(
        f"/api/interviews/{interview_id}/cancel",
        json={"reason": "Candidate requested a later date"},
        headers=RECRUITER,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
