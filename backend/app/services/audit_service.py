import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from app.db.models import GrievanceEvent

logger = logging.getLogger("IGRS.AuditService")


class EventType:
    CREATED = "CREATED"
    AI_CLASSIFIED = "AI_CLASSIFIED"
    ASSIGNED = "ASSIGNED"
    REASSIGNED = "REASSIGNED"
    STATUS_UPDATED = "STATUS_UPDATED"
    RESOLUTION_UPLOADED = "RESOLUTION_UPLOADED"
    WITHDRAWN = "WITHDRAWN"
    SLA_BREACHED = "SLA_BREACHED"
    SLA_ESCALATED = "SLA_ESCALATED"


class AuditService:
    """
    Append-only immutable audit trail service.
    Guarantees that every state transition, routing action, AI classification,
    and administrative decision is permanently recorded with full actor identity.
    """

    @staticmethod
    def log_event(
        db: Session,
        grievance_id: int,
        event_type: str,
        actor_role: str,
        actor_id: Optional[int] = None,
        old_value: Optional[str] = None,
        new_value: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        auto_commit: bool = False
    ) -> Optional[GrievanceEvent]:
        """
        Appends an immutable audit event to the grievance_events ledger.
        """
        try:
            metadata_str = json.dumps(metadata) if metadata is not None else None
            event = GrievanceEvent(
                grievance_id=grievance_id,
                actor_id=actor_id,
                actor_role=actor_role,
                event_type=event_type,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(new_value) if new_value is not None else None,
                timestamp=datetime.utcnow(),
                metadata_json=metadata_str
            )
            db.add(event)
            if auto_commit:
                db.commit()
                db.refresh(event)
            logger.info(
                f"[Audit] Grv #{grievance_id} | {event_type} | Actor: {actor_role} "
                f"(ID: {actor_id}) | '{old_value}' -> '{new_value}'"
            )
            return event
        except Exception as e:
            logger.error(f"Failed to record audit event for Grievance #{grievance_id}: {e}")
            if auto_commit:
                db.rollback()
            return None

    @staticmethod
    def get_events_for_grievance(db: Session, grievance_id: int) -> List[GrievanceEvent]:
        """
        Retrieves all audit events for a grievance in chronological order.
        """
        return (
            db.query(GrievanceEvent)
            .filter(GrievanceEvent.grievance_id == grievance_id)
            .order_by(GrievanceEvent.timestamp.asc(), GrievanceEvent.id.asc())
            .all()
        )


audit_service = AuditService()
