from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any

from app.db import models, schemas, connection
from app.services.nlp_processor import process_grievance
from app.auth.dependencies import get_current_user, require_admin


router = APIRouter(prefix="/grievance", tags=["Grievance"])


from app.queue.queue_service import queue_service
from app.queue.worker import _worker_thread
from app.cache.cache_service import cache_service

from app.auth.dependencies import (
    get_current_user,
    require_admin,
    require_officer_or_admin,
    get_actor_role_str,
    enforce_grievance_access
)
from app.services.audit_service import audit_service, EventType


#Submit a new grievance (Citizen only) - Asynchronous via Message Queue
@router.post("/submit", response_model=schemas.GrievanceResponse, status_code=201)
def submit_grievance(
    grievance: schemas.GrievanceCreate,
    db: Session = Depends(connection.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Asynchronous grievance submission:
    1. Persists initial grievance in PostgreSQL with status=Pending, processing_status=PENDING.
    2. Records CREATED event in the immutable audit trail.
    3. Publishes job to Message Queue (Redis / in-memory worker).
    4. Returns response immediately (<50ms) without blocking on Gemini/NLP.
    """
    try:
        new_grievance = models.Grievance(
            description=grievance.description,
            user_id=current_user.id,
            status="Pending",
            processing_status="PENDING",
            retry_count=0
        )

        db.add(new_grievance)
        db.commit()
        db.refresh(new_grievance)

        # Feature 4: Record creation in immutable audit trail
        role_str = get_actor_role_str(current_user)
        audit_service.log_event(
            db=db,
            grievance_id=new_grievance.id,
            event_type=EventType.CREATED,
            actor_role=role_str,
            actor_id=current_user.id,
            old_value=None,
            new_value="Pending",
            metadata={"description": new_grievance.description[:300]},
            auto_commit=True
        )

        # Enqueue for asynchronous AI processing
        queue_service.enqueue(grievance_id=new_grievance.id)

        return new_grievance

    except Exception as e:
        print(f"Error while submitting grievance: {e}")
        raise HTTPException(status_code=500, detail="Failed to submit grievance")


#Check async processing status of a grievance
@router.get("/{grievance_id}/status", response_model=schemas.GrievanceStatusResponse)
def get_grievance_status(
    grievance_id: int,
    db: Session = Depends(connection.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Allows tracking the processing status (PENDING -> PROCESSING -> COMPLETED / FAILED)
    of a submitted grievance.
    """
    grievance = db.query(models.Grievance).filter(models.Grievance.id == grievance_id).first()
    if not grievance:
        raise HTTPException(status_code=404, detail="Grievance not found")

    # Enforce server-side ownership: owner citizen, assigned officer, or admin
    enforce_grievance_access(grievance, current_user, action="view status of")

    return grievance


#Citizen-only: Withdraw own grievance
@router.post("/{grievance_id}/withdraw", response_model=schemas.GrievanceResponse)
def withdraw_own_grievance(
    grievance_id: int,
    withdraw_data: Optional[schemas.WithdrawGrievanceRequest] = None,
    db: Session = Depends(connection.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Allows a citizen to withdraw their own submitted grievance.
    Strict server-side ownership enforcement prevents modifying other users' grievances.
    Cannot withdraw if already Resolved, Closed, or Withdrawn.
    Permanently records WITHDRAWN in the immutable audit trail.
    """
    grievance = db.query(models.Grievance).filter(models.Grievance.id == grievance_id).first()
    if not grievance:
        raise HTTPException(status_code=404, detail="Grievance not found")

    role_str = get_actor_role_str(current_user)
    if role_str == "citizen" and grievance.user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Citizens can only withdraw their own grievances"
        )
    elif role_str not in ["citizen", "admin"]:
        raise HTTPException(
            status_code=403,
            detail="Only the complaint owner or an administrator can withdraw this grievance"
        )

    if grievance.status in ["Resolved", "Closed", "Withdrawn"]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot withdraw grievance #{grievance_id} because it is already '{grievance.status}'"
        )

    old_status = grievance.status
    grievance.status = "Withdrawn"
    db.commit()
    db.refresh(grievance)

    reason = withdraw_data.reason if withdraw_data and withdraw_data.reason else "Withdrawn by citizen"
    audit_service.log_event(
        db=db,
        grievance_id=grievance.id,
        event_type=EventType.WITHDRAWN,
        actor_role=role_str,
        actor_id=current_user.id,
        old_value=old_status,
        new_value="Withdrawn",
        metadata={"reason": reason},
        auto_commit=True
    )

    try:
        cache_service.delete_pattern("analytics:*")
    except Exception:
        pass

    return grievance


#Admin-only: Message Queue Health & Metrics
@router.get("/queue/stats", response_model=schemas.QueueStatsResponse)
def get_queue_stats(
    admin=Depends(require_admin)
):
    """
    Returns message queue depth, DLQ count, and worker status.
    """
    stats = queue_service.get_stats()
    stats["active_worker"] = _worker_thread is not None and _worker_thread.is_alive()
    return stats


#Admin-only: Retry a failed grievance from DLQ
@router.post("/{grievance_id}/retry")
def retry_failed_grievance(
    grievance_id: int,
    db: Session = Depends(connection.get_db),
    admin=Depends(require_admin)
):
    """
    Manually re-enqueues a failed grievance for AI processing.
    """
    grievance = db.query(models.Grievance).filter(models.Grievance.id == grievance_id).first()
    if not grievance:
        raise HTTPException(status_code=404, detail="Grievance not found")

    grievance.processing_status = "PENDING"
    grievance.retry_count = 0
    grievance.last_error = None
    db.commit()

    queue_service.enqueue(grievance_id=grievance.id)
    return {"message": f"Grievance #{grievance_id} re-enqueued for AI processing."}


#Get all grievances for the logged-in user (Citizen)
@router.get("/my-grievances", response_model=List[schemas.GrievanceResponse])
def get_my_grievances(
    db: Session = Depends(connection.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Fetch all grievances submitted by the currently logged-in citizen.
    """
    grievances = db.query(models.Grievance).filter(
        models.Grievance.user_id == current_user.id
    ).order_by(models.Grievance.created_at.desc()).all()
    return grievances


#Admin-only: View all grievances
@router.get("/all", response_model=List[schemas.GrievanceResponse])
def get_all_grievances(
    db: Session = Depends(connection.get_db),
    admin=Depends(require_admin)
):
    """
    Allows admin to view all grievances in the system.
    """
    grievances = db.query(models.Grievance).order_by(models.Grievance.created_at.desc()).all()
    return grievances




#Officer & Admin: Update grievance status (Strict RBAC & Audit Logging)
@router.put("/{grievance_id}/status")
def update_grievance_status(
    grievance_id: int,
    status_data: Optional[schemas.UpdateStatusRequest] = None,
    status: Optional[str] = None,
    db: Session = Depends(connection.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Update grievance status.
    - Officer: Can ONLY update grievances assigned to their queue.
    - Admin: Can update any grievance in the system.
    - Citizen: Forbidden (403).
    Permanently records the status change in the immutable audit trail.
    """
    grievance = db.query(models.Grievance).filter(models.Grievance.id == grievance_id).first()
    if not grievance:
        raise HTTPException(status_code=404, detail="Grievance not found")

    target_status = status_data.status if status_data and status_data.status else status
    if not target_status:
        raise HTTPException(status_code=400, detail="Target status is required")

    role_str = get_actor_role_str(current_user)
    if role_str == "citizen":
        raise HTTPException(
            status_code=403,
            detail="Citizens cannot modify grievance status"
        )
    if role_str == "officer":
        if grievance.assigned_officer_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="Officers can only update grievances assigned to their own queue"
            )

    old_status = grievance.status
    grievance.status = target_status
    db.commit()

    # Record in immutable audit trail
    remarks = status_data.remarks if status_data else None
    audit_service.log_event(
        db=db,
        grievance_id=grievance.id,
        event_type=EventType.STATUS_UPDATED,
        actor_role=role_str,
        actor_id=current_user.id,
        old_value=old_status,
        new_value=target_status,
        metadata={"remarks": remarks},
        auto_commit=True
    )

    # Invalidate analytics cache
    try:
        cache_service.delete_pattern("analytics:*")
    except Exception:
        pass

    return {
        "message": f"Grievance ID {grievance_id} updated from '{old_status}' to '{target_status}'.",
        "grievance_id": grievance_id,
        "old_status": old_status,
        "new_status": target_status
    }


#Officer & Admin: Upload official resolution report
@router.post("/{grievance_id}/resolution", response_model=schemas.GrievanceResponse)
def upload_grievance_resolution(
    grievance_id: int,
    resolution_data: schemas.UploadResolutionRequest,
    db: Session = Depends(connection.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Allows assigned officer (or admin) to upload resolution details and mark status as 'Resolved'.
    Strict server-side validation:
    - Officer can ONLY resolve complaints assigned to them.
    - Citizen cannot upload resolution (403).
    Permanently records RESOLUTION_UPLOADED event in immutable audit trail.
    """
    grievance = db.query(models.Grievance).filter(models.Grievance.id == grievance_id).first()
    if not grievance:
        raise HTTPException(status_code=404, detail="Grievance not found")

    role_str = get_actor_role_str(current_user)
    if role_str == "citizen":
        raise HTTPException(
            status_code=403,
            detail="Citizens cannot upload resolution reports"
        )
    if role_str == "officer":
        if grievance.assigned_officer_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="Officers can only resolve grievances assigned to their own queue"
            )

    old_status = grievance.status
    grievance.solution = resolution_data.solution
    grievance.status = "Resolved"
    db.commit()
    db.refresh(grievance)

    audit_service.log_event(
        db=db,
        grievance_id=grievance.id,
        event_type=EventType.RESOLUTION_UPLOADED,
        actor_role=role_str,
        actor_id=current_user.id,
        old_value=old_status,
        new_value="Resolved",
        metadata={
            "solution": resolution_data.solution,
            "remarks": resolution_data.remarks,
            "action_taken": resolution_data.action_taken
        },
        auto_commit=True
    )

    try:
        cache_service.delete_pattern("analytics:*")
    except Exception:
        pass

    return grievance


# =========================================================================
# Feature 3: Automated Grievance Routing, Officer Workload & SLA Engine
# =========================================================================
from app.services.routing_engine import routing_engine, TERMINAL_STATUSES
from app.auth.dependencies import require_officer_or_admin
from app.auth.utils import hash_password


# Officer Management: List all officers & active workloads (Admin only)
@router.get("/officers", response_model=List[schemas.OfficerResponse])
def get_officers(
    db: Session = Depends(connection.get_db),
    admin: models.User = Depends(require_admin)
):
    """
    Returns all registered department officers, their jurisdiction,
    maximum case capacity, and real-time active workload.
    """
    return routing_engine.get_all_officers_with_workload(db)


# Officer Management: Create / Register a new officer (Admin only)
@router.post("/officers", response_model=schemas.OfficerResponse, status_code=201)
def create_officer(
    officer_in: schemas.OfficerCreate,
    db: Session = Depends(connection.get_db),
    admin: models.User = Depends(require_admin)
):
    """
    Registers a new department officer with jurisdiction region, department,
    and concurrent capacity limit.
    """
    existing = db.query(models.User).filter(models.User.email == officer_in.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Officer with this email already exists")

    new_officer = models.User(
        name=officer_in.name,
        email=officer_in.email,
        password_hash=hash_password(officer_in.password),
        role=models.UserRole.officer,
        department=officer_in.department,
        region=officer_in.region,
        max_capacity=officer_in.max_capacity or 10,
        is_active=True
    )
    db.add(new_officer)
    db.commit()
    db.refresh(new_officer)

    return {
        "id": new_officer.id,
        "name": new_officer.name,
        "email": new_officer.email,
        "role": new_officer.role.value if hasattr(new_officer.role, "value") else str(new_officer.role),
        "department": new_officer.department,
        "region": new_officer.region,
        "max_capacity": new_officer.max_capacity,
        "is_active": new_officer.is_active,
        "active_cases": 0
    }


# Officer View: Fetch grievances assigned to the logged-in officer
@router.get("/assigned-to-me", response_model=List[schemas.GrievanceResponse])
def get_assigned_to_me(
    db: Session = Depends(connection.get_db),
    current_user: models.User = Depends(require_officer_or_admin)
):
    """
    Retrieves all open grievances currently assigned to the authenticated officer.
    """
    assigned = db.query(models.Grievance).filter(
        models.Grievance.assigned_officer_id == current_user.id
    ).order_by(models.Grievance.created_at.desc()).all()
    return assigned


# Automated Routing: Evaluate candidate scores and route/re-route a grievance
@router.post("/{grievance_id}/auto-route", response_model=schemas.RoutingResultResponse)
def auto_route_grievance(
    grievance_id: int,
    db: Session = Depends(connection.get_db),
    admin: models.User = Depends(require_admin)
):
    """
    Runs the automated routing engine on a grievance. Evaluates all eligible officers
    based on Category Match (50), Geographic Match (30), Priority Capability (20),
    and Active Workload Penalty (-40). Assigns the highest scorer and sets the SLA deadline.
    """
    grievance = db.query(models.Grievance).filter(models.Grievance.id == grievance_id).first()
    if not grievance:
        raise HTTPException(status_code=404, detail="Grievance not found")

    officer, score, candidates, summary = routing_engine.find_best_officer(
        db=db,
        category=grievance.category,
        region=grievance.region,
        priority=grievance.priority
    )

    if officer:
        routing_engine.route_grievance(db, grievance, auto_commit=True)

    return {
        "grievance_id": grievance.id,
        "category": grievance.category,
        "region": grievance.region,
        "priority": grievance.priority,
        "assigned_officer_id": grievance.assigned_officer_id,
        "assigned_officer_name": grievance.assigned_officer_name,
        "routing_score": grievance.routing_score,
        "sla_deadline": grievance.sla_deadline,
        "candidates": candidates,
        "decision_summary": summary
    }


# Manual Assignment: Administrative override to assign a specific officer
@router.post("/{grievance_id}/assign")
def assign_grievance_officer(
    grievance_id: int,
    assignment: schemas.ManualAssignRequest,
    db: Session = Depends(connection.get_db),
    admin: models.User = Depends(require_admin)
):
    """
    Allows an administrator to manually assign or override officer assignment.
    """
    grievance = db.query(models.Grievance).filter(models.Grievance.id == grievance_id).first()
    if not grievance:
        raise HTTPException(status_code=404, detail="Grievance not found")

    try:
        officer = routing_engine.assign_manually(
            db=db,
            grievance=grievance,
            officer_id=assignment.officer_id,
            reason=assignment.reason,
            admin_id=admin.id,
            auto_commit=True
        )
        return {
            "message": f"Grievance #{grievance_id} successfully assigned to {officer.name} ({officer.email}).",
            "assigned_officer_id": officer.id,
            "assigned_officer_name": officer.name,
            "sla_deadline": grievance.sla_deadline
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# Re-Assignment: Administrative override to reassign a grievance to a new officer
@router.post("/{grievance_id}/reassign")
def reassign_grievance_officer(
    grievance_id: int,
    reassignment: schemas.ReassignGrievanceRequest,
    db: Session = Depends(connection.get_db),
    admin: models.User = Depends(require_admin)
):
    """
    Allows an administrator to reassign a grievance to a new officer.
    Permanently records REASSIGNED in the immutable audit trail.
    """
    grievance = db.query(models.Grievance).filter(models.Grievance.id == grievance_id).first()
    if not grievance:
        raise HTTPException(status_code=404, detail="Grievance not found")

    try:
        officer = routing_engine.assign_manually(
            db=db,
            grievance=grievance,
            officer_id=reassignment.officer_id,
            reason=reassignment.reason,
            admin_id=admin.id,
            auto_commit=True
        )
        return {
            "message": f"Grievance #{grievance_id} successfully reassigned to {officer.name} ({officer.email}).",
            "assigned_officer_id": officer.id,
            "assigned_officer_name": officer.name,
            "sla_deadline": grievance.sla_deadline
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# Feature 4: Immutable Audit Trail Endpoint
@router.get("/{grievance_id}/audit-trail", response_model=schemas.GrievanceAuditTrailResponse)
@router.get("/{grievance_id}/events", response_model=schemas.GrievanceAuditTrailResponse)
def get_grievance_audit_trail(
    grievance_id: int,
    db: Session = Depends(connection.get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Retrieves the complete immutable audit trail of a grievance.
    Strict server-side RBAC:
    - Citizen: restricted strictly to own grievances.
    - Officer: restricted strictly to assigned grievances.
    - Admin: universal access across all grievances.
    """
    grievance = db.query(models.Grievance).filter(models.Grievance.id == grievance_id).first()
    if not grievance:
        raise HTTPException(status_code=404, detail="Grievance not found")

    enforce_grievance_access(grievance, current_user, action="view the audit trail of")

    events = audit_service.get_events_for_grievance(db, grievance_id)
    return {
        "grievance_id": grievance.id,
        "current_status": grievance.status,
        "assigned_officer_id": grievance.assigned_officer_id,
        "assigned_officer_name": grievance.assigned_officer_name,
        "total_events": len(events),
        "events": events
    }


# SLA Escalation: Audit all open grievances, flag breaches and auto-reassign
@router.post("/sla/escalate", response_model=schemas.SLAEscalationReport)
def audit_and_escalate_slas(
    db: Session = Depends(connection.get_db),
    admin: models.User = Depends(require_admin)
):
    """
    System-wide SLA audit. Scans all active grievances, flags breaches (sla_breached=True),
    escalates priority tiers, and rebalances overloaded officers.
    """
    report = routing_engine.check_and_escalate_slas(db, auto_reassign=True)
    return report


# SLA Monitoring: List all grievances currently in breach of their SLA deadline
@router.get("/sla/breached", response_model=List[schemas.GrievanceResponse])
def get_breached_grievances(
    db: Session = Depends(connection.get_db),
    admin: models.User = Depends(require_admin)
):
    """
    Lists all un-resolved grievances where the SLA resolution deadline has expired.
    """
    breached = db.query(models.Grievance).filter(
        models.Grievance.status.notin_(TERMINAL_STATUSES),
        models.Grievance.sla_breached == True
    ).order_by(models.Grievance.sla_deadline.asc()).all()
    return breached

