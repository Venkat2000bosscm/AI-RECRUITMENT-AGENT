from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditLog


def log(
    db: Session,
    actor: str,
    action: str,
    entity_type: str = "",
    entity_id: int | None = None,
    **details: Any,
) -> AuditLog:
    entry = AuditLog(actor=actor, action=action, entity_type=entity_type, entity_id=entity_id, details=details)
    db.add(entry)
    return entry
