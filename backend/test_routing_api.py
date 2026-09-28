import os
import sys
import unittest
from datetime import datetime, timedelta

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, User, UserRole, Grievance
from app.db import schemas
from app.routes.grievance import (
    get_officers,
    create_officer,
    get_assigned_to_me,
    auto_route_grievance,
    assign_grievance_officer,
    audit_and_escalate_slas,
    get_breached_grievances
)


class TestRoutingAPIFunctions(unittest.TestCase):
    """
    Direct route function integration tests for Feature 3 Routing & SLA APIs.
    Validates route logic, DB queries, schemas, and return structures.
    """

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        # Create Admin user
        self.admin = User(
            name="Admin System",
            email="admin@test.gov",
            password_hash="fakehash",
            role=UserRole.admin,
            is_active=True
        )
        # Create Officer user
        self.officer = User(
            name="Officer Assigned",
            email="officer.assigned@test.gov",
            password_hash="fakehash",
            role=UserRole.officer,
            department="Water",
            region="Lucknow",
            max_capacity=10,
            is_active=True
        )
        self.db.add(self.admin)
        self.db.add(self.officer)
        self.db.commit()
        self.db.refresh(self.admin)
        self.db.refresh(self.officer)

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)

    def test_01_create_officer_route(self):
        """Test create_officer route creates new officer with capacity & department"""
        payload = schemas.OfficerCreate(
            name="Officer Sharma",
            email="sharma@test.gov",
            password="securepassword",
            department="Electricity",
            region="Lucknow",
            max_capacity=8
        )
        res = create_officer(officer_in=payload, db=self.db, admin=self.admin)
        self.assertEqual(res["name"], "Officer Sharma")
        self.assertEqual(res["department"], "Electricity")
        self.assertEqual(res["max_capacity"], 8)
        self.assertEqual(res["active_cases"], 0)

    def test_02_get_officers_route(self):
        """Test get_officers lists registered officers and their workloads"""
        officers = get_officers(db=self.db, admin=self.admin)
        self.assertGreaterEqual(len(officers), 2)
        emails = [o["email"] for o in officers]
        self.assertIn("officer.assigned@test.gov", emails)

    def test_03_auto_route_grievance_route(self):
        """Test auto_route_grievance evaluates candidates and assigns best officer"""
        grv = Grievance(
            description="Water pipe burst near Charbagh",
            category="Water",
            region="Lucknow",
            priority="HIGH",
            status="Pending",
            created_at=datetime.utcnow()
        )
        self.db.add(grv)
        self.db.commit()
        self.db.refresh(grv)

        res = auto_route_grievance(grievance_id=grv.id, db=self.db, admin=self.admin)
        self.assertEqual(res["grievance_id"], grv.id)
        self.assertEqual(res["category"], "Water")
        self.assertEqual(res["assigned_officer_id"], self.officer.id)
        self.assertIsNotNone(res["routing_score"])
        self.assertIsNotNone(res["sla_deadline"])
        self.assertGreater(len(res["candidates"]), 0)
        self.assertIn("Assigned to", res["decision_summary"])

    def test_04_manual_assign_route(self):
        """Test assign_grievance_officer allows administrative override"""
        grv = Grievance(
            description="Electric pole fallen",
            category="Electricity",
            region="Lucknow",
            priority="CRITICAL",
            status="Pending",
            created_at=datetime.utcnow()
        )
        self.db.add(grv)
        self.db.commit()
        self.db.refresh(grv)

        req = schemas.ManualAssignRequest(
            officer_id=self.officer.id,
            reason="Emergency dispatched directly"
        )
        res = assign_grievance_officer(grievance_id=grv.id, assignment=req, db=self.db, admin=self.admin)
        self.assertIn("successfully assigned", res["message"])
        self.assertEqual(res["assigned_officer_id"], self.officer.id)

    def test_05_assigned_to_me_route(self):
        """Test get_assigned_to_me returns cases assigned to logged in officer"""
        grv = Grievance(
            description="Assigned case",
            category="Water",
            region="Lucknow",
            priority="MEDIUM",
            status="In Progress",
            assigned_officer_id=self.officer.id,
            created_at=datetime.utcnow()
        )
        self.db.add(grv)
        self.db.commit()

        cases = get_assigned_to_me(db=self.db, current_user=self.officer)
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].id, grv.id)

    def test_06_sla_escalation_route(self):
        """Test audit_and_escalate_slas and get_breached_grievances"""
        # Create an overdue grievance
        overdue_grv = Grievance(
            description="Overdue leak repair",
            category="Water",
            region="Lucknow",
            priority="LOW",
            status="In Progress",
            sla_deadline=datetime.utcnow() - timedelta(days=2),
            sla_breached=False,
            created_at=datetime.utcnow() - timedelta(days=5)
        )
        self.db.add(overdue_grv)
        self.db.commit()
        self.db.refresh(overdue_grv)

        # Audit and escalate
        report = audit_and_escalate_slas(db=self.db, admin=self.admin)
        self.assertGreaterEqual(report["breached_count"], 1)
        self.assertGreaterEqual(report["escalated_count"], 1)

        # Check breached list endpoint
        breached_list = get_breached_grievances(db=self.db, admin=self.admin)
        self.assertGreaterEqual(len(breached_list), 1)
        breached_ids = [b.id for b in breached_list]
        self.assertIn(overdue_grv.id, breached_ids)


if __name__ == "__main__":
    unittest.main()
