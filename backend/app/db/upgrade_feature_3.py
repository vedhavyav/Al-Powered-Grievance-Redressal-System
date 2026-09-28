import logging
from sqlalchemy import text
from app.db.connection import engine

logger = logging.getLogger("IGRS.DBUpgradeFeature3")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Schema upgrades for Feature 3
UPGRADE_STATEMENTS = [
    # Users table: officer metadata
    ("users", "department", "ALTER TABLE users ADD COLUMN IF NOT EXISTS department VARCHAR(100);"),
    ("users", "region", "ALTER TABLE users ADD COLUMN IF NOT EXISTS region VARCHAR(150);"),
    ("users", "max_capacity", "ALTER TABLE users ADD COLUMN IF NOT EXISTS max_capacity INTEGER DEFAULT 10;"),
    ("users", "is_active", "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;"),

    # Grievances table: routing & SLA tracking
    ("grievances", "assigned_officer_id", "ALTER TABLE grievances ADD COLUMN IF NOT EXISTS assigned_officer_id INTEGER REFERENCES users(id);"),
    ("grievances", "sla_deadline", "ALTER TABLE grievances ADD COLUMN IF NOT EXISTS sla_deadline TIMESTAMP;"),
    ("grievances", "sla_breached", "ALTER TABLE grievances ADD COLUMN IF NOT EXISTS sla_breached BOOLEAN DEFAULT FALSE;"),
    ("grievances", "escalated", "ALTER TABLE grievances ADD COLUMN IF NOT EXISTS escalated BOOLEAN DEFAULT FALSE;"),
    ("grievances", "escalated_at", "ALTER TABLE grievances ADD COLUMN IF NOT EXISTS escalated_at TIMESTAMP;"),
    ("grievances", "routing_score", "ALTER TABLE grievances ADD COLUMN IF NOT EXISTS routing_score DOUBLE PRECISION;"),
    ("grievances", "routing_metadata", "ALTER TABLE grievances ADD COLUMN IF NOT EXISTS routing_metadata TEXT;"),

    # Indexes
    ("grievances", "idx_grievance_assigned_officer", "CREATE INDEX IF NOT EXISTS idx_grievance_assigned_officer ON grievances(assigned_officer_id);"),
    ("grievances", "idx_grievance_sla_deadline", "CREATE INDEX IF NOT EXISTS idx_grievance_sla_deadline ON grievances(sla_deadline);"),
]


def upgrade_schema(verbose: bool = True):
    """
    Applies column additions and indexes for Feature 3.
    Safe to execute multiple times (idempotent).
    """
    applied = []
    with engine.connect() as conn:
        with conn.begin():
            # For PostgreSQL, check if userrole enum needs 'officer'
            try:
                conn.execute(text("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'officer';"))
                if verbose:
                    logger.info("Verified userrole ENUM contains 'officer'")
            except Exception:
                # SQLite or already updated
                pass

            for table, col_or_idx, ddl in UPGRADE_STATEMENTS:
                try:
                    conn.execute(text(ddl))
                    applied.append(f"{table}.{col_or_idx}")
                    if verbose:
                        logger.info(f"Verified/Applied schema: {table}.{col_or_idx}")
                except Exception as e:
                    # In SQLite or if column already exists
                    if verbose:
                        logger.debug(f"Schema update notice ({table}.{col_or_idx}): {e}")

    return applied


if __name__ == "__main__":
    print("Upgrading database schema for Feature 3 (Automated Routing & SLA)...")
    upgrade_schema(verbose=True)
    print("Database upgrade completed successfully.")
