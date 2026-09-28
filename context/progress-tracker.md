# IGRS Enhancement Progress Tracker

Track the implementation status of architectural enhancements defined in [`context/feature.md`](file:///c:/Users/Public/OneDrive/Desktop/vs%20code%20backup/AI-Powered-Grievance-Redressal-System/context/feature.md).

---

## Overview Roadmap

| # | Feature | Status | Description |
|---|---|---|---|
| 1 | **Asynchronous AI Processing Pipeline** | **Completed** | Decoupled complaint submission from Gemini AI via Redis/in-memory message queue, worker process, retries, and DLQ. |
| 2 | **Redis Caching + Database Query Optimization** | **Completed** | Redis & in-memory caching for `/forecast`, `/hotspots`, `/trends` with TTLs, pattern invalidation, and PostgreSQL composite indexes. |
| 3 | **Automated Grievance Routing & Load-Balancing** | **Completed** | Multi-criteria scoring engine routing by category, geography, priority/SLA, and active officer workload with hard capacity ceilings. |
| 4 | **Immutable Audit Trail + Role-Based Authorization** | **Completed** | Append-only `grievance_events` audit trail, server-side RBAC & ownership enforcement (Citizen, Officer, Admin), and full lifecycle event modelling. |
| 5 | **Production-Grade Observability + CI/CD** | **Completed** | Full Prometheus exposition (`/metrics`), W3C traceparent middleware, multi-stage grievance lifecycle metrics engine (P50/P95), GitHub Actions CI/CD workflows, and production Docker containerization. |

---

## Detailed Feature Log

### Feature 1: Asynchronous AI Processing Pipeline
- **Status**: Completed
- **Date**: 2026-09-28
- **Architectural Flow**:
  ```
  Citizen/Chatbot
        │  POST /grievance/submit
        ▼
   FastAPI API  ────────► Persist Grievance (status="Pending", processing_status="PENDING")
        │
   Enqueue Job
        ▼
  Message Queue (Redis `igrs:queue:grievances` / Thread-safe Fallback)
        │
   Dequeue Job (BLPOP)
        ▼
   AI Worker Thread/Process (Sets processing_status="PROCESSING")
        │
   Call Gemini 2.0 / NLP & Geocoding
        │
   ┌────┴────────────────────────┐
   ▼                             ▼
[Success]                   [Failure]
Update Category, Priority,   Retry with exponential backoff (2^retry s)
Region, Solution, Lat/Long   If retry > 3:
processing_status="COMPLETED" Move to Dead-Letter Queue (`igrs:queue:grievances:dlq`)
processed_at=now()           processing_status="FAILED", record `last_error`
  ```

#### Changes Implemented:
1. **Database Schema (`app.db.models.Grievance`)**:
   - Added `processing_status` (String, default=`"PENDING"`, indexed).
   - Added `retry_count` (Integer, default=`0`).
   - Added `last_error` (Text, nullable=`True`).
   - Added `processed_at` (DateTime, nullable=`True`).
2. **Pydantic Schemas (`app.db.schemas`)**:
   - Updated `GrievanceResponse` with async tracking fields.
   - Added `GrievanceStatusResponse` for real-time status polling.
   - Added `QueueStatsResponse` for queue depth, DLQ count, and worker health monitoring.
3. **Queue Service (`app.queue.queue_service.py`)**:
   - Implemented `GrievanceQueueService` supporting Redis lists (`RPUSH`/`BLPOP`) with automatic fallback to an in-memory queue when Redis is not running.
   - Dedicated Dead-Letter Queue (`igrs:queue:grievances:dlq`).
4. **AI Worker Service (`app.queue.worker.py`)**:
   - Background worker with exponential backoff retry mechanism ($2^{\text{retry}}$ seconds).
   - DLQ routing when retries exceed `MAX_RETRIES` (default: 3).
   - Embedded background worker thread managed via FastAPI startup/shutdown lifecycle.
   - Standalone CLI entry point (`python -m app.queue.worker`) for containerized worker deployments.
5. **API Endpoints (`app.routes.grievance.py`)**:
   - `POST /grievance/submit`: Instant submission (<50ms), returns 201 Created with `processing_status: "PENDING"`.
   - `GET /grievance/{id}/status`: Polling endpoint returning classification progress and AI output.
   - `GET /grievance/queue/stats`: Admin monitoring endpoint for queue and DLQ metrics.
   - `POST /grievance/{id}/retry`: Admin endpoint to re-enqueue failed jobs from the DLQ.

### Feature 2: Redis Caching + Database Query Optimization
- **Status**: Completed
- **Date**: 2026-09-28
- **Architectural Flow**:
  ```
                     Request (Citizen / Admin Dashboard)
                                   │
                                   ▼
                            FastAPI Route
                                   │
                         ┌─────────▼─────────┐
                         │    Cache Layer    │
                         │ (Redis / Memory)  │
                         └─────────┬─────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
              [Cache HIT]                   [Cache MISS]
          X-Cache: HIT (instant)        X-Cache: MISS
          Return cached response        Query DB / Run ML models
                                        Store in Redis with TTL
                                        Return fresh response
  ```

#### Changes Implemented:
1. **Cache Service Layer (`app.cache.cache_service.py`)**:
   - Production-ready Redis client with automatic, thread-safe in-memory fallback (supporting TTLs and lazy eviction).
   - Telemetry tracking: cache hits, misses, hit ratio %, active keys count, and backend status.
   - Pattern-based cache invalidation (`delete_pattern`) supporting wildcards (e.g. `analytics:*`, `analytics:hotspots*`).
   - Standardized TTL configurations:
     - `TTL_FORECAST = 1800` (30 minutes) for `/analytics/forecast/{category}`
     - `TTL_HOTSPOTS = 600` (10 minutes) for `/analytics/hotspots`
     - `TTL_TRENDS = 3600` (1 hour) for `/analytics/hotspots/trends`
2. **Database Schema & Index Optimizations (`app.db.models.Grievance`)**:
   - Added single-column and composite indexes via SQLAlchemy `__table_args__`:
     - `idx_grievance_category` on `category` (Hotspot dominance & Category forecasting)
     - `idx_grievance_created_at` on `created_at` (Timeline queries, trend ordering, and recency filters)
     - `idx_grievance_region` on `region` (Geographic aggregation and macro-hotspot grouping)
     - `idx_grievance_status_priority` composite index on `(status, priority)` (Officer routing, triage, and SLA escalation)
3. **Query Optimization in Analytics Services**:
   - `app/services/hotspot_service.py`: Replaced full table scans (`db.query(Grievance).all()`) with projected column queries (`region`, `latitude`, `longitude`, `category`) and database-level null filters. Added deterministic `finally: db.close()` connection recycling.
   - `app/services/hotspot_trend_service.py`: Replaced heavy object fetches with column-pruned DB queries and session closing.
4. **Automated Cache Invalidation**:
   - AI Processing Pipeline (`app/queue/worker.py`): Invalidation of `analytics:hotspots*` whenever a newly geolocated grievance is classified.
   - Model Retraining (`POST /analytics/retrain`): Invalidates all `analytics:*` keys upon Prophet model retraining.
   - Admin Status Update (`PUT /grievance/{id}/status`): Purges `analytics:*` cache.
5. **Observability & Management Endpoints (`app.routes.analytics.py`)**:
   - `GET /analytics/cache/stats`: Telemetry endpoint reporting hits, misses, hit ratio percentage, active keys, and backend type.
   - `POST /analytics/cache/clear`: Purges cache keys matching a pattern or completely flushes the store.
   - `X-Cache` HTTP response header (`HIT` or `MISS`) added to all analytics routes for client-side and network latency inspection.
6. **Query Profiling & Migration Tool (`app.db.optimize_indexes.py`)**:
   - Auto-executes `CREATE INDEX IF NOT EXISTS` for seamless DB upgrades on PostgreSQL (Neon) and local environments.
   - Interactive `EXPLAIN (ANALYZE)` benchmarking tool comparing query execution plans and index scans.
7. **Automated Test Suite (`backend/test_feature_2.py`)**:
   - 5 comprehensive unit & integration tests covering cache get/set/miss, pattern invalidation, model index verification, telemetry endpoints, and HTTP `X-Cache` response verification.

### Feature 3: Automated Grievance Routing & Load-Balancing Engine
- **Status**: Completed
- **Date**: 2026-09-28
- **Architectural Flow**:
  ```
                     Citizen Complaint
                             │
                             ▼
               AI Classification (Gemini 2.0)
             [Category, Region, Priority Tier]
                             │
                             ▼
  ┌────────────────────────────────────────────────────────┐
  │         Automated Routing & Scoring Engine             │
  │                                                        │
  │  Score = Category_Match (max 50)                       │
  │        + Geographic_Jurisdiction (max 30)              │
  │        + Priority_SLA_Capability (max 20)              │
  │        - Active_Workload_Penalty (scale 40)            │
  │                                                        │
  │  Hard Constraint: active_cases < max_capacity          │
  └──────────────────────────┬─────────────────────────────┘
                             │
            ┌────────────────┴────────────────┐
            ▼                                 ▼
   [Assigned Officer]                [SLA Deadline Set]
   Highest-scoring eligible          CRITICAL: +12 hours
   department officer assigned       HIGH:     +24 hours
   with audit metadata               MEDIUM:   +48 hours
                                     LOW:      +96 hours
                             │
                             ▼
  ┌────────────────────────────────────────────────────────┐
  │             SLA Breach & Escalation Loop               │
  │  Continuous / Periodic Audit:                         │
  │  If now > sla_deadline & status != Resolved:           │
  │  1. Flag sla_breached=True, escalated=True             │
  │  2. Bump Priority (e.g. MEDIUM -> HIGH -> CRITICAL)    │
  │  3. Auto-rebalance: Re-route from backlogged officer   │
  └────────────────────────────────────────────────────────┘
  ```

#### Mathematical Scoring Model:
$$\text{Routing Score} = S_{\text{cat}} + S_{\text{geo}} + S_{\text{prio}} - S_{\text{workload}}$$

1. **Category Match ($S_{\text{cat}}$, max 50 pts)**:
   - Exact department match: $+50.0$
   - Substring / specialty match: $+35.0$
   - General / Public Grievance department: $+20.0$
   - Department mismatch: $0.0$ (disqualified from assignment if matching officers exist)
2. **Geographic Match ($S_{\text{geo}}$, max 30 pts)**:
   - Exact region jurisdiction match: $+30.0$
   - Sub-region / district match: $+20.0$
   - All-region / neutral jurisdiction: $+10.0$
   - Mismatch: $0.0$
3. **Priority & SLA Capability ($S_{\text{prio}}$, max 20 pts)**:
   - CRITICAL / HIGH: $+20.0$ (utilization $< 40\%$), $+12.0$ (utilization $< 75\%$), $+5.0$ (otherwise)
   - MEDIUM: $+12.0$ (utilization $< 70\%$), $+6.0$ (otherwise)
   - LOW: $+8.0$
4. **Workload Penalty ($S_{\text{workload}}$, scale 40 pts)**:
   - Active cases = count of non-terminal complaints (`Pending`, `In Progress`, `PROCESSING`, `RETRYING`) assigned to officer.
   - If $\text{active\_cases} \ge \text{max\_capacity}$: Officer is **disqualified** ($\text{penalty} = 999.0$), preventing backlog accumulation.
   - Otherwise: $\text{Penalty} = \left(\frac{\text{active\_cases}}{\text{max\_capacity}}\right) \times 40.0 + (\text{active\_cases} \times 2.0)$

#### Changes Implemented:
1. **Database Schema Enhancements (`app.db.models`)**:
   - **`UserRole` Enum**: Added `officer = "officer"` alongside `user` and `admin`.
   - **`User` Table**: Added `department` (String 100), `region` (String 150), `max_capacity` (Integer, default 10), and `is_active` (Boolean, default True).
   - **`Grievance` Table**:
     - `assigned_officer_id` (ForeignKey to `users.id`, indexed).
     - `assigned_officer` relationship and `@property assigned_officer_name`.
     - `sla_deadline` (DateTime, indexed).
     - `sla_breached` (Boolean, default False, indexed).
     - `escalated` (Boolean, default False, indexed).
     - `escalated_at` (DateTime, nullable).
     - `routing_score` (Float, score awarded by engine).
     - `routing_metadata` (Text JSON with candidate breakdown, timestamps, and reasoning).
2. **Routing & SLA Engine (`app.services.routing_engine.py`)**:
   - `evaluate_officers`: Calculates candidate scores across all active officers with full parameter breakdown.
   - `find_best_officer`: Selects top-scoring eligible candidate with tie-breaking and graceful capacity fallback.
   - `route_grievance`: Assigns best officer, computes SLA deadline, and records transparent JSON audit metadata.
   - `assign_manually`: Administrative manual assignment / override with audit reason.
   - `check_and_escalate_slas`: Scans open cases for SLA deadline breaches, flags violations, bumps priority tiers, and auto-reassigns overloaded officers.
   - `get_all_officers_with_workload`: Aggregates active workloads, departments, and capacity across all officers.
3. **AI Pipeline Integration (`app/queue/worker.py`)**:
   - Integrated `routing_engine.route_grievance(db, grievance)` immediately following Gemini 2.0 / NLP classification.
   - Full lifecycle from citizen submission $\to$ asynchronous queue $\to$ AI classification $\to$ automated routing & SLA assignment.
4. **API Endpoints (`app.routes.grievance.py`)**:
   - `GET /grievance/officers`: Admin view of all officers, departments, jurisdictions, capacity, and real-time active cases.
   - `POST /grievance/officers`: Admin registration of department officers with capacity and jurisdiction limits.
   - `GET /grievance/assigned-to-me`: Officer endpoint to view complaints assigned to their queue.
   - `POST /grievance/{id}/auto-route`: Admin on-demand automated routing recalculation with candidate score breakdowns.
   - `POST /grievance/{id}/assign`: Admin manual assignment override.
   - `POST /grievance/sla/escalate`: System-wide SLA breach audit, priority escalation, and workload rebalancing.
   - `GET /grievance/sla/breached`: Monitoring endpoint listing all unresolved complaints exceeding their SLA deadline.
5. **Schema Migration & Seeding Tools**:
   - `app/db/upgrade_feature_3.py`: Idempotent schema migration applying `ALTER TABLE` column additions and composite indexes.
   - `seed_officers.py`: Pre-populates officers across Water, Electricity, Roads, Sanitation, and Public Grievances matching the scenarios in `context/feature.md`.
6. **Automated Test Suites**:
   - `backend/test_feature_3.py`: 8 comprehensive unit tests validating mathematical scoring (Officer B vs A vs C), capacity limits, SLA calculation, SLA breach escalation, AI worker integration, and manual overrides.
   - `backend/test_routing_api.py`: 6 integration tests verifying all routing, officer management, and SLA escalation routes.

### Feature 4: Immutable Audit Trail + Role-Based Authorization
- **Status**: Completed
- **Date**: 2026-09-28
- **Architectural Flow**:
  ```
                     Grievance Lifecycle Events
                                 │
     ┌───────────────────────────┼───────────────────────────┐
     ▼                           ▼                           ▼
  [Citizen Action]         [AI Worker / Engine]        [Officer / Admin]
  - Submit (CREATED)       - Classify (AI_CLASSIFIED)  - Status Update
  - Withdraw (WITHDRAWN)   - Route (ASSIGNED)          - Upload Resolution
                           - Escalation (SLA_ESCALATED)- Manual Reassign
                                 │
                                 ▼
         ┌───────────────────────────────────────────────┐
         │     Audit Service (app.services.audit_service)│
         │  Guaranteed Append-Only Event Stream Ledger   │
         └───────────────────────┬───────────────────────┘
                                 │
                                 ▼
                     PostgreSQL / SQLite Table
                     (`grievance_events`)
                     - id (PK, Auto-increment)
                     - grievance_id (FK -> grievances.id)
                     - actor_id (FK -> users.id, nullable)
                     - actor_role (citizen/officer/admin/ai_worker/system)
                     - event_type (CREATED, AI_CLASSIFIED, ASSIGNED, etc.)
                     - old_value & new_value (state diff)
                     - timestamp (UTC now)
                     - metadata_json (context, reasoning, payload)
                                 │
                                 ▼
         ┌───────────────────────────────────────────────┐
         │       Strict Server-Side RBAC Enforcement      │
         │  Citizen : View own cases + Withdraw own      │
         │  Officer : View & update strictly assigned    │
         │  Admin   : Universal view, assign, reassign   │
         └───────────────────────────────────────────────┘
  ```

#### Role-Based Access Control (RBAC) Matrix:

| Actor Role | Create Grievance | View Own | View Assigned | View All | Update Status | Upload Resolution | Withdraw Case | Assign / Reassign | View Audit Trail | Analytics Admin |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Citizen** | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ *(Own only)* | ❌ | ✅ *(Own only)* | ❌ |
| **Officer** | ❌ | ❌ | ✅ | ❌ | ✅ *(Assigned only)* | ✅ *(Assigned only)* | ❌ | ❌ | ✅ *(Assigned only)* | ❌ |
| **Admin** | ✅ | ✅ | ✅ | ✅ | ✅ *(Any)* | ✅ *(Any)* | ✅ *(Any)* | ✅ *(Any)* | ✅ *(Any)* | ✅ |

#### Canonical Event Taxonomy:
1. `CREATED`: Initial complaint submission by citizen (`Pending`, `PENDING`).
2. `AI_CLASSIFIED`: Asynchronous worker outputs category, priority tier, geocodes, and solution.
3. `ASSIGNED`: Automated routing engine or administrator binds grievance to an officer.
4. `REASSIGNED`: Case transferred to a new department specialist or rebalanced from backlogged officer.
5. `STATUS_UPDATED`: Transition between states (e.g. `Pending` $\to$ `In Progress` / `Under Review`).
6. `RESOLUTION_UPLOADED`: Assigned officer or admin submits final corrective actions and marks `Resolved`.
7. `WITHDRAWN`: Citizen withdraws their complaint before resolution.
8. `SLA_BREACHED`: System audit flags overdue complaint exceeding resolution deadline.
9. `SLA_ESCALATED`: SLA priority escalated (e.g. `LOW` $\to$ `MEDIUM` $\to$ `HIGH` $\to$ `CRITICAL`).

#### Changes Implemented:
1. **Database Model & Relations (`app.db.models.GrievanceEvent`)**:
   - `__tablename__ = "grievance_events"` with composite indexes on `grievance_id`, `event_type`, `timestamp`, and `actor_id`.
   - Immutable relationship: `Grievance.events = relationship("GrievanceEvent", back_populates="grievance", cascade="all, delete-orphan", order_by="GrievanceEvent.timestamp.asc()")`.
   - Dynamic actor resolution property: `@property actor_name` resolving User names or automated system services (`AI Worker (Gemini 2.0)`, `System (Routing Engine)`).
2. **Audit Service Layer (`app.services.audit_service.py`)**:
   - `log_event`: Centralized append-only event dispatcher with structured metadata serialization.
   - `get_events_for_grievance`: Fast retrieval of complete chronological lifecycle events.
3. **Pydantic Schemas (`app.db.schemas`)**:
   - `GrievanceEventResponse`: Serialized representation of event records.
   - `GrievanceAuditTrailResponse`: Top-level audit response containing complaint summary and full event ledger.
   - `WithdrawGrievanceRequest`: Citizen withdrawal reason schema.
   - `UploadResolutionRequest`: Structured resolution report schema with solution, remarks, and action taken.
   - `UpdateStatusRequest`: Validated status update payload.
   - `ReassignGrievanceRequest`: Administrative reassignment schema.
4. **Server-Side Authorization & Ownership Enforcement (`app.auth.dependencies.py`)**:
   - `require_citizen`: Enforces citizen-only access boundaries (`role == UserRole.user`).
   - `require_officer`: Enforces officer-only access boundaries (`role == UserRole.officer`).
   - `require_admin`: Enforces administrative authority (`role == UserRole.admin`).
   - `enforce_grievance_access`: Object-level ownership validator preventing cross-tenant access. Returns HTTP 403 Forbidden with descriptive rationale.
5. **API Route Handlers (`app.routes.grievance.py`)**:
   - `POST /grievance/submit`: Citizen submission now writes `CREATED` event to audit trail.
   - `POST /grievance/{id}/withdraw`: Citizen withdrawal endpoint verifying ownership and blocking terminal cases.
   - `PUT /grievance/{id}/status`: Enhanced status update handler enforcing that officers can only update assigned cases, and citizens are forbidden.
   - `POST /grievance/{id}/resolution`: Official resolution submission endpoint enforcing assigned officer authorization.
   - `POST /grievance/{id}/reassign`: Administrative officer transfer endpoint logging `REASSIGNED` event.
   - `GET /grievance/{id}/audit-trail` & `GET /grievance/{id}/events`: Audit ledger endpoint enforcing strict server-side ownership.
6. **Analytics Authorization (`app.routes.analytics.py`)**:
   - Protected `POST /analytics/retrain` and `POST /analytics/clear` with `require_admin`.
7. **Pipeline & Worker Integration (`app.queue.worker.py` & `app.services.routing_engine.py`)**:
   - Background AI worker logs `AI_CLASSIFIED` upon Gemini/NLP completion.
   - Routing engine logs `ASSIGNED` / `REASSIGNED` on automatic allocation.
   - SLA auditing logs `SLA_BREACHED` and `SLA_ESCALATED` upon deadline expiry.
8. **Frontend Audit Trail & Citizen Dashboard (`frontend/components/GrievanceList.tsx`)**:
   - Interactive **Audit Trail Modal**: Chronological timeline displaying event types, actor badges, timestamps, state transitions (`old_value` $\to$ `new_value`), and resolution remarks.
   - Citizen **Withdraw Grievance Action**: Inline withdrawal prompt with reason input for active complaints.
   - Status badge styling for "Withdrawn" complaints.
9. **Automated Test Suite (`backend/test_feature_4.py`)**:
   - 14 comprehensive unit and integration tests covering:
     - Append-only model immutability
     - Citizen submission, view own, and withdrawal permissions
     - Cross-citizen withdrawal prevention (403 Forbidden)
     - Terminal grievance withdrawal prevention (400 Bad Request)
     - Officer status update and resolution permissions
     - Cross-officer tampering prevention (403 Forbidden)
     - Admin reassignment and audit logging
     - Server-side audit trail access control
     - Full 5-step lifecycle simulation matching `context/feature.md` (`Created` $\to$ `AI Classified` $\to$ `Assigned` $\to$ `In Progress` $\to$ `Resolved`).

### Feature 5: Production-Grade Observability + CI/CD
- **Status**: Completed
- **Date**: 2026-09-28
- **Architectural Flow**:
  ```
                     GitHub Actions CI/CD Pipeline
                                   │
              ┌────────────────────┴────────────────────┐
              ▼                                         ▼
     [Backend CI: Python 3.11]              [Frontend CI: Node 20]
     - Flake8 Syntax & Complexity Lint      - ESLint Clean Code Audit
     - Bandit Security Vulnerability Scan   - TypeScript Compile Check
     - Unit & Integration Test Suites       - Next.js Turbopack Production Build
       (Features 1, 2, 3, 4, 5)             - Bundle Verification
              │                                         │
              └────────────────────┬────────────────────┘
                                   ▼
                   [Docker Multi-Stage Build & Scan]
                   - Backend Container (Distroless / Slim)
                   - Frontend Container (Next.js Standalone)
                   - Non-root user & Healthcheck Probes
                                   │
                                   ▼
              ┌──────────────────────────────────────────┐
              │      Runtime Production Observability    │
              │                                          │
              │  ASGI Observability Middleware           │
              │  - W3C Traceparent (OpenTelemetry)       │
              │  - Request ID & Latency Tracking         │
              │  - Normalized Route Histogram Buckets    │
              │                                          │
              │  Prometheus Metrics Registry             │
              │  - Counters (Requests, AI Calls, Errors) │
              │  - Gauges (Queue & DLQ Depth, Uptime)    │
              │  - Histograms (P50, P90, P95, Mean)      │
              │                                          │
              │  Grievance Lifecycle Redressal Engine    │
              │  - Submission -> AI Classification       │
              │  - AI -> Officer Assignment Delay        │
              │  - Officer Response & First Action       │
              │  - Total Resolution Duration (P50/P95)   │
              │  - SLA Compliance & Overdue Analytics    │
              └────────────────────┬─────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
             [Scrape Endpoint]           [Admin Dashboard]
             GET /metrics (Prometheus)   Interactive Telemetry
             GET /health/ready (K8s)     Live Vitals & Charts
  ```

#### Changes Implemented:
1. **Prometheus Metrics Registry (`app.observability.metrics`)**:
   - Thread-safe metric primitives (`Counter`, `Gauge`, `Histogram` with custom quantile reservoirs).
   - Generates official standard **Prometheus text exposition format (version 0.0.4)**.
   - Built-in metrics:
     - `igrs_http_requests_total{method, path, status}`
     - `igrs_http_request_errors_total{method, path, error}`
     - `igrs_http_request_duration_seconds{method, path}` (Histogram buckets)
     - `igrs_ai_requests_total{model, status}` & `igrs_ai_errors_total{model, error_type}`
     - `igrs_ai_request_duration_seconds{model}` (Histogram)
     - `igrs_database_query_duration_seconds{operation}` (Histogram)
     - `igrs_queue_wait_duration_seconds` & `igrs_grievance_processing_duration_seconds`
     - `igrs_queue_depth` & `igrs_dlq_depth` (Gauges)
     - `igrs_system_uptime_seconds` (Gauge)
2. **OpenTelemetry-Compatible ASGI Middleware (`app.observability.middleware`)**:
   - W3C Trace Context propagation (`traceparent` header standard).
   - `X-Request-ID` and `X-Response-Time-Ms` response injection.
   - URL path template normalization (e.g. `/grievance/108/status` $\to$ `/grievance/{id}/status`) preventing label cardinality explosion in time-series monitoring.
   - Unhandled exception trapping and error counter increments.
3. **Multi-Stage Grievance Lifecycle Engine (`app.observability.lifecycle_analyzer`)**:
   - Computes statistical engineering distributions across the complaint redressal lifecycle:
     - **Submission $\to$ AI Classification** (Mean, P50, P95)
     - **AI Classification $\to$ Officer Assignment Delay** (Mean, P50, P95)
     - **Assignment $\to$ Officer First Response Time** (Mean, P50, P95)
     - **Submission $\to$ Resolution Duration** (Mean, P50, P95, Min, Max)
   - Breakdown by category (Water, Electricity, Roads, Sanitation, etc.) and priority tiers (Critical, High, Medium, Low).
   - Overall SLA compliance rate (%) and overdue breached complaint auditing.
4. **Observability & Kubernetes Health Probes (`app.routes.observability`)**:
   - `GET /metrics`: Standard Prometheus scrapable text exposition endpoint.
   - `GET /observability/summary`: JSON telemetry overview with request latency percentiles, error rates, AI inference performance, and queue depths.
   - `GET /observability/lifecycle`: Multi-stage lifecycle redressal analytics.
   - `GET /health`: Comprehensive health check validating database and queue status.
   - `GET /health/ready`: Kubernetes readiness probe verifying database connectivity.
   - `GET /health/live`: Kubernetes liveness probe.
5. **Worker & Queue Instrumentation (`app.queue.worker`)**:
   - Queue wait latency tracking between enqueue timestamp and worker dequeue.
   - Gemini 2.0 / NLP inference duration measurement and AI success/error counters.
   - End-to-end complaint processing duration tracking.
6. **Frontend Observability & SLA Dashboard (`frontend/app/admin/dashboard/page.tsx`)**:
   - Dedicated "Observability" tab in Admin Portal.
   - Live HTTP request volume, error rate %, and P50/P95 latency cards.
   - AI model inference performance card.
   - Message Queue depth and Dead-Letter Queue status.
   - Multi-stage Grievance Lifecycle Timeline waterfall cards with SLA compliance %.
   - Quick links & badges for Prometheus `/metrics` and Kubernetes `/health/ready`.
7. **CI/CD Pipelines (GitHub Actions)**:
   - `.github/workflows/ci.yml`: Runs on PRs and pushes to `main`/`master` covering backend lint (`flake8`), security scan (`bandit`), unit/integration tests, frontend lint (`eslint`), type check (`tsc`), Next.js build verification, and multi-stage Docker builds.
   - `.github/workflows/cd.yml`: Automates container packaging and GitHub Container Registry (GHCR) publishing.
8. **Production Containerization**:
   - `backend/Dockerfile`: Multi-stage Python 3.11 container with non-root user and healthcheck.
   - `frontend/Dockerfile`: Multi-stage Next.js Node 20 container.
   - `docker-compose.yml`: Local production orchestrator for backend, frontend, postgres, redis, and prometheus.
   - `prometheus/prometheus.yml`: Scraper configuration targeting `backend:8000/metrics`.
9. **Automated Test Suite (`backend/test_feature_5.py`)**:
   - 15 comprehensive unit and integration tests covering:
     - Metric primitives (Counter, Gauge, Histogram, quantiles P50/P90/P95/P99)
     - Prometheus text exposition format validation
     - ASGI Middleware traceparent, request ID, response time, and path normalization
     - End-to-end grievance lifecycle analysis across synthetic event streams
     - All observability and health probe endpoints (`/metrics`, `/observability/summary`, `/observability/lifecycle`, `/health`, `/health/ready`, `/health/live`).

---


## Required API Keys & Environment Variables

| Variable | Type | Purpose | Where to Obtain (Free Tiers) | Setup Location |
|---|---|---|---|---|
| **`GEMINI_API_KEY`** | Required | AI grievance classification (`gemini-2.0-flash`) and solution suggestion engine | [Google AI Studio](https://aistudio.google.com/app/apikey) (Free tier) | `backend/.env` |
| **`OPENCAGE_API_KEY`** | Required | Geocodes extracted complaint regions to lat/long coordinates for maps & hotspots | [OpenCage Geocoding](https://opencagedata.com/) (2,500 free req/day) | `backend/.env` |
| **`DATABASE_URL`** | Required | PostgreSQL database connection string | [Neon Serverless Postgres](https://neon.tech/) or Local PostgreSQL | `backend/.env` |
| **`JWT_SECRET`** | Required | Secret string used for signing & verifying JWT authentication tokens | Generate via `python -c "import secrets; print(secrets.token_hex(32))"` | `backend/.env` |
| **`REDIS_URL`** | Optional | Message broker for distributed queue (Feature 1) and caching (Feature 2) | [Upstash Redis](https://upstash.com/) or local `redis://localhost:6379/0` *(In-memory fallback active if absent)* | `backend/.env` |
| **`ADMIN_EMAIL`** | Optional | Admin account email for initial admin seeding | Custom or defaults to `admin@igrs.com` | `backend/.env` |
| **`ADMIN_PASSWORD`** | Optional | Admin account password for initial admin seeding | Custom or defaults to `admin123` | `backend/.env` |
| **`AI_WORKER_MAX_RETRIES`** | Optional | Max retry attempts before routing a failed grievance job to DLQ | Integer (default: `3`) | `backend/.env` |

