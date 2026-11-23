import uuid
from typing import Any

from app.models.audit import AuditLog
from sqlalchemy.orm import Session


def record_audit(
    db: Session,
    *,
    action: str,
    actor_user_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    request_id: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        action=action,
        actor_user_id=actor_user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        before_json=before,
        after_json=after,
        reason=reason,
        request_id=request_id,
    )
    db.add(entry)
    db.flush()  # get ID without committing — caller controls transaction
    return entry
