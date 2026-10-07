import json

from sqlalchemy.orm import Session

from ..models import Setting

DEFAULT_STAGES = [
    {"key": "applied", "label": "Applied", "color": "#64748b"},
    {"key": "screened", "label": "Screened", "color": "#2563eb"},
    {"key": "shortlisted", "label": "Shortlisted", "color": "#7c3aed"},
    {"key": "interview_scheduled", "label": "Interview", "color": "#0891b2"},
    {"key": "interviewed", "label": "Interviewed", "color": "#0f766e"},
    {"key": "selected", "label": "Selected", "color": "#15803d"},
    {"key": "offered", "label": "Offered", "color": "#ca8a04"},
    {"key": "hired", "label": "Hired", "color": "#16a34a"},
    {"key": "rejected", "label": "Rejected", "color": "#dc2626"},
    {"key": "declined", "label": "Declined", "color": "#b91c1c"},
    {"key": "withdrawn", "label": "Withdrawn", "color": "#475569"},
]


def get_stages(db: Session) -> list[dict[str, str]]:
    setting = db.get(Setting, "pipeline_stages")
    if setting is None:
        return [stage.copy() for stage in DEFAULT_STAGES]
    stages = json.loads(setting.value)
    return stages


def save_stages(db: Session, stages: list[dict[str, str]]) -> list[dict[str, str]]:
    setting = db.get(Setting, "pipeline_stages")
    serialized = json.dumps(stages)
    if setting is None:
        db.add(Setting(key="pipeline_stages", value=serialized))
    else:
        setting.value = serialized
    return stages
