from sqlalchemy import Column, Integer, String, Text, DateTime, Enum, ForeignKey, Index, Boolean, Float
from sqlalchemy.orm import relationship
from datetime import datetime
from typing import Optional
import enum
from .connection import Base


#User Role
class UserRole(str, enum.Enum):
    user = "user"
    admin = "admin"
    officer = "officer"
    
#User Table
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(150), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.user)
    department = Column(String(100), nullable=True, index=True)
    region = Column(String(150), nullable=True, index=True)
    max_capacity = Column(Integer, default=10)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<User(name={self.name}, role={self.role}, dept={self.department})>"
    

class Grievance(Base):
    __tablename__ = "grievances"
    __table_args__ = (
        Index("idx_grievance_category", "category"),
        Index("idx_grievance_created_at", "created_at"),
        Index("idx_grievance_region", "region"),
        Index("idx_grievance_status_priority", "status", "priority"),
        Index("idx_grievance_assigned_officer", "assigned_officer_id"),
        Index("idx_grievance_sla_deadline", "sla_deadline"),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    description = Column(Text)
    category = Column(String(100))
    priority = Column(String(50))
    region = Column(String(150))
    latitude = Column(String(50))
    longitude = Column(String(50))
    solution = Column(Text)
    status = Column(String(50), default="Pending")
    processing_status = Column(String(50), default="PENDING", index=True)
    retry_count = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
    processed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", foreign_keys=[user_id], backref="grievances")

    # Feature 3: Automated Grievance Routing & SLA Load-Balancing
    assigned_officer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    assigned_officer = relationship("User", foreign_keys=[assigned_officer_id], backref="assigned_cases")
    sla_deadline = Column(DateTime, nullable=True)
    sla_breached = Column(Boolean, default=False)
    escalated = Column(Boolean, default=False)
    escalated_at = Column(DateTime, nullable=True)
    routing_score = Column(Float, nullable=True)
    routing_metadata = Column(Text, nullable=True)

    # Feature 4: Immutable Audit Trail
    events = relationship("GrievanceEvent", back_populates="grievance", cascade="all, delete-orphan", order_by="GrievanceEvent.timestamp.asc()")

    @property
    def assigned_officer_name(self) -> Optional[str]:
        return self.assigned_officer.name if self.assigned_officer else None


class GrievanceEvent(Base):
    """
    Immutable audit trail for grievances.
    Maintains an append-only sequence of lifecycle events:
    creation, AI classification, routing, reassignments, status transitions,
    resolutions, withdrawals, and SLA breaches/escalations.
    """
    __tablename__ = "grievance_events"
    __table_args__ = (
        Index("idx_grievance_events_grv", "grievance_id"),
        Index("idx_grievance_events_type", "event_type"),
        Index("idx_grievance_events_timestamp", "timestamp"),
        Index("idx_grievance_events_actor", "actor_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    grievance_id = Column(Integer, ForeignKey("grievances.id", ondelete="CASCADE"), nullable=False)
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_role = Column(String(50), nullable=False)  # citizen, officer, admin, ai_worker, system
    event_type = Column(String(50), nullable=False)  # CREATED, AI_CLASSIFIED, ASSIGNED, REASSIGNED, STATUS_UPDATED, RESOLUTION_UPLOADED, WITHDRAWN, SLA_BREACHED, SLA_ESCALATED
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    metadata_json = Column(Text, nullable=True)

    grievance = relationship("Grievance", back_populates="events")
    actor = relationship("User", foreign_keys=[actor_id])

    @property
    def actor_name(self) -> Optional[str]:
        if self.actor:
            return self.actor.name
        if self.actor_role in ["ai_worker", "ai"]:
            return "AI Worker (Gemini 2.0)"
        if self.actor_role in ["system", "routing_engine"]:
            return "System (Routing Engine)"
        return self.actor_role.capitalize() if self.actor_role else "System"

    def __repr__(self):
        return f"<GrievanceEvent(grv_id={self.grievance_id}, type={self.event_type}, role={self.actor_role}, time={self.timestamp})>"
