Here is the complete guide to running the **AI-Powered Grievance Redressal System (IGRS)** on your machine:

---

### 1. Prerequisites

Ensure you have the following installed and running:
- **Python 3.12** (already present in [backend/venv](file:///c:/Users/Public/OneDrive/Desktop/vs%20code%20backup/AI-Powered-Grievance-Redressal-System/backend/venv))
- **Node.js** (v18+ or v20+) & **npm**
- **PostgreSQL** database service
- **Redis** service (running on `localhost:6379`)

---

### 2. Configure Environment Variables

Open [backend/.env](file:///c:/Users/Public/OneDrive/Desktop/vs%20code%20backup/AI-Powered-Grievance-Redressal-System/backend/.env) and make sure your credentials and API keys are populated:

```env
DATABASE_URL=postgresql://<username>:<password>@localhost:5432/<db_name>
JWT_SECRET=your_secret_key_here
GEMINI_API_KEY=your_gemini_api_key
OPENCAGE_API_KEY=your_opencage_key
REDIS_URL=redis://localhost:6379/0
AI_WORKER_MAX_RETRIES=3
ADMIN_EMAIL=admin@igrs.com
ADMIN_PASSWORD=admin123
```

---

### 3. Initialize Database & Admin User

Open a terminal in the `backend` folder:

```powershell
cd "backend"

# 1. Activate the virtual environment
.\venv\Scripts\activate

# 2. (Optional, if packages need updating)
pip install -r requirements.txt

# 3. Create the database tables
python create_db.py

# 4. Create the default admin account
python create_admin.py

# 5. (Optional) Seed mock officers
python seed_officers.py
```

---

### 4. Start the Backend Server

With the virtual environment activated inside `backend`:

```powershell
uvicorn app.main:app --reload --port 8000
```
- **Backend API**: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **Interactive Swagger Docs**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

### 5. Start the Frontend Server

Open a second terminal window:

```powershell
cd "frontend"

# Install dependencies (if not already installed)
npm install

# Start Next.js development server
npm run dev
```
- **Frontend App**: [http://localhost:3000](http://localhost:3000)

---

### 6. Default Login Credentials

- **Admin Portal**: Log in at `/auth` or `/admin` using:
  - **Email**: `admin@igrs.com` (or the value set in [backend/.env](file:///c:/Users/Public/OneDrive/Desktop/vs%20code%20backup/AI-Powered-Grievance-Redressal-System/backend/.env))
  - **Password**: `admin123`
- **Citizen / User**: You can register a new citizen account directly from the signup page.

---

### 7. Run via Docker Compose (All-in-One Stack)

To run the entire ecosystem (Backend, Frontend, PostgreSQL, Redis, and Prometheus) in isolated production containers:

```powershell
docker compose up --build
```

- **Frontend App**: [http://localhost:3000](http://localhost:3000)
- **Backend API**: [http://localhost:8000](http://localhost:8000)
- **Prometheus Dashboard**: [http://localhost:9090](http://localhost:9090)

---

### 8. Production Observability & Health Endpoints

- **Prometheus Scrape Exposition**: `GET http://localhost:8000/metrics`
- **JSON Telemetry & Latencies**: `GET http://localhost:8000/observability/summary`
- **Grievance Lifecycle Engine**: `GET http://localhost:8000/observability/lifecycle`
- **Kubernetes Readiness Probe**: `GET http://localhost:8000/health/ready`
- **Kubernetes Liveness Probe**: `GET http://localhost:8000/health/live`
- **Admin Observability UI**: Accessible in the Admin Portal under the **"Observability"** tab.

---

### 9. Run Automated Test Suites

To execute the unit and integration tests across all enhancement features:

```powershell
cd "backend"
.\venv\Scripts\activate

# Feature 2: Redis Caching & DB Indexing
python -m unittest test_feature_2.py

# Feature 3: Automated Routing & Load-Balancing
python -m unittest test_feature_3.py test_routing_api.py

# Feature 4: Immutable Audit Trail & RBAC
python -m unittest test_feature_4.py

# Feature 5: Observability & Grievance Lifecycle
python -m unittest test_feature_5.py
```