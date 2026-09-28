import os
import json
import uuid
import queue
import logging
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger("IGRS.Queue")

# Queue names
QUEUE_NAME = "igrs:queue:grievances"
DLQ_NAME = "igrs:queue:grievances:dlq"


class GrievanceQueueService:
    """
    Message queue abstraction for grievance AI processing jobs.
    Uses Redis when available, with an in-memory queue fallback for local dev.
    """

    def __init__(self):
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.redis_client = None
        self._memory_queue: queue.Queue = queue.Queue()
        self._memory_dlq: list = []
        self.backend = "in-memory"
        self._initialize_backend()

    def _initialize_backend(self):
        """Attempts to connect to Redis; falls back to in-memory thread queue."""
        try:
            import redis
            client = redis.from_url(
                self.redis_url,
                socket_timeout=2,
                socket_connect_timeout=2,
                decode_responses=True
            )
            client.ping()
            self.redis_client = client
            self.backend = "redis"
            logger.info(f"Connected to Redis message queue at {self.redis_url}")
        except Exception as e:
            self.redis_client = None
            self.backend = "in-memory"
            logger.info(
                f"Redis unavailable ({e}). Using in-memory thread queue fallback. "
                "Set REDIS_URL to use a distributed Redis queue."
            )

    def enqueue(self, grievance_id: int, retry_count: int = 0, error_history: Optional[list] = None) -> Dict[str, Any]:
        """Enqueues a grievance for asynchronous AI processing."""
        job = {
            "job_id": str(uuid.uuid4()),
            "grievance_id": grievance_id,
            "retry_count": retry_count,
            "enqueued_at": datetime.utcnow().isoformat(),
            "error_history": error_history or []
        }

        serialized = json.dumps(job)

        if self.redis_client:
            try:
                self.redis_client.rpush(QUEUE_NAME, serialized)
                return job
            except Exception as e:
                logger.warning(f"Redis enqueue failed ({e}), pushing to in-memory fallback.")
                self.backend = "in-memory (fallback)"

        self._memory_queue.put(job)
        return job

    def dequeue(self, timeout: int = 2) -> Optional[Dict[str, Any]]:
        """
        Dequeues a job. Blocks up to `timeout` seconds waiting for a job.
        Returns parsed job dict or None if queue is empty.
        """
        if self.redis_client:
            try:
                result = self.redis_client.blpop(QUEUE_NAME, timeout=timeout)
                if result:
                    _, raw_payload = result
                    return json.loads(raw_payload)
            except Exception as e:
                logger.warning(f"Redis dequeue error ({e}), reading from in-memory fallback.")

        try:
            return self._memory_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def send_to_dlq(self, job: Dict[str, Any], final_error: str) -> None:
        """Sends permanently failed jobs to the Dead-Letter Queue (DLQ)."""
        dlq_entry = {
            **job,
            "failed_at": datetime.utcnow().isoformat(),
            "final_error": final_error,
        }
        serialized = json.dumps(dlq_entry)

        if self.redis_client:
            try:
                self.redis_client.rpush(DLQ_NAME, serialized)
                logger.error(f"[DLQ] Grievance #{job.get('grievance_id')} moved to DLQ: {final_error}")
                return
            except Exception as e:
                logger.error(f"Failed to push to Redis DLQ: {e}")

        self._memory_dlq.append(dlq_entry)
        logger.error(f"[DLQ] Grievance #{job.get('grievance_id')} stored in in-memory DLQ: {final_error}")

    def get_stats(self) -> Dict[str, Any]:
        """Returns queue metrics for monitoring."""
        queue_size = 0
        dlq_size = 0

        if self.redis_client:
            try:
                queue_size = self.redis_client.llen(QUEUE_NAME)
                dlq_size = self.redis_client.llen(DLQ_NAME)
            except Exception:
                queue_size = self._memory_queue.qsize()
                dlq_size = len(self._memory_dlq)
        else:
            queue_size = self._memory_queue.qsize()
            dlq_size = len(self._memory_dlq)

        return {
            "queue_name": QUEUE_NAME,
            "queue_size": queue_size,
            "dlq_size": dlq_size,
            "backend": self.backend,
            "redis_connected": self.redis_client is not None
        }

    def get_dlq_jobs(self, limit: int = 50) -> list:
        """Retrieves items from DLQ for inspection."""
        if self.redis_client:
            try:
                raw_items = self.redis_client.lrange(DLQ_NAME, 0, limit - 1)
                return [json.loads(i) for i in raw_items]
            except Exception:
                pass
        return self._memory_dlq[-limit:]


# Global singleton instance
queue_service = GrievanceQueueService()
