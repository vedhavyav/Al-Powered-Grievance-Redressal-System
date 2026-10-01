# Errors and Resolution Log

## 1. Setup Environment Configuration

The required environment variables for the backend:
```env
DATABASE_URL=postgresql://username:password@localhost:5432/igrs
JWT_SECRET=your_secret_key
GEMINI_API_KEY=your_gemini_key
ADMIN_EMAIL=admin@igrs.com
ADMIN_PASSWORD=admin123
```
- Status: **Resolved** (`backend/.env` and `backend/.env.example` have been created).

---

## 2. Error Encountered While Setting Up Backend

```
error: subprocess-exited-with-error
  
  × Preparing metadata (pyproject.toml) did not run successfully.
  │ exit code: 1
  ╰─> [22 lines of output]

  Installing backend dependencies ... done
  Preparing metadata (pyproject.toml) ... error
  error: subprocess-exited-with-error
  
  × Preparing metadata (pyproject.toml) did not run successfully.
  │ exit code: 1
  ╰─> [22 lines of output]
```

### Root Cause
1. **Python Version Incompatibility (Python 3.13 vs NumPy 1.26.4 & Prophet 1.1.5)**:
   - When running `python -m venv venv`, Windows defaulted to Python 3.13 (`Python 3.13.13`).
   - `numpy==1.26.4` and `prophet==1.1.5` have no prebuilt binary wheels for Python 3.13. Pip attempted to build `numpy==1.26.4` from source using `meson-python` / `pyproject.toml`, which failed because numpy 1.26.4 does not support Python 3.13 C-API changes.
2. **File Encoding**:
   - `backend/requirements.txt` was encoded in UTF-16LE instead of standard UTF-8.

### Resolution Steps Applied
1. **Converted `backend/requirements.txt` to standard UTF-8** encoding.
2. **Recreated the virtual environment with Python 3.12** (`C:\Users\vadit\AppData\Local\Programs\Python\Python312\python.exe`), which is the officially supported target for NumPy 1.26.4 and Prophet 1.1.5:
   ```bash
   cd backend
   uv venv venv --python 3.12 --clear
   # OR with py launcher:
   # py -3.12 -m venv venv
   ```
3. **Installed all dependencies**:
   ```bash
   uv pip install -r requirements.txt --python venv\Scripts\python.exe
   ```
   All 106 packages (including FastAPI, SQLAlchemy, Uvicorn, NumPy 1.26.4, Prophet 1.1.5, Scikit-learn, etc.) installed successfully using pre-built wheels.
4. **Environment & Auth Fixes**:
   - Created `backend/.env` and `backend/.env.example`.
   - Updated `backend/app/auth/utils.py` so that `SECRET_KEY` uses `JWT_SECRET` from environment variables.
   - Updated `backend/create_admin.py` with fallback defaults.
5. **Verification**:
   - Verified `backend/app/main.py` imports cleanly with zero errors.



## 3. Frontend "next start" Does Not Work with "output: export"

```
npm run start
Error: "next start" does not work with "output: export" configuration. Use "npx serve@latest out" instead.
```

### Root Cause
- `output: "export"` in `frontend/next.config.ts` configured Next.js for a purely static HTML export into the `frontend/out` directory.
- Next.js's built-in Node production server (`next start`) explicitly disallows running against static exports because there is no Node server artifact to serve.
- Additionally, `frontend/Dockerfile` specifies `CMD ["npm", "start"]`, which would also fail inside Docker when `output: "export"` is enabled.

### Resolution Steps Applied
1. **Configured Conditional Static Export**:
   - Updated `frontend/next.config.ts` so `output: "export"` is only enabled when `process.env.STATIC_EXPORT === "true"` (e.g. for static Cloudflare Pages builds).
   - In standard mode, Next.js builds the optimized production application with Node runtime support.
2. **Added `serve` NPM Script**:
   - Added `"serve": "npx serve@latest out"` to `frontend/package.json` for testing static export builds if needed.
3. **Updated Baseline Browser Mapping**:
   - Installed `baseline-browser-mapping@latest` to eliminate the build warning.
4. **Verification**:
   - Ran `npm run build` -> Compiled successfully (`12/12` pages generated).
   - Ran `npm run start` -> Verified server starts and is ready on `http://localhost:3000`.

- Status: **Resolved**

---

## 4. Docker Command Not Recognized

```powershell
docker compose build
docker : The term 'docker' is not recognized as the name of a cmdlet, function, script file, or operable program.
```

### Root Cause
- Docker Desktop is not installed on this Windows machine or its executable (`docker.exe`) is not present in the system environment `PATH`.

### Resolution & Options
1. **Native Execution (Recommended for Local Dev)**:
   - Docker is completely optional for local development. The app runs directly via:
     - **Backend**: `uvicorn app.main:app --reload --port 8000` (Python 3.12 venv)
     - **Frontend**: `npm run dev` or `npm run build && npm run start` (Node v22)
     - **Databases**: Local PostgreSQL (port 5432) & Redis (port 6379).
2. **If Docker Compose is Desired**:
   - Install **Docker Desktop for Windows** from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/).
   - Ensure the WSL 2 backend is selected during installation.
   - Restart the terminal and verify with:
     ```powershell
     docker --version
     docker compose version
     ```
   - Once installed, `docker compose up --build` can be executed.

- Status: **Documented / Actionable**

---

## 5. Render Deploy Build Failure: google-api-core and grpcio-status Conflict (Python 3.14)

```text
ERROR: Cannot install google-api-core[grpc]==2.28.1 and grpcio-status==1.71.2 because these package versions have conflicting dependencies.
The conflict is caused by:
    The user requested grpcio-status==1.71.2
    google-api-core[grpc] 2.28.1 depends on grpcio-status<2.0.0 and >=1.75.1; python_version >= "3.14" and extra == "grpc"
Additionally, some packages in these conflicts have no matching distributions available for your environment:
    grpcio-status
ERROR: ResolutionImpossible
==> Build failed 😞
```

### Root Cause
1. **Render Defaulting to Python 3.14 (`cp314`)**:
   - Without an explicit Python version pinned, Render defaults to its latest Python version (Python 3.14).
   - In Python 3.14, `google-api-core[grpc]` requires `grpcio-status >= 1.75.1`, which clashed with the rigid pin `grpcio-status==1.71.2` in `requirements.txt`.
   - Furthermore, `grpcio-status`, `prophet`, and `numpy==1.26.4` do not have pre-built distributions for Python 3.14.
2. **Pinned `grpcio-status`**:
   - `grpcio-status` was rigidly pinned to `1.71.2` while `grpcio` was `1.76.0`.

### Resolution Steps Applied
1. **Pinned Python Version to 3.12**:
   - Created `.python-version` files (containing `3.12.8`) in both the repository root and `backend/`.
   - Created `runtime.txt` files (containing `python-3.12.8`) in both the repository root and `backend/`.
   - In Render Dashboard under **Environment Variables**, set:
     ```env
     PYTHON_VERSION=3.12.8
     ```
2. **Loosened `grpcio-status` in `backend/requirements.txt`**:
   - Changed `grpcio-status==1.71.2` to `grpcio-status>=1.71.2,<2.0.0` to permit compatibility across minor versions.

- Status: **Resolved**