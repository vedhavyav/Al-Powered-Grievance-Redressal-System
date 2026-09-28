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
