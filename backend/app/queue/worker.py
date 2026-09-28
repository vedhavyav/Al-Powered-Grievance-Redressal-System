import os
import time
import logging
import threading
from datetime import datetime
from typing import Optional

from app.db.connection import SessionLocal
from app.db.models import Grievance
from app.services.nlp_processor import process_grievance
from app.queue.queue_service import queue_service
from app.cache.cache_service import cache_service
from app.observability.metrics import metrics_registry

logger = logging.getLogger("IGRS.AIWorker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

MAX_RETRIES = int(os.getenv("AI_WORKER_MAX_RETRIES", "3"))
_worker_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


def process_single_job(job: dict) -> bool:
    """
    Executes NLP/Gemini processing for a single queued grievance.
    Handles retries with exponential backoff and DLQ routing on failure.
    Instruments queue wait, AI model latency, and overall duration.
    """
    grievance_id = job.get("grievance_id")
    retry_count = job.get("retry_count", 0)
    job_start = time.perf_counter()

    # Track message queue wait duration
    enqueued_at = job.get("enqueued_at")
    if enqueued_at:
        try:
            enq_time = datetime.fromisoformat(enqueued_at)
            wait_sec = max(0.0, (datetime.utcnow() - enq_time).total_seconds())
            metrics_registry.queue_wait_duration_seconds.observe(wait_sec)
        except Exception:
            pass

    logger.info(f"Processing grievance #{grievance_id} (attempt {retry_count + 1}/{MAX_RETRIES + 1})")

    db = SessionLocal()
    try:
        grievance = db.query(Grievance).filter(Grievance.id == grievance_id).first()
        if not grievance:
            logger.warning(f"Grievance #{grievance_id} not found in database. Skipping.")
            return False

        # Mark as in-flight
        grievance.processing_status = "PROCESSING"
        db.commit()

        # Run NLP + Gemini classification and geocoding with latency measurement
        ai_start = time.perf_counter()
        try:
            result = process_grievance(grievance.description)
            ai_duration = time.perf_counter() - ai_start
            metrics_registry.ai_request_duration_seconds.observe(ai_duration, labels={"model": "gemini-2.0-flash"})
            metrics_registry.ai_requests_total.inc(labels={"model": "gemini-2.0-flash", "status": "success"})
        except Exception as ai_err:
            ai_duration = time.perf_counter() - ai_start
            metrics_registry.ai_request_duration_seconds.observe(ai_duration, labels={"model": "gemini-2.0-flash"})
            metrics_registry.ai_requests_total.inc(labels={"model": "gemini-2.0-flash", "status": "error"})
            metrics_registry.ai_errors_total.inc(labels={"model": "gemini-2.0-flash", "error_type": type(ai_err).__name__})
            raise ai_err

        # Update grievance with AI classification outputs
        grievance.category = result.get("category")
        grievance.priority = result.get("priority")
        grievance.region = result.get("region")
        grievance.latitude = str(result.get("latitude")) if result.get("latitude") is not None else None
        grievance.longitude = str(result.get("longitude")) if result.get("longitude") is not None else None
        grievance.solution = result.get("solution")
        grievance.processing_status = "COMPLETED"
        grievance.processed_at = datetime.utcnow()
        grievance.last_error = None
        db.commit()

        # Record overall end-to-end processing duration
        proc_duration = time.perf_counter() - job_start
        metrics_registry.grievance_processing_duration_seconds.observe(proc_duration)

        # Feature 4: Record AI classification in immutable audit trail
        try:
            from app.services.audit_service import audit_service, EventType
            audit_service.log_event(
                db=db,
                grievance_id=grievance.id,
                event_type=EventType.AI_CLASSIFIED,
                actor_role="ai_worker",
                actor_id=None,
                old_value="Unclassified",
                new_value=f"{grievance.category} / {grievance.priority}",
                metadata={
                    "category": grievance.category,
                    "priority": grievance.priority,
                    "region": grievance.region,
                    "has_solution": bool(grievance.solution),
                    "latitude": grievance.latitude,
                    "longitude": grievance.longitude
                },
                auto_commit=True
            )
        except Exception as audit_err:
            logger.warning(f"Audit log error for AI classification #{grievance_id}: {audit_err}")

        # Feature 3: Automated Grievance Routing & SLA Load-Balancing
        try:
            from app.services.routing_engine import routing_engine
            assigned_officer = routing_engine.route_grievance(db, grievance, auto_commit=True)
            if assigned_officer:
                logger.info(f"Grievance #{grievance_id} automatically routed to officer '{assigned_officer.name}' (ID: {assigned_officer.id})")
        except Exception as route_err:
            logger.warning(f"Automated routing error for grievance #{grievance_id}: {route_err}")

        # Invalidate hotspot & trend caches to reflect freshly processed grievance data
        try:
            cache_service.delete_pattern("analytics:hotspots*")
        except Exception as cache_err:
            logger.warning(f"Cache invalidation error: {cache_err}")

        logger.info(
            f"Successfully processed grievance #{grievance_id}: "
            f"category='{grievance.category}', priority='{grievance.priority}', region='{grievance.region}'"
        )
        return True

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error processing grievance #{grievance_id}: {error_msg}")

        try:
            grievance = db.query(Grievance).filter(Grievance.id == grievance_id).first()
            if grievance:
                next_retry = retry_count + 1
                grievance.retry_count = next_retry
                grievance.last_error = error_msg

                if next_retry <= MAX_RETRIES:
                    grievance.processing_status = "RETRYING"
                    db.commit()

                    # Exponential backoff before re-enqueuing: 2^retry seconds
                    backoff_delay = 2 ** next_retry
                    logger.info(f"Scheduling retry {next_retry}/{MAX_RETRIES} for grievance #{grievance_id} in {backoff_delay}s")
                    time.sleep(min(backoff_delay, 10))

                    history = job.get("error_history", [])
                    history.append({"retry": next_retry, "error": error_msg, "time": datetime.utcnow().isoformat()})
                    queue_service.enqueue(grievance_id=grievance_id, retry_count=next_retry, error_history=history)
                else:
                    # Max retries exceeded -> Dead-Letter Queue
                    grievance.processing_status = "FAILED"
                    grievance.last_error = f"Max retries ({MAX_RETRIES}) exceeded: {error_msg}"
                    db.commit()

                    queue_service.send_to_dlq(job, final_error=error_msg)
                    logger.error(f"Grievance #{grievance_id} permanently failed after {MAX_RETRIES} retries. Sent to DLQ.")
        except Exception as db_err:
            logger.error(f"Database error during failure handling for #{grievance_id}: {db_err}")

        return False

    finally:
        db.close()


def run_worker_loop(stop_event: Optional[threading.Event] = None):
    """
    Continuous worker loop that pulls and processes jobs from the queue.
    """
    logger.info("AI Processing Worker started and listening for jobs...")
    while stop_event is None or not stop_event.is_set():
        try:
            job = queue_service.dequeue(timeout=2)
            if job:
                process_single_job(job)
        except Exception as e:
            logger.error(f"Unexpected error in worker loop: {e}")
            time.sleep(1)

    logger.info("AI Processing Worker stopped gracefully.")


def start_background_worker() -> threading.Thread:
    """
    Spawns an async worker thread within the FastAPI process.
    Ensures seamless async queue handling during local development and server runs.
    """
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        logger.info("Background AI Worker is already running.")
        return _worker_thread

    _stop_event.clear()
    _worker_thread = threading.Thread(
        target=run_worker_loop,
        args=(_stop_event,),
        name="IGRS-AIWorker-Thread",
        daemon=True
    )
    _worker_thread.start()
    logger.info("Background AI Worker thread launched successfully.")
    return _worker_thread


def stop_background_worker():
    """Stops the background worker thread gracefully."""
    if _stop_event:
        _stop_event.set()
    if _worker_thread and _worker_thread.is_alive():
        _worker_thread.join(timeout=3)
    logger.info("Background AI Worker thread shutdown.")


if __name__ == "__main__":
    logger.info("Starting standalone AI Worker process...")
    try:
        run_worker_loop()
    except KeyboardInterrupt:
        logger.info("Worker stopped by user interrupt.")
