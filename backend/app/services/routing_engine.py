import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.models import User, UserRole, Grievance

logger = logging.getLogger("IGRS.RoutingEngine")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Priority-to-SLA configuration (in hours)
SLA_HOURS_MAPPING = {
    "CRITICAL": 12,
    "HIGH": 24,
    "MEDIUM": 48,
    "LOW": 96
}

# Scoring Weights
WEIGHT_CATEGORY = 50.0
WEIGHT_GEOGRAPHY = 30.0
WEIGHT_PRIORITY = 20.0
WEIGHT_WORKLOAD_SCALE = 40.0
WORKLOAD_PER_CASE_PENALTY = 2.0

TERMINAL_STATUSES = {"Resolved", "Closed", "Rejected"}


class RoutingEngine:
    """
    Automated Grievance Routing and Workload Load-Balancing Engine.

    Calculates deterministic multi-criteria routing scores based on:
      Score = Category_Match + Geographic_Match + Priority_Capability - Active_Workload_Penalty

    Features:
    - Department & specialty affinity matching
    - Geographic jurisdiction match
    - Workload balancing across officers
    - Hard capacity ceiling enforcement (prevents overload)
    - SLA deadline generation per priority tier
    - Automated SLA breach audit & intelligent reassignment
    """

    def __init__(self):
        self.sla_hours = SLA_HOURS_MAPPING

    def calculate_sla_deadline(self, priority: Optional[str], from_time: Optional[datetime] = None) -> datetime:
        """
        Calculates the SLA resolution deadline based on the priority level.
        """
        base_time = from_time or datetime.utcnow()
        prio_upper = (priority or "MEDIUM").strip().upper()
        hours = self.sla_hours.get(prio_upper, 48)
        return base_time + timedelta(hours=hours)

    def get_officer_active_workload(self, db: Session, officer_id: int) -> int:
        """
        Counts active, un-resolved grievances currently assigned to an officer.
        """
        active_count = db.query(func.count(Grievance.id)).filter(
            Grievance.assigned_officer_id == officer_id,
            Grievance.status.notin_(TERMINAL_STATUSES)
        ).scalar()
        return active_count or 0

    def evaluate_officers(
        self,
        db: Session,
        category: Optional[str],
        region: Optional[str],
        priority: Optional[str]
    ) -> List[Dict[str, Any]]:
        """
        Evaluates all registered officers against grievance parameters and returns
        a scored, sorted list of candidate breakdowns.
        """
        # Fetch active officers
        officers = db.query(User).filter(
            User.role == UserRole.officer,
            User.is_active == True
        ).all()

        # If no officers exist, fallback to admin users
        if not officers:
            logger.warning("No active officers found; falling back to admin users for routing.")
            officers = db.query(User).filter(
                User.role == UserRole.admin,
                User.is_active == True
            ).all()

        norm_category = (category or "").strip().lower()
        norm_region = (region or "").strip().lower()
        norm_priority = (priority or "MEDIUM").strip().upper()

        candidates = []

        for off in officers:
            dept = (off.department or "").strip().lower()
            off_region = (off.region or "").strip().lower()
            active_cases = self.get_officer_active_workload(db, off.id)
            max_cap = off.max_capacity or 10

            # 1. Category Matching Score (max 50)
            category_score = 0.0
            if norm_category and dept:
                if dept == norm_category:
                    category_score = 50.0
                elif dept in norm_category or norm_category in dept:
                    category_score = 35.0
                elif dept in ["general", "public grievances", "all"]:
                    category_score = 20.0
                else:
                    category_score = 0.0
            elif dept in ["general", "public grievances", "all"]:
                category_score = 20.0

            # 2. Geographic Matching Score (max 30)
            geo_score = 0.0
            if norm_region and off_region:
                if off_region == norm_region:
                    geo_score = 30.0
                elif off_region in norm_region or norm_region in off_region:
                    geo_score = 20.0
                else:
                    geo_score = 0.0
            else:
                geo_score = 10.0  # Neutral when region is unknown or officer covers all regions

            # 3. Priority / SLA Capacity Capability Score (max 20)
            capacity_ratio = active_cases / max(max_cap, 1)
            priority_score = 0.0
            if norm_priority in ["CRITICAL", "HIGH"]:
                if capacity_ratio < 0.4:
                    priority_score = 20.0
                elif capacity_ratio < 0.75:
                    priority_score = 12.0
                else:
                    priority_score = 5.0
            elif norm_priority == "MEDIUM":
                priority_score = 12.0 if capacity_ratio < 0.7 else 6.0
            else:  # LOW
                priority_score = 8.0

            # 4. Workload Penalty & Capacity Filter
            eligible = True
            disqualification_reason = None
            workload_penalty = 0.0

            if active_cases >= max_cap:
                eligible = False
                workload_penalty = 999.0
                disqualification_reason = f"Max capacity reached ({active_cases}/{max_cap})"
            else:
                workload_penalty = (capacity_ratio * WEIGHT_WORKLOAD_SCALE) + (active_cases * WORKLOAD_PER_CASE_PENALTY)

            total_score = round(category_score + geo_score + priority_score - workload_penalty, 2)

            candidates.append({
                "officer_id": off.id,
                "officer_name": off.name,
                "department": off.department,
                "region": off.region,
                "active_cases": active_cases,
                "max_capacity": max_cap,
                "category_score": round(category_score, 2),
                "geo_score": round(geo_score, 2),
                "priority_score": round(priority_score, 2),
                "workload_penalty": round(workload_penalty, 2),
                "total_score": total_score,
                "eligible": eligible,
                "disqualification_reason": disqualification_reason
            })

        # Sort: eligible candidates first, then descending total_score, then lowest active_cases
        candidates.sort(
            key=lambda c: (1 if c["eligible"] else 0, c["total_score"], -c["active_cases"]),
            reverse=True
        )

        return candidates

    def find_best_officer(
        self,
        db: Session,
        category: Optional[str],
        region: Optional[str],
        priority: Optional[str]
    ) -> Tuple[Optional[User], Optional[float], List[Dict[str, Any]], str]:
        """
        Identifies the optimal officer and returns (officer, score, candidates, summary).
        """
        candidates = self.evaluate_officers(db, category, region, priority)
        if not candidates:
            return None, None, [], "No officers or administrators available in system."

        eligible_candidates = [c for c in candidates if c["eligible"]]

        # If officers in matching category exist, prioritize them
        if eligible_candidates:
            cat_matches = [c for c in eligible_candidates if c["category_score"] > 0]
            selected = cat_matches[0] if cat_matches else eligible_candidates[0]
        else:
            # Overloaded fallback: pick candidate with lowest active workload
            selected = min(candidates, key=lambda c: c["active_cases"])
            logger.warning(f"All officers at capacity. Falling back to least busy officer #{selected['officer_id']}")

        officer = db.query(User).filter(User.id == selected["officer_id"]).first()
        summary = (
            f"Assigned to {selected['officer_name']} ({selected['department'] or 'General'}, {selected['region'] or 'All'}) "
            f"with score {selected['total_score']} (Active cases: {selected['active_cases']}/{selected['max_capacity']})."
        )
        return officer, selected["total_score"], candidates, summary

    def route_grievance(
        self,
        db: Session,
        grievance: Grievance,
        auto_commit: bool = True
    ) -> Optional[User]:
        """
        Executes automated routing for a grievance, assigning officer, SLA deadline,
        and persisting routing metadata. Records ASSIGNED or REASSIGNED in audit trail.
        """
        prev_officer_id = grievance.assigned_officer_id
        prev_officer_name = grievance.assigned_officer_name

        officer, score, candidates, summary = self.find_best_officer(
            db=db,
            category=grievance.category,
            region=grievance.region,
            priority=grievance.priority
        )

        sla_deadline = self.calculate_sla_deadline(grievance.priority, from_time=grievance.created_at)

        if officer:
            grievance.assigned_officer_id = officer.id
            grievance.routing_score = score
            grievance.sla_deadline = sla_deadline
            grievance.sla_breached = False
            grievance.routing_metadata = json.dumps({
                "assigned_at": datetime.utcnow().isoformat(),
                "assigned_officer_id": officer.id,
                "assigned_officer_name": officer.name,
                "summary": summary,
                "top_candidates": candidates[:5]
            })
            logger.info(f"Grievance #{grievance.id} routed to officer '{officer.name}' (ID: {officer.id}, Score: {score})")

            # Feature 4: Record assignment in immutable audit trail
            try:
                from app.services.audit_service import audit_service, EventType
                ev_type = EventType.REASSIGNED if prev_officer_id and prev_officer_id != officer.id else EventType.ASSIGNED
                audit_service.log_event(
                    db=db,
                    grievance_id=grievance.id,
                    event_type=ev_type,
                    actor_role="system",
                    actor_id=None,
                    old_value=prev_officer_name,
                    new_value=officer.name,
                    metadata={
                        "routing_score": score,
                        "sla_deadline": sla_deadline.isoformat() if sla_deadline else None,
                        "officer_department": officer.department,
                        "officer_region": officer.region
                    },
                    auto_commit=False
                )
            except Exception as audit_err:
                logger.warning(f"Audit log error during routing #{grievance.id}: {audit_err}")
        else:
            logger.warning(f"Unable to route grievance #{grievance.id}: No candidate officer found.")

        if auto_commit:
            db.commit()
            if officer:
                db.refresh(grievance)

        return officer

    def assign_manually(
        self,
        db: Session,
        grievance: Grievance,
        officer_id: int,
        reason: Optional[str] = None,
        admin_id: Optional[int] = None,
        auto_commit: bool = True
    ) -> User:
        """
        Manually assigns an officer to a grievance (e.g. by an administrator).
        Records ASSIGNED or REASSIGNED in audit trail.
        """
        prev_officer_id = grievance.assigned_officer_id
        prev_officer_name = grievance.assigned_officer_name

        officer = db.query(User).filter(User.id == officer_id).first()
        if not officer:
            raise ValueError(f"Officer with ID {officer_id} not found.")

        grievance.assigned_officer_id = officer.id
        if not grievance.sla_deadline:
            grievance.sla_deadline = self.calculate_sla_deadline(grievance.priority, grievance.created_at)

        metadata = {
            "manual_assignment": True,
            "assigned_at": datetime.utcnow().isoformat(),
            "assigned_officer_id": officer.id,
            "assigned_officer_name": officer.name,
            "reason": reason or "Administrative override"
        }
        grievance.routing_metadata = json.dumps(metadata)

        # Feature 4: Record manual assignment in immutable audit trail
        try:
            from app.services.audit_service import audit_service, EventType
            ev_type = EventType.REASSIGNED if prev_officer_id and prev_officer_id != officer.id else EventType.ASSIGNED
            audit_service.log_event(
                db=db,
                grievance_id=grievance.id,
                event_type=ev_type,
                actor_role="admin",
                actor_id=admin_id,
                old_value=prev_officer_name,
                new_value=officer.name,
                metadata={
                    "manual": True,
                    "reason": reason or "Administrative override",
                    "officer_department": officer.department
                },
                auto_commit=False
            )
        except Exception as audit_err:
            logger.warning(f"Audit log error during manual assign #{grievance.id}: {audit_err}")

        if auto_commit:
            db.commit()
            db.refresh(grievance)

        return officer

    def check_and_escalate_slas(self, db: Session, auto_reassign: bool = True) -> Dict[str, Any]:
        """
        Audits all open grievances for SLA breaches.
        If a breach is detected:
        1. Flags sla_breached = True, escalated = True
        2. Escalates priority tier (e.g. MEDIUM -> HIGH, HIGH -> CRITICAL)
        3. If officer is backlogged and auto_reassign is True, re-routes to an available officer.
        """
        now = datetime.utcnow()
        active_grievances = db.query(Grievance).filter(
            Grievance.status.notin_(TERMINAL_STATUSES),
            Grievance.sla_deadline.isnot(None),
            Grievance.sla_deadline < now
        ).all()

        total_active = db.query(func.count(Grievance.id)).filter(
            Grievance.status.notin_(TERMINAL_STATUSES)
        ).scalar() or 0

        breached_count = len(active_grievances)
        escalated_count = 0
        reassigned_count = 0
        details = []

        priority_escalation = {
            "LOW": "MEDIUM",
            "MEDIUM": "HIGH",
            "HIGH": "CRITICAL",
            "CRITICAL": "CRITICAL"
        }

        for grv in active_grievances:
            was_already_escalated = grv.escalated
            grv.sla_breached = True
            grv.escalated = True
            grv.escalated_at = grv.escalated_at or now
            escalated_count += 1

            old_priority = grv.priority or "MEDIUM"
            new_priority = priority_escalation.get(old_priority.upper(), "HIGH")
            grv.priority = new_priority

            detail_entry = {
                "grievance_id": grv.id,
                "category": grv.category,
                "region": grv.region,
                "old_priority": old_priority,
                "new_priority": new_priority,
                "sla_deadline": grv.sla_deadline.isoformat() if grv.sla_deadline else None,
                "previous_officer_id": grv.assigned_officer_id,
                "reassigned": False
            }

            if auto_reassign:
                # Attempt reassignment to an officer with lower workload
                curr_workload = self.get_officer_active_workload(db, grv.assigned_officer_id) if grv.assigned_officer_id else 99
                if curr_workload >= 2:
                    new_officer, new_score, _, reassign_summary = self.find_best_officer(
                        db=db,
                        category=grv.category,
                        region=grv.region,
                        priority=new_priority
                    )
                    if new_officer and new_officer.id != grv.assigned_officer_id:
                        grv.assigned_officer_id = new_officer.id
                        grv.routing_score = new_score
                        reassigned_count += 1
                        detail_entry["reassigned"] = True
                        detail_entry["new_officer_id"] = new_officer.id
                        detail_entry["new_officer_name"] = new_officer.name
                        detail_entry["summary"] = reassign_summary

            details.append(detail_entry)

            # Feature 4: Record SLA breach & escalation in immutable audit trail
            try:
                from app.services.audit_service import audit_service, EventType
                if not was_already_escalated:
                    audit_service.log_event(
                        db=db,
                        grievance_id=grv.id,
                        event_type=EventType.SLA_BREACHED,
                        actor_role="system",
                        actor_id=None,
                        old_value="ACTIVE",
                        new_value="BREACHED",
                        metadata={"sla_deadline": grv.sla_deadline.isoformat() if grv.sla_deadline else None},
                        auto_commit=False
                    )
                audit_service.log_event(
                    db=db,
                    grievance_id=grv.id,
                    event_type=EventType.SLA_ESCALATED,
                    actor_role="system",
                    actor_id=None,
                    old_value=old_priority,
                    new_value=new_priority,
                    metadata={
                        "reassigned": detail_entry["reassigned"],
                        "new_officer": detail_entry.get("new_officer_name")
                    },
                    auto_commit=False
                )
            except Exception as audit_err:
                logger.warning(f"Audit log error during SLA escalation #{grv.id}: {audit_err}")

        db.commit()

        return {
            "total_active_checked": total_active,
            "breached_count": breached_count,
            "escalated_count": escalated_count,
            "reassigned_count": reassigned_count,
            "details": details
        }

    def get_all_officers_with_workload(self, db: Session) -> List[Dict[str, Any]]:
        """
        Returns list of all officers with current active case counts and capacity.
        """
        officers = db.query(User).filter(
            User.role.in_([UserRole.officer, UserRole.admin])
        ).all()

        results = []
        for off in officers:
            active_cases = self.get_officer_active_workload(db, off.id)
            results.append({
                "id": off.id,
                "name": off.name,
                "email": off.email,
                "role": off.role.value if hasattr(off.role, "value") else str(off.role),
                "department": off.department,
                "region": off.region,
                "max_capacity": off.max_capacity or 10,
                "is_active": off.is_active if off.is_active is not None else True,
                "active_cases": active_cases
            })

        return results


# Global singleton instance
routing_engine = RoutingEngine()
