from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


# Grievance Schemas
class GrievanceCreate(BaseModel):
    description: str


class GrievanceResponse(BaseModel):
    id: int
    description: str
    category: Optional[str] = None
    priority: Optional[str] = None
    region: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    solution: Optional[str] = None
    status: Optional[str] = "Pending"
    processing_status: Optional[str] = "PENDING"
    retry_count: Optional[int] = 0
    last_error: Optional[str] = None
    processed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    
    # Feature 3: Routing & SLA fields
    assigned_officer_id: Optional[int] = None
    assigned_officer_name: Optional[str] = None
    sla_deadline: Optional[datetime] = None
    sla_breached: Optional[bool] = False
    escalated: Optional[bool] = False
    escalated_at: Optional[datetime] = None
    routing_score: Optional[float] = None
    routing_metadata: Optional[str] = None

    class Config:
        from_attributes = True


class GrievanceStatusResponse(BaseModel):
    id: int
    status: str
    processing_status: str
    retry_count: int
    last_error: Optional[str] = None
    processed_at: Optional[datetime] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    region: Optional[str] = None
    solution: Optional[str] = None

    # Feature 3: Routing & SLA fields
    assigned_officer_id: Optional[int] = None
    assigned_officer_name: Optional[str] = None
    sla_deadline: Optional[datetime] = None
    sla_breached: Optional[bool] = False
    escalated: Optional[bool] = False
    routing_score: Optional[float] = None

    class Config:
        from_attributes = True


class QueueStatsResponse(BaseModel):
    queue_name: str
    queue_size: int
    dlq_size: int
    backend: str
    active_worker: bool


# Feature 3: Officer & Routing Schemas
class OfficerCreate(BaseModel):
    name: str
    email: str
    password: str
    department: str
    region: str
    max_capacity: Optional[int] = 10


class OfficerResponse(BaseModel):
    id: int
    name: str
    email: str
    role: str
    department: Optional[str] = None
    region: Optional[str] = None
    max_capacity: int = 10
    is_active: bool = True
    active_cases: int = 0

    class Config:
        from_attributes = True


class CandidateScoreBreakdown(BaseModel):
    officer_id: int
    officer_name: str
    department: Optional[str] = None
    region: Optional[str] = None
    active_cases: int
    max_capacity: int
    category_score: float
    geo_score: float
    priority_score: float
    workload_penalty: float
    total_score: float
    eligible: bool
    disqualification_reason: Optional[str] = None


class RoutingResultResponse(BaseModel):
    grievance_id: int
    category: Optional[str] = None
    region: Optional[str] = None
    priority: Optional[str] = None
    assigned_officer_id: Optional[int] = None
    assigned_officer_name: Optional[str] = None
    routing_score: Optional[float] = None
    sla_deadline: Optional[datetime] = None
    candidates: List[CandidateScoreBreakdown] = []
    decision_summary: str


class ManualAssignRequest(BaseModel):
    officer_id: int
    reason: Optional[str] = None


class SLAEscalationReport(BaseModel):
    total_active_checked: int
    breached_count: int
    escalated_count: int
    reassigned_count: int
    details: List[Dict[str, Any]] = []


# Feature 4: Immutable Audit Trail & RBAC Schemas
class GrievanceEventResponse(BaseModel):
    id: int
    grievance_id: int
    actor_id: Optional[int] = None
    actor_name: Optional[str] = None
    actor_role: str
    event_type: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    timestamp: datetime
    metadata_json: Optional[str] = None

    class Config:
        from_attributes = True


class GrievanceAuditTrailResponse(BaseModel):
    grievance_id: int
    current_status: str
    assigned_officer_id: Optional[int] = None
    assigned_officer_name: Optional[str] = None
    total_events: int
    events: List[GrievanceEventResponse] = []


class WithdrawGrievanceRequest(BaseModel):
    reason: Optional[str] = "Grievance withdrawn by citizen"


class UploadResolutionRequest(BaseModel):
    solution: str = Field(..., min_length=5, description="Official resolution description and corrective action taken")
    remarks: Optional[str] = None
    action_taken: Optional[str] = None


class UpdateStatusRequest(BaseModel):
    status: str = Field(..., description="Target grievance status e.g. In Progress, Under Review, Resolved, Closed")
    remarks: Optional[str] = None


class ReassignGrievanceRequest(BaseModel):
    officer_id: int
    reason: Optional[str] = "Reassigned by administrator"
