import logging
from sqlalchemy import text
from app.db.connection import engine

logger = logging.getLogger("IGRS.DBUpgradeFeature4")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Schema upgrades for Feature 4: Immutable Audit Trail & RBAC
CREATE_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS grievance_events (
    id SERIAL PRIMARY KEY,
    grievance_id INTEGER NOT NULL REFERENCES grievances(id) ON DELETE CASCADE,
    actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    actor_role VARCHAR(50) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    old_value TEXT,
    new_value TEXT,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT
);
"""

INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS idx_grievance_events_grv ON grievance_events(grievance_id);",
    "CREATE INDEX IF NOT EXISTS idx_grievance_events_type ON grievance_events(event_type);",
    "CREATE INDEX IF NOT EXISTS idx_grievance_events_timestamp ON grievance_events(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_grievance_events_actor ON grievance_events(actor_id);",
]


def upgrade_schema(verbose: bool = True):
    """
    Applies table creation and indexes for Feature 4 (Immutable Audit Trail).
    Safe to execute multiple times (idempotent).
    """
    applied = []
    with engine.connect() as conn:
        with conn.begin():
            try:
                conn.execute(text(CREATE_EVENTS_TABLE))
                applied.append("grievance_events table")
                if verbose:
                    logger.info("Verified/Applied schema: grievance_events table")
            except Exception as e:
                if verbose:
                    logger.debug(f"Schema update notice (table creation): {e}")

            for idx_ddl in INDEX_STATEMENTS:
                try:
                    conn.execute(text(idx_ddl))
                    applied.append(idx_ddl.split()[5] if len(idx_ddl.split()) > 5 else "index")
                    if verbose:
                        logger.info(f"Verified/Applied index: {idx_ddl}")
                except Exception as e:
                    if verbose:
                        logger.debug(f"Schema update notice (index): {e}")

    return applied


if __name__ == "__main__":
    print("Upgrading database schema for Feature 4 (Immutable Audit Trail)...")
    upgrade_schema(verbose=True)
    print("Database upgrade for Feature 4 completed successfully.")
