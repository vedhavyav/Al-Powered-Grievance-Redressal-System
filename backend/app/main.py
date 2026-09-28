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


@app.on_event("startup")
def startup_event():
    print("Starting IGRS backend...")
    try:
        upgrade_feature_3_schema(verbose=False)
    except Exception as e:
        print(f"Feature 3 schema upgrade notice: {e}")

    try:
        upgrade_feature_4_schema(verbose=False)
    except Exception as e:
        print(f"Feature 4 schema upgrade notice: {e}")
    load_forecast_models()
    retrain_forecast_models_async()
    start_background_worker()


@app.on_event("shutdown")
def shutdown_event():
    print("Shutting down IGRS backend...")
    stop_background_worker()


@app.get("/")
def root():
    return {"message": "IGRS Backend is running!"}