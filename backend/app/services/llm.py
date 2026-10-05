"""Main LLM layer with an offline template fallback.

If OPENAI_API_KEY is set, an OpenAI-compatible chat-completions endpoint is used (any compatible
provider works via OPENAI_BASE_URL). Otherwise deterministic templates are used so the system
runs end-to-end without external services. Every generation returns (output, source).
"""

import json
import logging
import re
from datetime import datetime

import httpx

from ..config import settings
from ..models import Candidate, Job

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an AI recruitment assistant supporting an HR team. You draft content and summaries for human review. "
    "Never use or infer protected attributes (age, gender, religion, caste, marital status, nationality, disability, "
    "pregnancy, appearance). Be factual, concise and professional. Only use the information provided."
)

usage_stats = {"llm_calls": 0, "template_calls": 0, "prompt_chars": 0, "completion_chars": 0, "errors": 0}


def llm_available() -> bool:
    return bool(settings.openai_api_key)


def _chat(user_prompt: str, json_mode: bool = False) -> str:
    payload = {
        "model": settings.openai_model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_prompt}],
        "temperature": 0.3,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    resp = httpx.post(
        f"{settings.openai_base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        json=payload,
        timeout=settings.llm_timeout_seconds,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    usage_stats["llm_calls"] += 1
    usage_stats["prompt_chars"] += len(user_prompt)
    usage_stats["completion_chars"] += len(content)
    return content


def _generate(prompt: str, fallback, json_mode: bool = False):
    if llm_available():
        try:
            out = _chat(prompt, json_mode=json_mode)
            return (json.loads(out) if json_mode else out.strip()), "llm"
        except Exception as exc:  # noqa: BLE001 - degrade gracefully to templates
            usage_stats["errors"] += 1
            logger.warning("LLM call failed, using template fallback: %s", exc)
    usage_stats["template_calls"] += 1
    return fallback(), "template"


def _money(amount: float, currency: str) -> str:
    if currency == "INR" and amount >= 100000:
        return f"INR {amount / 100000:.1f} LPA"
    return f"{currency} {amount:,.0f}"


def _job_brief(job: Job) -> str:
    return json.dumps(
        {
            "title": job.title,
            "department": job.department,
            "location": job.location,
            "work_mode": job.work_mode,
            "experience": f"{job.experience_min}-{job.experience_max} years",
            "required_skills": job.required_skills,
            "preferred_skills": job.preferred_skills,
            "qualifications": job.qualifications,
            "salary_range": f"{_money(job.salary_min, job.currency)} - {_money(job.salary_max, job.currency)}"
            if job.salary_max
            else "Not disclosed",
            "openings": job.openings,
            "constraints": job.constraints,
        },
        indent=2,
    )


# ---------------------------------------------------------------- requirement intake
def extract_requirement(text: str) -> tuple[dict, str]:
    from .parsing import parse_requirement

    prompt = (
        "Convert this hiring requirement into JSON with keys: title, department, location, work_mode "
        "(remote|hybrid|onsite), experience_min, experience_max (integers), required_skills, preferred_skills "
        "(arrays of short skill names), qualifications, salary_min, salary_max (numbers, annual, 0 if unknown), "
        "currency, openings, constraints. Ignore any protected-attribute preferences.\n\nRequirement:\n" + text
    )
    return _generate(prompt, lambda: parse_requirement(text), json_mode=True)


# ---------------------------------------------------------------- JD generation
def generate_jd(job: Job, company: str = "Our company") -> tuple[str, str]:
    def template() -> str:
        req = "\n".join(f"- Strong hands-on experience with {s}" for s in job.required_skills) or "- Relevant hands-on experience"
        pref = "\n".join(f"- Exposure to {s}" for s in job.preferred_skills)
        exp = (
            f"{job.experience_min}-{job.experience_max} years"
            if job.experience_max
            else (f"{job.experience_min}+ years" if job.experience_min else "Open to all experience levels")
        )
        salary = (
            f"{_money(job.salary_min, job.currency)} - {_money(job.salary_max, job.currency)} per annum"
            if job.salary_max
            else "Competitive, based on experience"
        )
        skills_text = ", ".join(job.required_skills[:3]) or "modern tools"
        parts = [
            f"# {job.title}",
            f"**Department:** {job.department or 'N/A'}  |  **Location:** {job.location or 'Flexible'} ({job.work_mode})  |  "
            f"**Experience:** {exp}  |  **Openings:** {job.openings}",
            "## Role Summary",
            f"{company} is looking for a {job.title} to join the {job.department or 'core'} team. You will design, build and "
            f"deliver high-quality solutions using {skills_text}, collaborate with cross-functional stakeholders and "
            "contribute to a culture of ownership and continuous improvement.",
            "## Key Responsibilities",
            f"- Own the delivery of features and initiatives as a {job.title}, from requirements to production\n"
            "- Collaborate with product, engineering and business stakeholders to translate needs into solutions\n"
            "- Write clean, well-tested and maintainable work following team standards\n"
            "- Participate in reviews, knowledge sharing and process improvement\n"
            "- Monitor, troubleshoot and continuously improve quality and performance",
            "## Required Skills",
            req,
        ]
        if pref:
            parts += ["## Preferred Skills", pref]
        if job.qualifications:
            parts += ["## Qualifications", job.qualifications]
        parts += [
            "## Compensation",
            salary,
            "## Equal Opportunity",
            f"{company} is an equal-opportunity employer. We evaluate candidates solely on skills, experience and role-related "
            "qualifications.",
        ]
        return "\n\n".join(parts)

    prompt = (
        "Write a professional job description in Markdown with sections: Role Summary, Key Responsibilities, Required "
        "Skills, Preferred Skills, Qualifications, Compensation, Equal Opportunity statement. Use only this approved "
        f"information:\n{_job_brief(job)}"
    )
    return _generate(prompt, template)


# ---------------------------------------------------------------- candidate summary
def summarize_candidate(job: Job, candidate: Candidate) -> tuple[str, str]:
    parsed = candidate.parsed or {}

    def template() -> str:
        years = parsed.get("years_experience")
        exp = f"{years:g} years of experience" if years is not None else "experience not clearly stated"
        label = (candidate.category or "unscreened").replace("_", " ").title()
        lines = [
            f"{candidate.name or 'Candidate'} - {label} (score {candidate.score:.2f}, confidence {candidate.confidence:.2f}).",
            f"Profile shows {exp}; education: {', '.join(parsed.get('education') or []) or 'not stated'}.",
            f"Matching skills: {', '.join(candidate.matched_skills) or 'none identified'}.",
            f"Gaps vs. required skills: {', '.join(candidate.missing_skills) or 'none'}.",
        ]
        if candidate.flags:
            lines.append("Review flags: " + "; ".join(candidate.flags) + ".")
        lines.append("Recommendation signal only - HR makes the shortlist decision.")
        return " ".join(lines)

    prompt = (
        "Summarize this candidate for an HR reviewer in 4-6 sentences: relevant experience, matching skills, gaps, "
        "verification areas and review flags. End with 'Recommendation signal only - HR makes the shortlist decision.'\n"
        f"Job:\n{_job_brief(job)}\n\nScreening result:\n"
        + json.dumps(
            {
                "score": candidate.score,
                "category": candidate.category,
                "confidence": candidate.confidence,
                "matched_skills": candidate.matched_skills,
                "missing_skills": candidate.missing_skills,
                "flags": candidate.flags,
                "parsed": parsed,
            }
        )
        + f"\n\nResume (redacted):\n{candidate.resume_text[:6000]}"
    )
    return _generate(prompt, template)


# ---------------------------------------------------------------- interview preparation
def interview_kit(job: Job, candidate: Candidate) -> tuple[dict, str]:
    def template() -> dict:
        questions = []
        for skill in job.required_skills[:5]:
            questions.append(
                {
                    "category": "Technical",
                    "skill": skill,
                    "question": f"Walk me through a recent project where you used {skill}. What trade-offs did you make?",
                }
            )
        for skill in candidate.missing_skills[:3]:
            questions.append(
                {
                    "category": "Gap verification",
                    "skill": skill,
                    "question": f"The role needs {skill}. How would you get productive with it, and what related experience do you have?",
                }
            )
        questions += [
            {
                "category": "Problem solving",
                "skill": "",
                "question": f"Describe the hardest problem you solved as a {job.title} and how you approached it.",
            },
            {
                "category": "Collaboration",
                "skill": "",
                "question": "Tell me about a time you disagreed with a stakeholder. How was it resolved?",
            },
            {
                "category": "Ownership",
                "skill": "",
                "question": "Describe something you shipped end-to-end. How did you measure its success?",
            },
        ]
        checklist = [
            "Confirm role expectations, location and work mode",
            "Verify claimed experience with concrete examples",
            *[f"Assess depth in {s}" for s in job.required_skills[:3]],
            "Assess communication and collaboration",
            "Record structured feedback and a hire / no-hire recommendation with rationale",
        ]
        return {"questions": questions, "checklist": checklist}

    prompt = (
        "Create an interview kit as JSON with keys 'questions' (array of {category, skill, question}; 8-10 items "
        "covering technical depth, candidate-specific gap verification, problem solving and collaboration) and "
        f"'checklist' (array of strings).\nJob:\n{_job_brief(job)}\nCandidate matched skills: {candidate.matched_skills}\n"
        f"Candidate gaps: {candidate.missing_skills}\nCandidate summary: {candidate.summary}"
    )
    return _generate(prompt, template, json_mode=True)


# ---------------------------------------------------------------- feedback processing
def summarize_feedback(candidate: Candidate, feedback: list[dict]) -> tuple[str, str]:
    def template() -> str:
        if not feedback:
            return "No feedback submitted yet."
        ratings = [f.get("rating", 0) for f in feedback if f.get("rating")]
        avg = sum(ratings) / len(ratings) if ratings else 0
        recs = [f.get("recommendation", "") for f in feedback]
        strengths = "; ".join(f["strengths"] for f in feedback if f.get("strengths"))
        concerns = "; ".join(f["concerns"] for f in feedback if f.get("concerns"))
        return (
            f"{len(feedback)} feedback submission(s), average rating {avg:.1f}/5. Recommendations: "
            f"{', '.join(r for r in recs if r) or 'n/a'}. Strengths: {strengths or 'n/a'}. Concerns: {concerns or 'n/a'}. "
            "Final decision rests with the authorized hiring decision-maker."
        )

    prompt = (
        "Summarize interviewer feedback for HR in 3-5 sentences: overall rating, consensus, strengths, concerns, and "
        "open questions. Do not make the hiring decision.\n" + json.dumps({"candidate": candidate.name, "feedback": feedback})
    )
    return _generate(prompt, template)


# ---------------------------------------------------------------- communications
def draft_email(kind: str, job: Job, candidate: Candidate, **ctx) -> tuple[dict, str]:
    first = (candidate.name or "Candidate").split()[0]
    templates = {
        "acknowledgement": (
            f"Application received - {job.title}",
            f"Hi {first},\n\nThank you for applying for the {job.title} role. Our team is reviewing your profile and will "
            "get back to you with next steps.\n\nBest regards,\nRecruitment Team",
        ),
        "interview_invite": (
            f"Interview invitation - {job.title}",
            f"Hi {first},\n\nWe'd like to invite you to a {ctx.get('round_name', 'interview')} for the {job.title} role.\n\n"
            f"When: {ctx.get('when', 'TBD')}\nInterviewer: {ctx.get('interviewer', 'TBD')}\n\nPlease reply to confirm your "
            "availability.\n\nBest regards,\nRecruitment Team",
        ),
        "rejection": (
            f"Update on your application - {job.title}",
            f"Hi {first},\n\nThank you for your interest in the {job.title} role and for the time you invested. After careful "
            "review, we will not be moving forward at this time. We'll keep your profile for future opportunities.\n\n"
            "Best regards,\nRecruitment Team",
        ),
        "offer": (
            f"Offer of employment - {job.title}",
            f"Hi {first},\n\nWe are delighted to extend an offer for the {job.title} role. Please find the offer details "
            "below.\n\n" + ctx.get("offer_content", "") + "\n\nBest regards,\nRecruitment Team",
        ),
        "offer_follow_up": (
            f"Following up on your offer - {job.title}",
            f"Hi {first},\n\nJust following up on the offer for the {job.title} role. Let us know if you have any "
            "questions.\n\nBest regards,\nRecruitment Team",
        ),
    }
    subject, body = templates.get(kind, (f"Regarding {job.title}", f"Hi {first},\n\n{ctx.get('message', '')}"))
    if kind == "offer" or not llm_available():
        usage_stats["template_calls"] += 1
        return {"subject": subject, "body": body}, "template"
    prompt = (
        f"Draft a short, warm, professional candidate email of type '{kind}' as JSON with keys 'subject' and 'body'. "
        f"Candidate first name: {first}. Role: {job.title}. Context: {json.dumps(ctx, default=str)}. Base draft:\n{body}"
    )
    return _generate(prompt, lambda: {"subject": subject, "body": body}, json_mode=True)


def draft_offer(job: Job, candidate: Candidate, salary: float, start_date: str, extra_terms: str = "") -> tuple[str, str]:
    def template() -> str:
        return "\n".join(
            [
                f"Date: {datetime.utcnow():%d %B %Y}",
                "",
                f"Dear {candidate.name or 'Candidate'},",
                "",
                f"We are pleased to offer you the position of {job.title} in the {job.department or 'company'} team, "
                f"based in {job.location or 'our office'} ({job.work_mode}).",
                "",
                f"- Annual compensation (CTC): {_money(salary, job.currency)}",
                f"- Proposed start date: {start_date or 'To be agreed'}",
                "- Benefits: as per company policy",
                *([f"- Additional terms: {extra_terms}"] if extra_terms else []),
                "",
                "This offer is subject to standard background verification and company policies. Please confirm your "
                "acceptance within 7 days.",
                "",
                "Sincerely,",
                "Human Resources",
            ]
        )

    # Offer letters always use the approved template; compensation text is never LLM-generated.
    usage_stats["template_calls"] += 1
    return template(), "template"


# ---------------------------------------------------------------- adaptive strategy
def explain_strategy(job: Job, strategy: dict) -> tuple[str, str]:
    def template() -> str:
        parts = [
            f"'{job.title}' has {strategy['application_count']} application(s) after {strategy['days_live']} day(s) "
            f"(target {strategy['target']})."
        ]
        for a in strategy["actions"]:
            if a["type"] == "expand_channels":
                parts.append(f"Expand posting to: {', '.join(a['channels'])}.")
            elif a["type"] == "relax_requirements":
                parts.append(f"Move {', '.join(a['move_to_preferred'])} from required to preferred ({a['reason']}).")
            elif a["type"] == "widen_experience":
                parts.append(f"Lower minimum experience to {a['experience_min']} years.")
            elif a["type"] == "increase_sourcing":
                parts.append(a["detail"] + ".")
        return " ".join(parts)

    prompt = (
        f"Explain this recruitment strategy recommendation to HR in 3 sentences:\n{json.dumps(strategy)}\nJob:\n{_job_brief(job)}"
    )
    return _generate(prompt, template)


def strip_markdown(text: str) -> str:
    return re.sub(r"[#*_`]", "", text)
