from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import grievance, analytics, ai_router, observability
from app.auth.routes import router as auth_router
from app.observability.middleware import ObservabilityMiddleware
from app.services.forecast_manager import load_forecast_models, retrain_forecast_models_async
from app.queue.worker import start_background_worker, stop_background_worker
from app.db.upgrade_feature_3 import upgrade_schema as upgrade_feature_3_schema
from app.db.upgrade_feature_4 import upgrade_schema as upgrade_feature_4_schema


app = FastAPI(
    title="AI-Powered Grievance Management System",
    description="Backend for IGRS — powered by NLP, Gemini AI, and analytics",
    version="1.0.0",
)

# Observability and Tracing Middleware
app.add_middleware(ObservabilityMiddleware)

# Frontend calling APIs
origin = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origin,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth_router)
app.include_router(grievance.router)
app.include_router(analytics.router)
app.include_router(ai_router.router)
app.include_router(observability.router)


import threading


def _init_background_services():
    try:
        from app.db.connection import Base, engine
        import app.db.models  # noqa: F401 Ensure models are mapped
        Base.metadata.create_all(bind=engine)
        print("Database schema verified/created successfully.", flush=True)
    except Exception as e:
        print(f"Database table verification/creation notice: {e}", flush=True)

    try:
        upgrade_feature_3_schema(verbose=False)
    except Exception as e:
        print(f"Feature 3 schema upgrade notice: {e}", flush=True)

    try:
        upgrade_feature_4_schema(verbose=False)
    except Exception as e:
        print(f"Feature 4 schema upgrade notice: {e}", flush=True)

    try:
        import os
        from app.db.connection import SessionLocal
        from app.db.models import User, UserRole
        from app.auth.utils import hash_password
        admin_email = os.getenv("ADMIN_EMAIL", "admin@igrs.com")
        admin_pass = os.getenv("ADMIN_PASSWORD", "admin123")
        with SessionLocal() as db:
            if not db.query(User).filter(User.email == admin_email).first():
                admin_user = User(
                    name="Admin",
                    email=admin_email,
                    password_hash=hash_password(admin_pass),
                    role=UserRole.admin
                )
                db.add(admin_user)
                db.commit()
                print(f"Default admin initialized ({admin_email})", flush=True)
    except Exception as e:
        print(f"Admin initialization notice: {e}", flush=True)

    try:
        load_forecast_models()
    except Exception as e:
        print(f"Forecast models load notice: {e}", flush=True)

    try:
        retrain_forecast_models_async()
    except Exception as e:
        print(f"Forecast retrain notice: {e}", flush=True)

    try:
        start_background_worker()
    except Exception as e:
        print(f"Background worker notice: {e}", flush=True)


@app.on_event("startup")
def startup_event():
    print("Starting IGRS backend...", flush=True)
    # Initialize DB migrations and caches in background to bind port immediately (<1s)
    threading.Thread(target=_init_background_services, daemon=True).start()


@app.on_event("shutdown")
def shutdown_event():
    print("Shutting down IGRS backend...", flush=True)
    stop_background_worker()


@app.get("/")
def root():
    return {"message": "IGRS Backend is running!"}