import os
import sys
import unittest
from datetime import datetime, timedelta
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db.models import Base, User, UserRole, Grievance, GrievanceEvent
from app.db import schemas
from app.auth.dependencies import (
    require_admin,
    require_officer_or_admin,
    require_citizen,
    require_officer,
    get_actor_role_str,
    enforce_grievance_access
)
from app.services.audit_service import audit_service, EventType
from app.routes.grievance import (
    submit_grievance,
    get_my_grievances,
    withdraw_own_grievance,
    update_grievance_status,
    upload_grievance_resolution,
    assign_grievance_officer,
    reassign_grievance_officer,
    get_grievance_audit_trail,
    get_all_grievances
)


class TestFeature4AuditTrailAndRBAC(unittest.TestCase):
    """
    Comprehensive test suite for Feature 4:
    - Immutable Audit Trail (append-only ledger, event types, actor resolution)
    - Role-Based Authorization (Citizen, Officer, Admin permissions & server-side ownership)
    - Complete Grievance Lifecycle scenario from context/feature.md
    """

    def setUp(self):
        # Isolated SQLite in-memory test database
        self.engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        # Seed Users: Citizen Jane, Citizen Bob, Officer Alice (Water), Officer Charlie (Electricity), Admin Root
        self.citizen = self._create_user("Citizen Jane", "jane@citizen.com", UserRole.user)
        self.other_citizen = self._create_user("Citizen Bob", "bob@citizen.com", UserRole.user)
        self.officer1 = self._create_user("Officer Alice", "alice@dept.gov", UserRole.officer, department="Water", region="Lucknow")
        self.officer2 = self._create_user("Officer Charlie", "charlie@dept.gov", UserRole.officer, department="Electricity", region="Lucknow")
        self.admin = self._create_user("Admin Root", "admin@igrs.gov", UserRole.admin)

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)

    def _create_user(self, name, email, role, department=None, region=None, capacity=10):
        user = User(
            name=name,
            email=email,
            password_hash="fakehash",
            role=role,
            department=department,
            region=region,
            max_capacity=capacity,
            is_active=True
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def _create_grievance(self, description, user_id, category=None, priority=None, region=None, status="Pending", assigned_id=None):
        grv = Grievance(
            description=description,
            user_id=user_id,
            category=category,
            priority=priority,
            region=region,
            status=status,
            assigned_officer_id=assigned_id,
            created_at=datetime.utcnow()
        )
        self.db.add(grv)
        self.db.commit()
        self.db.refresh(grv)
        return grv

    # -------------------------------------------------------------------------
    # 1. Immutable Audit Trail Model & Service Unit Tests
    # -------------------------------------------------------------------------

    def test_audit_event_logging_and_immutability(self):
        """Verify append-only logging of lifecycle events and actor properties."""
        grv = self._create_grievance("Pipeline burst near Hazratganj", self.citizen.id)

        # 1. Creation event
        ev1 = audit_service.log_event(
            db=self.db,
            grievance_id=grv.id,
            event_type=EventType.CREATED,
            actor_role="citizen",
            actor_id=self.citizen.id,
            old_value=None,
            new_value="Pending",
            metadata={"description": grv.description},
            auto_commit=True
        )
        self.assertIsNotNone(ev1.id)
        self.assertEqual(ev1.actor_name, "Citizen Jane")
        self.assertEqual(ev1.event_type, "CREATED")

        # 2. AI classification event (automated / no user actor)
        ev2 = audit_service.log_event(
            db=self.db,
            grievance_id=grv.id,
            event_type=EventType.AI_CLASSIFIED,
            actor_role="ai_worker",
            actor_id=None,
            old_value="Unclassified",
            new_value="Water / HIGH",
            metadata={"category": "Water", "priority": "HIGH"},
            auto_commit=True
        )
        self.assertEqual(ev2.actor_name, "AI Worker (Gemini 2.0)")

        # 3. Routing assignment event (system engine)
        ev3 = audit_service.log_event(
            db=self.db,
            grievance_id=grv.id,
            event_type=EventType.ASSIGNED,
            actor_role="system",
            actor_id=None,
            old_value=None,
            new_value=self.officer1.name,
            metadata={"score": 85.0},
            auto_commit=True
        )
        self.assertEqual(ev3.actor_name, "System (Routing Engine)")

        # Verify query order and event count
        events = audit_service.get_events_for_grievance(self.db, grv.id)
        self.assertEqual(len(events), 3)
        self.assertEqual([e.event_type for e in events], ["CREATED", "AI_CLASSIFIED", "ASSIGNED"])

    # -------------------------------------------------------------------------
    # 2. Citizen Role & Ownership Boundaries
    # -------------------------------------------------------------------------

    def test_citizen_submit_generates_audit_event(self):
        """Citizen submission automatically logs a CREATED event in the audit trail."""
        req = schemas.GrievanceCreate(description="Contaminated water supply in block C")
        result = submit_grievance(grievance=req, db=self.db, current_user=self.citizen)

        self.assertIsNotNone(result.id)
        self.assertEqual(result.status, "Pending")

        # Verify audit trail
        events = audit_service.get_events_for_grievance(self.db, result.id)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "CREATED")
        self.assertEqual(events[0].actor_role, "citizen")
        self.assertEqual(events[0].actor_id, self.citizen.id)

    def test_citizen_can_withdraw_own_grievance(self):
        """Citizen can successfully withdraw their open grievance."""
        grv = self._create_grievance("Garbage dump issue", self.citizen.id, status="Pending")

        withdraw_req = schemas.WithdrawGrievanceRequest(reason="Resolved by colony association")
        updated = withdraw_own_grievance(
            grievance_id=grv.id,
            withdraw_data=withdraw_req,
            db=self.db,
            current_user=self.citizen
        )

        self.assertEqual(updated.status, "Withdrawn")

        # Verify audit trail contains WITHDRAWN event
        events = audit_service.get_events_for_grievance(self.db, grv.id)
        withdraw_ev = next(e for e in events if e.event_type == "WITHDRAWN")
        self.assertEqual(withdraw_ev.actor_role, "citizen")
        self.assertEqual(withdraw_ev.old_value, "Pending")
        self.assertEqual(withdraw_ev.new_value, "Withdrawn")

    def test_citizen_cannot_withdraw_other_citizens_grievance(self):
        """Citizen cannot withdraw another citizen's grievance (403 Forbidden)."""
        grv = self._create_grievance("Pothole issue", self.citizen.id, status="Pending")

        with self.assertRaises(HTTPException) as ctx:
            withdraw_own_grievance(
                grievance_id=grv.id,
                withdraw_data=schemas.WithdrawGrievanceRequest(reason="Malicious attempt"),
                db=self.db,
                current_user=self.other_citizen
            )
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Citizens can only withdraw their own grievances", ctx.exception.detail)

    def test_citizen_cannot_withdraw_resolved_grievance(self):
        """Cannot withdraw a grievance that is already Resolved (400 Bad Request)."""
        grv = self._create_grievance("Drain issue", self.citizen.id, status="Resolved")

        with self.assertRaises(HTTPException) as ctx:
            withdraw_own_grievance(
                grievance_id=grv.id,
                withdraw_data=None,
                db=self.db,
                current_user=self.citizen
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("already 'Resolved'", ctx.exception.detail)

    def test_citizen_cannot_update_grievance_status(self):
        """Citizen cannot directly update grievance status (403 Forbidden)."""
        grv = self._create_grievance("Streetlight broken", self.citizen.id, status="Pending")

        status_in = schemas.UpdateStatusRequest(status="Resolved")
        with self.assertRaises(HTTPException) as ctx:
            update_grievance_status(
                grievance_id=grv.id,
                status_data=status_in,
                db=self.db,
                current_user=self.citizen
            )
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Citizens cannot modify grievance status", ctx.exception.detail)

    def test_citizen_cannot_upload_resolution(self):
        """Citizen cannot upload resolution reports (403 Forbidden)."""
        grv = self._create_grievance("Streetlight broken", self.citizen.id, status="In Progress")

        res_in = schemas.UploadResolutionRequest(solution="I replaced the bulb myself")
        with self.assertRaises(HTTPException) as ctx:
            upload_grievance_resolution(
                grievance_id=grv.id,
                resolution_data=res_in,
                db=self.db,
                current_user=self.citizen
            )
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Citizens cannot upload resolution reports", ctx.exception.detail)

    # -------------------------------------------------------------------------
    # 3. Officer Role & Assignment Boundaries
    # -------------------------------------------------------------------------

    def test_officer_can_update_status_of_assigned_case(self):
        """Officer can update status for a complaint assigned to them."""
        grv = self._create_grievance(
            "Water pipe leak",
            self.citizen.id,
            status="Pending",
            assigned_id=self.officer1.id
        )

        status_in = schemas.UpdateStatusRequest(status="In Progress", remarks="Team dispatched")
        res = update_grievance_status(
            grievance_id=grv.id,
            status_data=status_in,
            db=self.db,
            current_user=self.officer1
        )
        self.assertEqual(res["new_status"], "In Progress")

        # Verify audit trail
        events = audit_service.get_events_for_grievance(self.db, grv.id)
        status_event = next(e for e in events if e.event_type == "STATUS_UPDATED")
        self.assertEqual(status_event.old_value, "Pending")
        self.assertEqual(status_event.new_value, "In Progress")
        self.assertEqual(status_event.actor_role, "officer")
        self.assertEqual(status_event.actor_id, self.officer1.id)

    def test_officer_cannot_update_unassigned_case(self):
        """Officer cannot update status of a case assigned to another officer (403 Forbidden)."""
        grv = self._create_grievance(
            "Water pipe leak",
            self.citizen.id,
            status="Pending",
            assigned_id=self.officer1.id
        )

        status_in = schemas.UpdateStatusRequest(status="In Progress")
        with self.assertRaises(HTTPException) as ctx:
            update_grievance_status(
                grievance_id=grv.id,
                status_data=status_in,
                db=self.db,
                current_user=self.officer2  # Officer Charlie trying to touch Alice's case
            )
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Officers can only update grievances assigned to their own queue", ctx.exception.detail)

    def test_officer_can_upload_resolution_for_assigned_case(self):
        """Officer can upload official resolution report for assigned complaint."""
        grv = self._create_grievance(
            "Low water pressure",
            self.citizen.id,
            status="In Progress",
            assigned_id=self.officer1.id
        )

        res_in = schemas.UploadResolutionRequest(
            solution="Replaced faulty valve on main feeder line and restored water pressure.",
            remarks="Field inspection verified flow rate.",
            action_taken="Valve replacement"
        )
        updated = upload_grievance_resolution(
            grievance_id=grv.id,
            resolution_data=res_in,
            db=self.db,
            current_user=self.officer1
        )

        self.assertEqual(updated.status, "Resolved")
        self.assertIn("Replaced faulty valve", updated.solution)

        # Verify RESOLUTION_UPLOADED event
        events = audit_service.get_events_for_grievance(self.db, grv.id)
        res_event = next(e for e in events if e.event_type == "RESOLUTION_UPLOADED")
        self.assertEqual(res_event.actor_role, "officer")
        self.assertEqual(res_event.new_value, "Resolved")

    def test_officer_cannot_upload_resolution_for_unassigned_case(self):
        """Officer cannot upload resolution for another officer's case (403 Forbidden)."""
        grv = self._create_grievance(
            "Power surge",
            self.citizen.id,
            status="In Progress",
            assigned_id=self.officer2.id
        )

        res_in = schemas.UploadResolutionRequest(solution="Unauthorized attempt")
        with self.assertRaises(HTTPException) as ctx:
            upload_grievance_resolution(
                grievance_id=grv.id,
                resolution_data=res_in,
                db=self.db,
                current_user=self.officer1  # Alice trying to resolve Charlie's case
            )
        self.assertEqual(ctx.exception.status_code, 403)

    # -------------------------------------------------------------------------
    # 4. Admin Role & Universal Authority
    # -------------------------------------------------------------------------

    def test_admin_can_reassign_officer_with_audit_trail(self):
        """Admin can reassign an open case to another officer with audit logging."""
        grv = self._create_grievance(
            "Transformer sparking",
            self.citizen.id,
            status="In Progress",
            assigned_id=self.officer1.id
        )

        reassign_req = schemas.ReassignGrievanceRequest(
            officer_id=self.officer2.id,
            reason="Reassigned to electrical specialist"
        )
        res = reassign_grievance_officer(
            grievance_id=grv.id,
            reassignment=reassign_req,
            db=self.db,
            admin=self.admin
        )
        self.assertEqual(res["assigned_officer_id"], self.officer2.id)

        # Verify REASSIGNED event recorded
        events = audit_service.get_events_for_grievance(self.db, grv.id)
        reassign_event = next(e for e in events if e.event_type == "REASSIGNED")
        self.assertEqual(reassign_event.old_value, self.officer1.name)
        self.assertEqual(reassign_event.new_value, self.officer2.name)
        self.assertEqual(reassign_event.actor_role, "admin")
        self.assertEqual(reassign_event.actor_id, self.admin.id)

    # -------------------------------------------------------------------------
    # 5. Audit Trail Access Control
    # -------------------------------------------------------------------------

    def test_audit_trail_access_permissions(self):
        """
        Verify server-side RBAC for viewing the audit trail:
        - Citizen can view own audit trail
        - Other citizen cannot view (403)
        - Assigned officer can view
        - Unassigned officer cannot view (403)
        - Admin can view any audit trail
        """
        grv = self._create_grievance(
            "Sewage overflow",
            self.citizen.id,
            status="In Progress",
            assigned_id=self.officer1.id
        )
        # Log a sample event
        audit_service.log_event(
            db=self.db,
            grievance_id=grv.id,
            event_type=EventType.CREATED,
            actor_role="citizen",
            actor_id=self.citizen.id,
            new_value="Pending",
            auto_commit=True
        )

        # 1. Owner Citizen -> Allowed
        trail1 = get_grievance_audit_trail(grievance_id=grv.id, db=self.db, current_user=self.citizen)
        self.assertEqual(trail1["total_events"], 1)

        # 2. Other Citizen -> Forbidden (403)
        with self.assertRaises(HTTPException) as ctx2:
            get_grievance_audit_trail(grievance_id=grv.id, db=self.db, current_user=self.other_citizen)
        self.assertEqual(ctx2.exception.status_code, 403)

        # 3. Assigned Officer -> Allowed
        trail3 = get_grievance_audit_trail(grievance_id=grv.id, db=self.db, current_user=self.officer1)
        self.assertEqual(trail3["total_events"], 1)

        # 4. Unassigned Officer -> Forbidden (403)
        with self.assertRaises(HTTPException) as ctx4:
            get_grievance_audit_trail(grievance_id=grv.id, db=self.db, current_user=self.officer2)
        self.assertEqual(ctx4.exception.status_code, 403)

        # 5. Admin -> Allowed
        trail5 = get_grievance_audit_trail(grievance_id=grv.id, db=self.db, current_user=self.admin)
        self.assertEqual(trail5["total_events"], 1)

    # -------------------------------------------------------------------------
    # 6. Complete End-to-End Lifecycle Scenario from context/feature.md
    # -------------------------------------------------------------------------

    def test_full_lifecycle_scenario_from_feature_spec(self):
        """
        Verify the exact chronological sequence specified in context/feature.md:
        10:32 AM - Created by citizen
        10:33 AM - AI classified -> Water / HIGH
        10:34 AM - Assigned -> Officer Alice
        02:14 PM - Status -> IN_PROGRESS
        05:42 PM - Status -> RESOLVED
        """
        # Step 1: Citizen creates complaint
        grv = self._create_grievance("Water pipeline burst near Alambagh", self.citizen.id)
        audit_service.log_event(
            db=self.db,
            grievance_id=grv.id,
            event_type=EventType.CREATED,
            actor_role="citizen",
            actor_id=self.citizen.id,
            old_value=None,
            new_value="Pending",
            auto_commit=True
        )

        # Step 2: AI Classification
        grv.category = "Water"
        grv.priority = "HIGH"
        grv.region = "Lucknow"
        self.db.commit()
        audit_service.log_event(
            db=self.db,
            grievance_id=grv.id,
            event_type=EventType.AI_CLASSIFIED,
            actor_role="ai_worker",
            actor_id=None,
            old_value="Unclassified",
            new_value="Water / HIGH",
            auto_commit=True
        )

        # Step 3: Assignment to Officer Alice
        grv.assigned_officer_id = self.officer1.id
        self.db.commit()
        audit_service.log_event(
            db=self.db,
            grievance_id=grv.id,
            event_type=EventType.ASSIGNED,
            actor_role="system",
            actor_id=None,
            old_value=None,
            new_value=self.officer1.name,
            auto_commit=True
        )

        # Step 4: Officer sets status to IN_PROGRESS
        update_grievance_status(
            grievance_id=grv.id,
            status_data=schemas.UpdateStatusRequest(status="IN_PROGRESS", remarks="Excavation team on site"),
            db=self.db,
            current_user=self.officer1
        )

        # Step 5: Officer uploads resolution -> RESOLVED
        upload_grievance_resolution(
            grievance_id=grv.id,
            resolution_data=schemas.UploadResolutionRequest(solution="Replaced cracked pipeline segment and restored normal water flow."),
            db=self.db,
            current_user=self.officer1
        )

        # Verify complete chronological audit trail
        trail = get_grievance_audit_trail(grievance_id=grv.id, db=self.db, current_user=self.citizen)
        events = trail["events"]

        self.assertEqual(len(events), 5)
        self.assertEqual(events[0].event_type, "CREATED")
        self.assertEqual(events[0].actor_role, "citizen")

        self.assertEqual(events[1].event_type, "AI_CLASSIFIED")
        self.assertEqual(events[1].new_value, "Water / HIGH")

        self.assertEqual(events[2].event_type, "ASSIGNED")
        self.assertEqual(events[2].new_value, "Officer Alice")

        self.assertEqual(events[3].event_type, "STATUS_UPDATED")
        self.assertEqual(events[3].new_value, "IN_PROGRESS")

        self.assertEqual(events[4].event_type, "RESOLUTION_UPLOADED")
        self.assertEqual(events[4].new_value, "Resolved")


if __name__ == "__main__":
    unittest.main()
