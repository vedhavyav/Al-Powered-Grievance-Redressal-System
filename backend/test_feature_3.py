import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, User, UserRole, Grievance
from app.services.routing_engine import RoutingEngine, routing_engine, SLA_HOURS_MAPPING
from app.queue.worker import process_single_job


class TestFeature3RoutingAndSLA(unittest.TestCase):
    """
    Test suite for Feature 3: Automated Grievance Routing & Load-Balancing Engine
    """

    def setUp(self):
        # Create an isolated in-memory SQLite database for each test
        self.engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.router = RoutingEngine()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)

    def _create_user(self, name, email, role=UserRole.officer, department=None, region=None, capacity=10):
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

    def _create_grievance(self, description, category, region, priority, status="Pending", assigned_id=None, sla_deadline=None):
        grv = Grievance(
            description=description,
            category=category,
            region=region,
            priority=priority,
            status=status,
            assigned_officer_id=assigned_id,
            sla_deadline=sla_deadline,
            created_at=datetime.utcnow()
        )
        self.db.add(grv)
        self.db.commit()
        self.db.refresh(grv)
        return grv

    def test_routing_engine_prompt_scenario(self):
        """
        Verify the exact scenario defined in context/feature.md:
        Complaint: 'Water pipeline burst near Alambagh' (Category: Water, Region: Lucknow, Priority: HIGH)
        Officer A: Water, Lucknow, 8 active cases
        Officer B: Water, Lucknow, 2 active cases
        Officer C: Electricity, Lucknow, 1 active case
        Expected Assignment: Officer B
        """
        off_a = self._create_user("Officer A", "a@igrs.test", department="Water", region="Lucknow", capacity=10)
        off_b = self._create_user("Officer B", "b@igrs.test", department="Water", region="Lucknow", capacity=10)
        off_c = self._create_user("Officer C", "c@igrs.test", department="Electricity", region="Lucknow", capacity=10)

        # Assign 8 active cases to Officer A
        for i in range(8):
            self._create_grievance(f"Water case A{i}", "Water", "Lucknow", "MEDIUM", status="In Progress", assigned_id=off_a.id)

        # Assign 2 active cases to Officer B
        for i in range(2):
            self._create_grievance(f"Water case B{i}", "Water", "Lucknow", "MEDIUM", status="In Progress", assigned_id=off_b.id)

        # Assign 1 active case to Officer C
        self._create_grievance("Electric case C0", "Electricity", "Lucknow", "MEDIUM", status="In Progress", assigned_id=off_c.id)

        # Verify active case counts
        self.assertEqual(self.router.get_officer_active_workload(self.db, off_a.id), 8)
        self.assertEqual(self.router.get_officer_active_workload(self.db, off_b.id), 2)
        self.assertEqual(self.router.get_officer_active_workload(self.db, off_c.id), 1)

        # Evaluate candidate officers
        candidates = self.router.evaluate_officers(self.db, category="Water", region="Lucknow", priority="HIGH")
        best_officer, score, candidate_scores, summary = self.router.find_best_officer(
            self.db, category="Water", region="Lucknow", priority="HIGH"
        )

        self.assertIsNotNone(best_officer)
        self.assertEqual(best_officer.id, off_b.id)
        self.assertEqual(best_officer.name, "Officer B")

        # Officer B should score higher than Officer A (due to workload) and Officer C (due to category match)
        score_a = next(c["total_score"] for c in candidates if c["officer_id"] == off_a.id)
        score_b = next(c["total_score"] for c in candidates if c["officer_id"] == off_b.id)
        score_c = next(c["total_score"] for c in candidates if c["officer_id"] == off_c.id)

        self.assertGreater(score_b, score_a, "Officer B with 2 cases must outscore Officer A with 8 cases")
        self.assertGreater(score_b, score_c, "Officer B with Water match must outscore Officer C with Electricity")

    def test_capacity_ceiling_enforcement(self):
        """
        Verify that an officer who has reached maximum capacity is marked ineligible
        and cannot receive new assignments.
        """
        off = self._create_user("Full Officer", "full@igrs.test", department="Sanitation", region="Lucknow", capacity=3)
        off_alt = self._create_user("Free Officer", "free@igrs.test", department="Sanitation", region="Lucknow", capacity=10)

        # Fill first officer to capacity (3/3)
        for i in range(3):
            self._create_grievance(f"Sanitation {i}", "Sanitation", "Lucknow", "LOW", status="Pending", assigned_id=off.id)

        candidates = self.router.evaluate_officers(self.db, category="Sanitation", region="Lucknow", priority="MEDIUM")
        cand_map = {c["officer_id"]: c for c in candidates}

        self.assertFalse(cand_map[off.id]["eligible"])
        self.assertIn("Max capacity reached", cand_map[off.id]["disqualification_reason"])
        self.assertTrue(cand_map[off_alt.id]["eligible"])

        # Best officer must be the free officer
        best_off, _, _, _ = self.router.find_best_officer(self.db, category="Sanitation", region="Lucknow", priority="MEDIUM")
        self.assertEqual(best_off.id, off_alt.id)

    def test_sla_deadline_computation(self):
        """
        Verify SLA deadlines for all priority tiers.
        """
        now = datetime(2026, 9, 28, 12, 0, 0)
        self.assertEqual(self.router.calculate_sla_deadline("CRITICAL", from_time=now), now + timedelta(hours=12))
        self.assertEqual(self.router.calculate_sla_deadline("HIGH", from_time=now), now + timedelta(hours=24))
        self.assertEqual(self.router.calculate_sla_deadline("MEDIUM", from_time=now), now + timedelta(hours=48))
        self.assertEqual(self.router.calculate_sla_deadline("LOW", from_time=now), now + timedelta(hours=96))
        # Default / unknown priority fallback
        self.assertEqual(self.router.calculate_sla_deadline(None, from_time=now), now + timedelta(hours=48))

    def test_sla_breach_detection_and_escalation(self):
        """
        Verify that overdue grievances trigger SLA breach flagging and automatic escalation.
        """
        off_busy = self._create_user("Busy Officer", "busy@igrs.test", department="Water", region="Lucknow", capacity=10)
        off_available = self._create_user("Available Officer", "avail@igrs.test", department="Water", region="Lucknow", capacity=10)

        # Overdue grievance: deadline was 2 hours ago
        past_deadline = datetime.utcnow() - timedelta(hours=2)
        grv_overdue = self._create_grievance(
            "Broken pipe overdue", "Water", "Lucknow", "MEDIUM",
            status="In Progress", assigned_id=off_busy.id, sla_deadline=past_deadline
        )
        # Assign extra cases to off_busy so current workload is high
        for i in range(3):
            self._create_grievance(f"Other case {i}", "Water", "Lucknow", "LOW", status="Pending", assigned_id=off_busy.id)

        # Run SLA audit
        report = self.router.check_and_escalate_slas(self.db, auto_reassign=True)

        self.assertEqual(report["breached_count"], 1)
        self.assertEqual(report["escalated_count"], 1)
        self.assertGreaterEqual(report["reassigned_count"], 1)

        self.db.refresh(grv_overdue)
        self.assertTrue(grv_overdue.sla_breached)
        self.assertTrue(grv_overdue.escalated)
        self.assertIsNotNone(grv_overdue.escalated_at)
        self.assertEqual(grv_overdue.priority, "HIGH")  # Escalate MEDIUM -> HIGH
        self.assertEqual(grv_overdue.assigned_officer_id, off_available.id)

    def test_route_grievance_end_to_end(self):
        """
        Test end-to-end routing on a grievance instance.
        """
        officer = self._create_user("Officer Metro", "metro@igrs.test", department="Roads", region="Kanpur", capacity=10)
        grv = self._create_grievance("Pothole on highway", "Roads", "Kanpur", "HIGH")

        assigned = self.router.route_grievance(self.db, grv, auto_commit=True)

        self.assertEqual(assigned.id, officer.id)
        self.assertEqual(grv.assigned_officer_id, officer.id)
        self.assertIsNotNone(grv.sla_deadline)
        self.assertIsNotNone(grv.routing_score)
        self.assertIn("assigned_officer_name", grv.routing_metadata)
        self.assertEqual(grv.assigned_officer_name, "Officer Metro")

    @patch("app.queue.worker.process_grievance")
    @patch("app.queue.worker.cache_service.delete_pattern")
    @patch("app.queue.worker.SessionLocal")
    def test_ai_worker_triggers_automated_routing(self, mock_session_local, mock_cache_delete, mock_nlp):
        """
        Test that worker.process_single_job automatically routes the grievance
        upon completing Gemini AI classification.
        """
        # Return a dedicated session so closing it doesn't close self.db
        mock_session_local.side_effect = lambda: self.Session()
        mock_nlp.return_value = {
            "category": "Water",
            "priority": "HIGH",
            "region": "Lucknow",
            "latitude": 26.8467,
            "longitude": 80.9462,
            "solution": "Dispatch repair team to fix pipe burst"
        }

        officer = self._create_user("Auto Water Officer", "water.auto@igrs.test", department="Water", region="Lucknow")
        grv = self._create_grievance("Water pipeline leak", None, None, None, status="Pending")
        grv_id = grv.id

        job = {"grievance_id": grv_id, "retry_count": 0}
        success = process_single_job(job)

        self.assertTrue(success)
        test_session = self.Session()
        try:
            updated_grv = test_session.query(Grievance).filter(Grievance.id == grv_id).first()
            self.assertEqual(updated_grv.processing_status, "COMPLETED")
            self.assertEqual(updated_grv.category, "Water")
            self.assertEqual(updated_grv.region, "Lucknow")
            # Feature 3: Grievance must have been automatically assigned by routing engine!
            self.assertEqual(updated_grv.assigned_officer_id, officer.id)
            self.assertIsNotNone(updated_grv.sla_deadline)
            self.assertIsNotNone(updated_grv.routing_score)
        finally:
            test_session.close()

    def test_manual_assign_and_metadata(self):
        """
        Verify manual administrative assignment overrides and persists audit reason.
        """
        admin = self._create_user("Admin", "admin@igrs.test", role=UserRole.admin)
        officer = self._create_user("Override Officer", "override@igrs.test", department="Electricity")
        grv = self._create_grievance("Transformer blown", "Electricity", "Lucknow", "CRITICAL")

        assigned = self.router.assign_manually(
            self.db,
            grv,
            officer_id=officer.id,
            reason="High importance VIP area",
            auto_commit=True
        )

        self.assertEqual(assigned.id, officer.id)
        self.assertEqual(grv.assigned_officer_id, officer.id)
        self.assertIn("High importance VIP area", grv.routing_metadata)
        self.assertIn("manual_assignment", grv.routing_metadata)

    def test_get_all_officers_with_workload(self):
        """
        Verify officer workload aggregation across the system.
        """
        off1 = self._create_user("Off 1", "off1@igrs.test", department="Water", region="Lucknow", capacity=5)
        off2 = self._create_user("Off 2", "off2@igrs.test", department="Electricity", region="Lucknow", capacity=10)

        # 3 cases for off1
        for i in range(3):
            self._create_grievance(f"Case {i}", "Water", "Lucknow", "LOW", status="Pending", assigned_id=off1.id)

        officers_info = self.router.get_all_officers_with_workload(self.db)
        off1_info = next(o for o in officers_info if o["id"] == off1.id)
        off2_info = next(o for o in officers_info if o["id"] == off2.id)

        self.assertEqual(off1_info["active_cases"], 3)
        self.assertEqual(off1_info["max_capacity"], 5)
        self.assertEqual(off2_info["active_cases"], 0)


if __name__ == "__main__":
    unittest.main()

