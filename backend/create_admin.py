import os
from dotenv import load_dotenv
from app.db.connection import SessionLocal
from app.db.models import User, UserRole
from app.auth.utils import hash_password

#Load environment variables
load_dotenv()

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@igrs.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

db = SessionLocal()
existing_admin = db.query(User).filter(User.email == ADMIN_EMAIL).first()

if not existing_admin:
    admin_user = User(
        name="Admin",
        email=ADMIN_EMAIL,
        password_hash=hash_password(ADMIN_PASSWORD),
        role=UserRole.admin
    )
    db.add(admin_user)
    db.commit()
    print("Admin user created successfully!")
else:
    print("Admin already exists.")

db.close()
