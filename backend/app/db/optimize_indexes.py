import sys
import os
import time
import logging
from sqlalchemy import text
from app.db.connection import engine, SessionLocal

logger = logging.getLogger("IGRS.DBOptimizer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# SQL statements for Feature 2 PostgreSQL indexes
INDEX_STATEMENTS = [
    (
        "idx_grievance_category",
        "CREATE INDEX IF NOT EXISTS idx_grievance_category ON grievances(category);"
    ),
    (
        "idx_grievance_created_at",
        "CREATE INDEX IF NOT EXISTS idx_grievance_created_at ON grievances(created_at);"
    ),
    (
        "idx_grievance_region",
        "CREATE INDEX IF NOT EXISTS idx_grievance_region ON grievances(region);"
    ),
    (
        "idx_grievance_status_priority",
        "CREATE INDEX IF NOT EXISTS idx_grievance_status_priority ON grievances(status, priority);"
    ),
]


def ensure_indexes(verbose: bool = True) -> list[str]:
    """
    Applies the required composite and column indexes on the grievances table
    if they do not already exist. Works safely on PostgreSQL and SQLite (test).
    """
    created = []
    with engine.connect() as conn:
        with conn.begin():
            for name, ddl in INDEX_STATEMENTS:
                try:
                    conn.execute(text(ddl))
                    created.append(name)
                    if verbose:
                        logger.info(f"Verified/Created index: {name}")
                except Exception as e:
                    logger.warning(f"Could not create index {name}: {e}")
    return created


def profile_queries():
    """
    Runs EXPLAIN (ANALYZE, BUFFERS) or EXPLAIN on key access patterns to evaluate
    query execution plans, comparing Index Scans vs Sequential Scans.
    """
    queries = [
        (
            "Category Filter (Hotspot Dominance & Forecast)",
            "SELECT id, region, category FROM grievances WHERE category = 'Water' LIMIT 100;"
        ),
        (
            "Region Filter (Macro Hotspot Aggregations)",
            "SELECT id, region, latitude, longitude FROM grievances WHERE region = 'Lucknow' LIMIT 100;"
        ),
        (
            "Status + Priority Composite Filter (Admin & Escalation)",
            "SELECT id, status, priority, created_at FROM grievances WHERE status = 'Pending' AND priority = 'HIGH' LIMIT 100;"
        ),
        (
            "Timeline / Recency Filter (Trends & Velocity)",
            "SELECT id, created_at, category FROM grievances ORDER BY created_at DESC LIMIT 50;"
        ),
    ]

    print("\n" + "=" * 70)
    print("      IGRS POSTGRESQL QUERY PROFILING & INDEX VERIFICATION")
    print("=" * 70)

    with engine.connect() as conn:
        for title, query_sql in queries:
            print(f"\n[Query]: {title}")
            print(f"SQL: {query_sql}")

            # Try EXPLAIN ANALYZE for PostgreSQL; fallback to basic EXPLAIN if unsupported
            explain_sql = f"EXPLAIN ANALYZE {query_sql}"
            try:
                start_time = time.perf_counter()
                result = conn.execute(text(explain_sql))
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                lines = [row[0] for row in result.fetchall()]
                print(f"Execution Time (Roundtrip): {elapsed_ms:.2f}ms")
                print("Plan Summary:")
                for line in lines[:6]:  # Show top lines of query plan
                    print(f"  -> {line}")
            except Exception as e:
                # Fallback to standard EXPLAIN
                try:
                    res = conn.execute(text(f"EXPLAIN {query_sql}"))
                    lines = [str(r[0]) for r in res.fetchall()]
                    print("Execution Plan:")
                    for line in lines[:4]:
                        print(f"  -> {line}")
                except Exception as ex2:
                    print(f"Could not execute EXPLAIN: {ex2}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    print("Ensuring database indexes...")
    ensure_indexes(verbose=True)
    profile_queries()
