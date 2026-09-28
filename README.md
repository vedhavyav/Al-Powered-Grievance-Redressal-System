# AI-Powered Grievance Redressal System (IGRS)

**A Next-Generation Citizen Grievance Redressal Platform powered by AI, NLP, and Predictive Analytics**

## Overview

The **AI-Powered Grievance Redressal System (IGRS)** is a modern, intelligent, and fully automated platform designed to streamline how citizens submit grievances and how administrations resolve them.

Traditional grievance systems rely on lengthy forms, manual classification, delayed routing, and slow redressal.

**IGRS revolutionizes this process using:**

- 🧠 AI-powered classification
- 💬 Natural language chatbot grievance submission
- 📍 Automatic location extraction & geocoding
- 🔥 Priority prediction using NLP
- 📊 Admin analytics & hotspot forecasting
- 📈 Prophet-based time series forecasting
- 🌐 Modern Next.js + FastAPI architecture

This project is built for real-world scalability and can be deployed by local bodies, smart cities, and government offices.

---

## Key Features

### 👥 Citizen Features

- **Chatbot-based grievance filing** (no complex forms)
- **AI understands complaint**, extracts:
  - Category (Electricity, Roads, Water, Sanitation…)
  - Priority (High / Medium / Low)
  - Region / locality name
  - Latitude & Longitude
- **Real-time solution suggestion**
- **Track grievance status**
- **Option to withdraw grievance** (until resolved)
- **User-friendly dashboard**

### 🛠️ Admin Features

- **View all grievances** (sorted by priority/time)
- **Update grievance status**
- **Detailed view** with:
  - Category
  - Location coordinates
  - Suggested solution
  - Severity/priority
- **Analytics Dashboard** (hotspots, trends, forecasts)
- **Predictive Insights** powered by Prophet ML models
- **Role-based authentication**

### 🤖 AI & NLP Features

- **Powered by Google Gemini AI**
- **NLP pipeline** for:
  - Text classification
  - Entity extraction (NER)
  - Priority prediction
  - Region identification
  - Generating AI-based troubleshooting suggestions
- **Forecasting models** predict:
  - High grievance zones
  - Time-based complaint surges
  - Resource needs
  - Category-wise future trends

### 📈 ML Forecasting Features

- **Prophet Time Series Models** for each grievance category
- **Adaptive Learning System**:
  - Checks database for real complaint data
  - Uses actual data when sufficient records available
  - Falls back to trained synthetic data when needed
  - Automatic model retraining on time intervals
- **Season-aware predictions** (Monsoon, Summer, Winter, Post-Monsoon)
- **Region-specific forecasting** for major cities
- **Model Performance Metrics**:
  - MAE (Mean Absolute Error) < 20 for all categories
  - RMSE tracking for accuracy validation

---

## Architecture
```
frontend/     (Next.js + Tailwind + Framer Motion)
backend/      (FastAPI, SQLAlchemy, PostgreSQL, Gemini API)
ml_pipeline/  (Prophet Models, Synthetic Data Generation, Training Scripts)
```

### Architecture Flow

1. User interacts with the AI chatbot
2. NLP engine processes text → classification, region extraction
3. System stores structured grievance in PostgreSQL
4. Admin dashboard visualizes & manages grievances
5. **ML Pipeline** analyzes database:
   - Checks if sufficient real data exists
   - Predicts using actual data OR trained models
   - Generates forecasts for future complaint volumes
6. Analytics system predicts future hotspots

---

## Screenshots

| Homepage | User Dashboard |
| :---: | :---: |
| ![Homepage](screenshots/homepage.jpg) | ![User Dashboard](screenshots/Userdashboard1.jpg) |
| ![Homepage 2](screenshots/homepage2.jpg) | ![User Dashboard 2](screenshots/Userdashboard2.jpg) |

| Admin Dashboard | Analytics |
| :---: | :---: |
| ![Admin Dashboard](screenshots/Admindashboard.jpg) | ![Map](screenshots/map.jpg) |
| ![Admin Dashboard 2](screenshots/Admindashboard2.jpg) | ![Forecasting](screenshots/forecasting.jpg) |
---

## Tech Stack

### Frontend

- Next.js 14 (App Router)
- TypeScript
- TailwindCSS
- Framer Motion UI animations
- Axios

### Backend

- FastAPI (Python)
- Redis (Asynchronous Message Broker & High-Performance Response Cache)
- SQLAlchemy ORM with Composite Database Indexing
- PostgreSQL
- JWT Authentication
- CORS-enabled REST APIs

### AI/NLP

- Google Gemini API
- Custom NLP Pipeline
- Geocode API (Location → lat/long)
- Text classification & NER

### ML/Forecasting

- **Prophet** (Facebook's time series forecasting)
- **NumPy** & **Pandas** for data processing
- **Scikit-learn** for metrics evaluation
- **Joblib** for model serialization
- **Matplotlib** for visualization

---

## Folder Structure

### Frontend
```
frontend/
│── app/
│   ├── user/
│   ├── admin/
│   ├── auth/
│   └── components/
└── lib/
```

### Backend
```
backend/
│── app/
│   ├── auth/
│   ├── db/
│   ├── routes/
│   ├── services/
│   ├── utils/
│   └── main.py
└── venv/
```

### ML Pipeline
```
ml_pipeline/
│── synthetic_data_generation_igrs.py    # Generates seasonal synthetic data
│── prophet_training_igrs.py             # Trains Prophet models per category
```

---

## Setup & Installation

### 1️⃣ Clone Repository
```bash
git clone https://github.com/Krixna-Kant/AI-Powered-Grievance-Redressal-System
cd AI-Grievance-Management-System
```

### 🖥️ Backend Setup

> **Note**: Use Python 3.11 or 3.12 (Python 3.13 is incompatible with pinned versions of `prophet` and `numpy 1.26.4`).

#### Create Virtual Environment
```bash
cd backend
py -3.12 -m venv venv        # Or: uv venv venv --python 3.12
source venv/bin/activate     # Windows: .\venv\Scripts\activate
```

#### Install Dependencies
```bash
pip install -r requirements.txt
# Or faster with uv:
# uv pip install -r requirements.txt
```

#### Environment Variables

Create `.env` file:
```env
DATABASE_URL=postgresql://username:password@localhost:5432/igrs
JWT_SECRET=your_secret_key
GEMINI_API_KEY=your_gemini_key
```

#### Run Backend
```bash
uvicorn app.main:app --reload
```

### 🌐 Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

### 🤖 ML Pipeline Setup

#### Install ML Dependencies
```bash
cd ml_pipeline
pip install numpy==1.26.4 prophet==1.1.5 cmdstanpy==1.1.0 pandas scikit-learn matplotlib joblib
```

#### Generate Synthetic Data (Optional - for training)
```bash
python synthetic_data_generation_igrs.py
```

#### Train Prophet Models
```bash
python prophet_training_igrs.py
```

This will:
- Train separate Prophet models for each category
- Generate `up_forecast.pkl` (saved models)
- Create `up_model_metrics.csv` (performance metrics)
- Display forecast plots for validation

**App will run at:**  
👉 http://localhost:3000

**Backend runs at:**  
👉 http://localhost:8000

---

## API Endpoints

### Authentication

| Method | Endpoint        | Description   |
|--------|-----------------|---------------|
| POST   | /auth/register  | Register user |
| POST   | /auth/login     | Login user    |

### AI APIs

| Method | Endpoint        | Purpose                                    |
|--------|-----------------|--------------------------------------------|
| POST   | /ai/classify    | Classify complaint, predict category/priority |
| POST   | /ai/solution    | Generate AI solution                       |

### Grievance APIs

| Method | Endpoint                   | Purpose                  |
|--------|----------------------------|--------------------------|
| POST   | /grievance/submit          | Submit grievance         |
| GET    | /grievance/my-grievances   | User grievances          |
| GET    | /grievance/all             | Admin only               |
| PUT    | /grievance/{id}/status     | Update grievance status  |

### Analytics & Forecasting APIs

| Method | Endpoint                   | Purpose                          |
|--------|----------------------------|----------------------------------|
| GET    | /analytics/forecast        | Get category-wise predictions    |
| GET    | /analytics/hotspots        | Identify high-complaint regions  |
| GET    | /analytics/trends          | Historical trend analysis        |

---

## How AI Works (Internal Logic)

### 1. Gemini Classification

When user enters:

> "Water pipeline leakage in Alambagh"

NLP model predicts:

- `category = "Water Supply"`
- `priority = "High"`
- `region = "Alambagh, Lucknow"`

### 2. Geocoding

Region → Latitude/Longitude

### 3. Solution Engine

Gemini generates:

> "Send Nagar Nigam team for pipeline inspection; high chance of underground crack."

### 4. Storage

Stores full structured data in PostgreSQL.

---

## ML Forecasting Pipeline

### How Prophet Models Work

1. **Data Collection**
   - System checks PostgreSQL for actual grievance data
   - Minimum threshold: 60 days of data per category
   
2. **Adaptive Prediction Logic**
```python
   if database_has_sufficient_data():
       predictions = prophet_model.predict(real_data)
   else:
       predictions = prophet_model.predict(synthetic_training_data)
```

3. **Automatic Retraining**
   - Models retrain periodically (weekly/monthly)
   - Incorporates new real-world complaint patterns
   - Adapts to seasonal variations automatically

4. **Seasonal Awareness**
   - **Monsoon (Jun-Sep)**: Infrastructure +60%, Sanitation +40%
   - **Summer (Mar-May)**: Utilities +50% (power cuts, water shortage)
   - **Winter (Dec-Feb)**: Medical +10% (seasonal diseases)
   - **Post-Monsoon (Oct-Nov)**: Medical +30% (dengue, malaria)

### Model Performance

| Category        | MAE   | RMSE  | Accuracy |
|----------------|-------|-------|----------|
| Infrastructure | 19.65 | 24.27 | ~15% error |
| Utilities      | 18.47 | 23.14 | ~18% error |
| Sanitation     | 14.78 | 18.65 | ~12% error |
| Medical        | 12.22 | 15.80 | ~10% error |

*All models achieve <25% error rate, which is excellent for real-world forecasting.*

### Synthetic Data Generation

**File**: `synthetic_data_generation_igrs.py`

- Covers **10 major UP cities**: Lucknow, Kanpur, Varanasi, Agra, Meerut, Prayagraj, Gorakhpur, Bareilly, Noida, Ghaziabad
- **4 main categories**: Infrastructure, Utilities, Sanitation, Medical
- **Date range**: Jan 2024 - Dec 2025 (2 years)
- **Features**:
  - Population-weighted complaint volumes
  - Seasonal multipliers
  - Random noise for realism
  - 29,200 total records (730 days × 10 regions × 4 categories)

---

## What Makes This System Better Than Traditional Grievance Portals

### ❌ Old Systems

- Long, complicated forms
- No automated classification
- Manual routing → slow responses
- No location intelligence
- No AI suggestions
- Citizens unsure which department to select
- **No predictive analytics**
- **No resource planning**

### ✅ Our System

- Chatbot-based instant submission
- AI handles all classification
- Region detection & mapping
- Smart admin dashboard
- Predictive analytics
- Faster resolution workflow
- Easy for both citizens & government
- **ML-powered forecasting** for proactive governance
- **Adaptive learning** from real complaint data
- **Season-aware predictions** for resource allocation

---

## Future Enhancements

- Voice-based grievance submission
- WhatsApp chatbot integration
- Multi-language support (Hindi, regional languages)
- Auto-assigning grievances to department officers
- Real-time heatmaps
- Mobile app (iOS & Android)
- **Deep learning models** for image-based complaints (pothole detection, garbage spots)
- **Integration with IoT sensors** for real-time monitoring
- **Blockchain** for transparent grievance tracking

---

## Author

**Krishna** – Full Stack Developer & AI Engineer

AI-Powered-Grievance-Redressal-System

---

## License

This project is licensed under the MIT License.

---

## Support

If you like this project, please ⭐ **star the repo** and share your feedback!

---

## Acknowledgments

- **Facebook Prophet** for time series forecasting
- **Google Gemini AI** for NLP capabilities
- **Uttar Pradesh Government** (inspiration for use case)
- Open-source community for amazing tools