from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(ORM):
    id: int
    name: str
    email: str
    role: str


class JobBase(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    department: str = Field(default="", max_length=120)
    location: str = Field(default="", max_length=120)
    work_mode: str = Field(default="hybrid", pattern="^(remote|hybrid|onsite)$")
    experience_min: int = Field(default=0, ge=0, le=60)
    experience_max: int = Field(default=0, ge=0, le=60)
    required_skills: list[str] = []
    preferred_skills: list[str] = []
    qualifications: str = ""
    salary_min: float = 0
    salary_max: float = 0
    currency: str = "INR"
    openings: int = 1
    constraints: str = ""
    channels: list[str] = []


class JobCreate(JobBase):
    pass


class JobUpdate(BaseModel):
    title: str | None = None
    department: str | None = None
    location: str | None = None
    work_mode: str | None = None
    experience_min: int | None = None
    experience_max: int | None = None
    required_skills: list[str] | None = None
    preferred_skills: list[str] | None = None
    qualifications: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    currency: str | None = None
    openings: int | None = None
    constraints: str | None = None
    description: str | None = None
    channels: list[str] | None = None


class JobOut(JobBase, ORM):
    id: int
    description: str
    status: str
    agent_paused: bool
    created_by: str
    created_at: datetime
    published_at: datetime | None
    candidate_count: int = 0
    pipeline: dict[str, int] = {}


class IntakeRequest(BaseModel):
    text: str = Field(min_length=3, max_length=20000)


class CandidateCreate(BaseModel):
    resume_text: str = Field(min_length=1, max_length=1_000_000)
    name: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=320)
    source: str = Field(default="manual", max_length=60)


class CandidateOut(ORM):
    id: int
    job_id: int
    name: str
    email: str
    phone: str
    location: str
    source: str
    resume_filename: str
    score: float | None
    category: str | None
    hr_category_override: str | None
    confidence: float | None
    matched_skills: list[str]
    missing_skills: list[str]
    flags: list[str]
    summary: str
    status: str
    created_at: datetime
    screened_at: datetime | None


class CandidateSearchPage(BaseModel):
    items: list[CandidateOut]
    total: int
    page: int
    page_size: int


class CandidateDetail(CandidateOut):
    resume_text: str
    parsed: dict
    score_breakdown: dict
    hr_note: str


class OverrideRequest(BaseModel):
    category: str | None = None
    status: str | None = None
    note: str = ""


class ApprovalOut(ORM):
    id: int
    type: str
    title: str
    job_id: int | None
    candidate_id: int | None
    payload: dict
    rationale: str
    status: str
    requested_by: str
    decided_by: str | None
    decision_comment: str
    created_at: datetime
    decided_at: datetime | None


class DecisionRequest(BaseModel):
    approved: bool
    comment: str = ""
    overrides: dict = Field(default_factory=dict)


class InterviewerOut(ORM):
    id: int
    name: str
    email: str
    expertise: list[str]


class InterviewOut(ORM):
    id: int
    job_id: int
    candidate_id: int
    interviewer_id: int | None
    round_name: str
    start_time: datetime | None
    end_time: datetime | None
    status: str
    questions: list[dict]
    checklist: list[str]
    feedback: list[dict]
    feedback_summary: str
    candidate_name: str = ""
    interviewer_name: str = ""
    job_title: str = ""


class ProposeInterviewRequest(BaseModel):
    interviewer_id: int | None = None
    round_name: str = "Technical"


class FeedbackRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    recommendation: str = Field(pattern="^(strong_hire|hire|no_hire|strong_no_hire)$")
    strengths: str = ""
    concerns: str = ""
    notes: str = ""


class InterviewRescheduleRequest(BaseModel):
    start_time: str = Field(min_length=10, max_length=40)


class InterviewCancelRequest(BaseModel):
    reason: str = Field(default="", max_length=500)


class OfferDraftRequest(BaseModel):
    salary: float | None = Field(default=None, ge=0)
    start_date: str = Field(default="", max_length=20)
    extra_terms: str = Field(default="", max_length=2000)


class OfferOut(ORM):
    id: int
    job_id: int
    candidate_id: int
    salary: float
    currency: str
    start_date: str
    content: str
    status: str
    created_at: datetime
    sent_at: datetime | None
    responded_at: datetime | None
    candidate_name: str = ""
    job_title: str = ""


class OfferResponseRequest(BaseModel):
    accepted: bool


class OnboardingTaskOut(ORM):
    id: int
    candidate_id: int
    title: str
    owner: str
    status: str


class OnboardingUpdate(BaseModel):
    status: str = Field(pattern="^(pending|in_progress|done)$")


class EmailOut(ORM):
    id: int
    to: str
    subject: str
    body: str
    kind: str
    job_id: int | None
    candidate_id: int | None
    status: str
    created_at: datetime


class AuditOut(ORM):
    id: int
    ts: datetime
    actor: str
    action: str
    entity_type: str
    entity_id: int | None
    details: dict


class AgentRunOut(ORM):
    id: int
    job_id: int
    started_at: datetime
    steps: list[dict]
    outcome: str


class EmailRequest(BaseModel):
    kind: str = Field(
        default="general",
        pattern="^(general|acknowledgement|interview_invite|interview_cancelled|rejection|offer|offer_follow_up)$",
    )
    message: str = Field(default="", max_length=5000)


class PauseRequest(BaseModel):
    paused: bool


class PipelineStage(BaseModel):
    key: str = Field(pattern="^[a-z][a-z0-9_]{1,39}$")
    label: str = Field(min_length=1, max_length=60)
    color: str = Field(pattern="^#[0-9a-fA-F]{6}$")


class PipelineStagesRequest(BaseModel):
    stages: list[PipelineStage] = Field(min_length=1, max_length=20)


class CopilotRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    job_id: int | None = Field(default=None, ge=1)
