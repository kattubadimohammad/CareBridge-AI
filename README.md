# CareBridge AI — Elderly Care and Medication Management Platform

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

CareBridge AI is an accessible, reliable, and intelligent elderly care and medication adherence platform. Designed with seniors and caregivers in mind, it bridges the gap between daily medication routines, timely reminders, caregiver visibility, and automated escalation for missed doses.

---

## 🌟 Key Features

1. **High-Performance FastAPI Backend**  
   Modern, asynchronous Python backend with automatic OpenAPI/Swagger documentation, fast execution, and modular architecture.

2. **Dual Database Architecture (SQLAlchemy)**  
   - **Local Development:** Zero-setup local SQLite database.  
   - **Production:** Fully compatible with persistent cloud databases (e.g., Cloud SQL PostgreSQL) via standard connection strings.

3. **Cloud Scheduler Integration**  
   Secure automated endpoints for periodic cron triggers to evaluate upcoming doses, issue reminder notifications, and trigger caregiver alerts on overdue medications.

4. **Senior-Centric Passcode Authentication & RBAC**  
   - **Elderly Mode:** Simplified, large-keypad numeric passcode login.  
   - **Caregiver & Family Mode:** Secure role-based access control (RBAC) to manage care recipients, review adherence logs, and configure schedules.  
   - **Admin Mode:** System monitoring and audit trails.

5. **Automated Notification & Escalation Service**  
   Real-time email and webhook alerts for caregivers when scheduled doses are pending, taken, or critically overdue.

6. **Accessible, Senior-Friendly UI (Jinja2 + CSS)**  
   Designed following WCAG 2.1 AA accessibility guidelines: high contrast ratios, large readable typography, touch-friendly touch targets, and distraction-free layouts.

7. **Cloud-Native & Containerized**  
   Production-ready Dockerfile optimized for Google Cloud Run with low memory footprint and sub-second cold starts.

---

## 📁 Project Structure

```text
Catalyst_Hackathon_2026/
├── .env.example              # Environment variables template
├── .gitignore                # Git ignore configuration for Python & SQLite
├── Dockerfile                # Production container specification (Cloud Run ready)
├── GEMINI.md                 # Hackathon guidelines & rules (immutable)
├── README.md                 # Project documentation
├── requirements.txt          # Python dependencies
├── app/
│   ├── __init__.py
│   ├── config.py             # Pydantic Settings & environment validation
│   ├── database.py           # SQLAlchemy engine & session management
│   ├── main.py               # FastAPI application entrypoint
│   ├── models/               # SQLAlchemy ORM models (Users, Medications, Logs)
│   │   └── __init__.py
│   ├── routers/              # API endpoints and Jinja2 web views
│   │   └── __init__.py
│   ├── schemas/              # Pydantic schemas (Request/Response validation)
│   │   └── __init__.py
│   ├── services/             # Business logic (notifications, scheduler, auth)
│   │   └── __init__.py
│   ├── static/               # Static assets (CSS, JS)
│   │   ├── css/
│   │   │   └── style.css
│   │   └── js/
│   │       └── app.js
│   └── templates/            # Accessible Jinja2 HTML templates
│       ├── base.html
│       └── index.html
└── tests/                    # Automated test suite
    ├── __init__.py
    └── test_health.py
```

---

## 🚀 Getting Started (Local Development)

### Prerequisites
- Python 3.10+ (Python 3.11 recommended)
- Git

### 1. Clone & Set Up Virtual Environment

```bash
# Clone the repository
git clone https://github.com/kattubadimohammad/catalyst-2026-submission.git
cd Catalyst_Hackathon_2026

# Create and activate virtual environment
python -m venv .venv

# Windows (PowerShell):
.venv\Scripts\Activate.ps1

# Linux / macOS:
source .venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure Environment Variables

```bash
# Copy example configuration
cp .env.example .env
```

### 4. Run the Development Server

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- Web Interface: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- Interactive API Docs (Swagger UI): [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## ☁️ Render Deployment (Free Tier)

CareBridge AI can be deployed on Render Free Web Service either via Render Blueprints (`render.yaml`) or manual configuration:

### Option A: Turnkey Blueprint Deployment
1. Connect your repository to Render.
2. Select **Blueprints** and Render will automatically detect `render.yaml`.
3. Review environment variables and click **Apply**.

### Option B: Manual Web Service Setup
- **Environment:** `Python`
- **Region:** `Oregon (US West)` or any preferred region
- **Branch:** `main`
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Health Check Path:** `/api/health`

### Required Environment Variables:
| Variable | Value / Description |
|---|---|
| `ENVIRONMENT` | `production` |
| `APP_SECRET_KEY` (or `JWT_SECRET`) | Strong random string (minimum 32 characters) |
| `DATABASE_URL` | `sqlite:///./carebridge.db` (ephemeral demo) or Render PostgreSQL connection string (`postgresql://...`) |
| `CRON_API_KEY` | Secret token for securing `/api/cron/check-reminders` |
| `SMTP_ENABLED` | `false` (uses built-in audit & simulation mode on Render Free) |

> [!NOTE]
> **Render Free Restrictions & Safe Notification Demonstration:**
> 1. **Ephemeral Disk:** SQLite data will reset when the free service spins down or restarts. For persistent data, link a Render PostgreSQL database via `DATABASE_URL`.
> 2. **SMTP Port Block:** Render Free blocks outbound SMTP ports 25, 465, and 587. CareBridge AI provides a built-in **Simulation Mode** (`SMTP_ENABLED=false` by default) which safely evaluates schedules, dispatches reminders, logs them to the console, and records complete delivery audits in the database visible on the caregiver portal.

---

## 🐳 Docker & Cloud Run Deployment

### Build and Run Locally with Docker

```bash
# Build Docker image
docker build -t carebridge-ai .

# Run container locally
docker run -p 8080:8080 --env-file .env carebridge-ai
```

### Deploy to Google Cloud Run

```bash
gcloud run deploy carebridge-ai \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars ENVIRONMENT=production
```

---

## 🔒 Security & Data Privacy Policy
- **Zero Confidential Data Policy:** The project strictly avoids storing or referencing proprietary company or customer credentials or internal data.
- **Passcode Hashing:** All user and senior passcodes are cryptographically hashed using bcrypt.
- **Scheduler Endpoint Protection:** Cloud Scheduler webhooks require secure header token validation (`X-Scheduler-Token`).

---

## 📄 License
This project is developed as part of Catalyst Hackathon 2026 under the MIT License.
