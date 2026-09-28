import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

from app.db.connection import SessionLocal
from app.db.models import User, UserRole
from app.auth.utils import hash_password

SAMPLE_OFFICERS = [
    {
        "name": "Officer A (Water - Lucknow)",
        "email": "officer.a@igrs.gov.in",
        "password": "password123",
        "department": "Water",
        "region": "Lucknow",
        "max_capacity": 10
    },
    {
        "name": "Officer B (Water - Lucknow)",
        "email": "officer.b@igrs.gov.in",
        "password": "password123",
        "department": "Water",
        "region": "Lucknow",
        "max_capacity": 10
    },
    {
        "name": "Officer C (Electricity - Lucknow)",
        "email": "officer.c@igrs.gov.in",
        "password": "password123",
        "department": "Electricity",
        "region": "Lucknow",
        "max_capacity": 10
    },
    {
        "name": "Officer D (Roads - Kanpur)",
        "email": "officer.d@igrs.gov.in",
        "password": "password123",
        "department": "Roads & Infrastructure",
        "region": "Kanpur",
        "max_capacity": 10
    },
    {
        "name": "Officer E (Sanitation - Lucknow)",
        "email": "officer.e@igrs.gov.in",
        "password": "password123",
        "department": "Sanitation",
        "region": "Lucknow",
        "max_capacity": 10
    },
    {
        "name": "Officer F (Public Grievances - All Regions)",
        "email": "officer.f@igrs.gov.in",
        "password": "password123",
        "department": "General",
        "region": "All",
        "max_capacity": 15
    },
]


def seed_officers():
    """
    Seeds sample officers across departments and jurisdictions
    matching the scenarios in context/feature.md.
    """
    db = SessionLocal()
    created_count = 0
    updated_count = 0

    try:
        for data in SAMPLE_OFFICERS:
            existing = db.query(User).filter(User.email == data["email"]).first()
            if not existing:
                officer = User(
                    name=data["name"],
                    email=data["email"],
                    password_hash=hash_password(data["password"]),
                    role=UserRole.officer,
                    department=data["department"],
                    region=data["region"],
                    max_capacity=data["max_capacity"],
                    is_active=True
                )
                db.add(officer)
                created_count += 1
                print(f"Created officer: {data['name']} ({data['department']}, {data['region']})")
            else:
                existing.role = UserRole.officer
                existing.department = data["department"]
                existing.region = data["region"]
                existing.max_capacity = data["max_capacity"]
                existing.is_active = True
                updated_count += 1
                print(f"Updated existing officer: {data['name']}")

        db.commit()
        print(f"\nDone. Seeded: {created_count} created, {updated_count} verified/updated.")
    except Exception as e:
        db.rollback()
        print(f"Error seeding officers: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    seed_officers()
