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
   - **Production:** Fully compatible with managed PostgreSQL (e.g., Render PostgreSQL, Supabase, Cloud SQL) via standard connection strings.

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

7. **Cloud-Native & Container Ready**  
   Turnkey one-click deployment on Render with managed PostgreSQL and background scheduler endpoints, alongside an optimized Dockerfile for Google Cloud Run.

---

## 📁 Project Structure

```text
Catalyst_Hackathon_2026/
├── .env.example              # Environment variables template
├── .gitignore                # Git ignore configuration for Python, SQLite, & caches
├── Dockerfile                # Production container specification (Cloud Run ready)
├── GEMINI.md                 # Hackathon guidelines & rules (immutable)
├── pytest.ini                # Pytest configuration & asyncio loop scope
├── README.md                 # Comprehensive platform documentation
├── render.yaml               # Render Infrastructure-as-Code Blueprint (Singapore)
├── requirements.txt          # Production dependencies (including psycopg2-binary)
├── app/
│   ├── __init__.py
│   ├── config.py             # Pydantic Settings & production secret validation
│   ├── database.py           # SQLAlchemy engine, session maker & URL normalizer
│   ├── main.py               # FastAPI application entrypoint & lifespan table creator
│   ├── models/               # SQLAlchemy ORM models
│   │   └── __init__.py       # Users, Profiles, Meds, Logs, Audits, Appointments
│   ├── routers/              # Modular API endpoints & Jinja2 web views
│   │   ├── __init__.py       # Web page routes, /health, /api/health, & cron endpoint
│   │   ├── adherence.py      # Adherence logging, dose confirmation & stats
│   │   ├── appointments.py   # Doctor appointment scheduling & listing
│   │   ├── auth.py           # Senior passcode & caregiver JWT authentication
│   │   ├── medications.py    # Medication catalog & multi-dose schedule CRUD
│   │   └── profile.py        # Shared healthcare profile management
│   ├── schemas/              # Pydantic request & response schemas
│   │   └── __init__.py
│   ├── services/             # Core business logic
│   │   ├── __init__.py
│   │   ├── auth_service.py   # Passcode hashing, lockout tracking & JWT tokens
│   │   ├── notification_service.py # Outbound email & test simulation dispatch
│   │   └── scheduler_service.py    # Timezone-aware dose scheduler & alert engine
│   ├── static/               # Accessible static assets
│   │   ├── css/
│   │   │   └── style.css     # High-contrast, large-touch WCAG 2.1 AA styles
│   │   └── js/
│   │       └── app.js        # Senior passcode keypad & dosage confirmation
│   └── templates/            # Accessible Jinja2 HTML templates
│       ├── base.html         # Base accessible layout
│       ├── caregiver_portal.html  # Caregiver oversight dashboard & audits
│       ├── index.html        # Public portal homepage & role selector
│       ├── login.html        # Dual login interface (Senior PIN / Caregiver)
│       └── senior_dashboard.html  # Senior-friendly high-visibility dashboard
└── tests/                    # Automated test suite (11 test modules, 41 passing tests)
    ├── __init__.py
    ├── conftest.py           # Shared test fixtures & environment isolation
    ├── test_adherence.py     # Adherence tracking & confirmation tests
    ├── test_appointments.py  # Doctor appointment management tests
    ├── test_auth.py          # Authentication, PIN login & caregiver linking
    ├── test_frontend_workflow.py # End-to-end browser & portal workflows
    ├── test_health.py        # System health checks (/health, /api/health) & cron
    ├── test_medications.py   # Medication CRUD & schedule management
    ├── test_notifications.py # Outbound email & notification simulation engine
    ├── test_profile.py       # Shared healthcare profile & permission checks
    ├── test_scheduler_engine.py # Timezones, DST transitions & overdue escalation
    ├── test_security.py      # Rate limiting, PIN lockout & production secrets
    └── test_views.py         # Accessible view rendering & UI response checks
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

## ☁️ Primary Production Deployment: Render (Free Tier)

CareBridge AI is designed for seamless, turnkey deployment on Render using either the Infrastructure-as-Code Blueprint (`render.yaml`) or manual configuration:

### Option A: Turnkey Blueprint Deployment (Recommended)
1. Fork or push this repository to your GitHub account.
2. In the Render Dashboard, create a new **Blueprint Instance**.
3. Select this repository; Render will automatically detect and apply `render.yaml`.
4. Render provisions both the managed PostgreSQL database (`carebridge-db`) and the Web Service in the **Singapore** region, automatically wiring `DATABASE_URL` via private networking.
5. Click **Apply** to deploy.

### Option B: Manual Web Service Setup
- **Environment:** `Python`
- **Region:** `Singapore` (matches `render.yaml`)
- **Branch:** `main`
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Health Check Path:** `/api/health`

### Required Environment Variables:
| Variable | Value / Description |
|---|---|
| `ENVIRONMENT` | `production` |
| `APP_SECRET_KEY` (or `JWT_SECRET`) | Strong random secret key (minimum 32 characters) |
| `DATABASE_URL` | Render PostgreSQL connection string (`postgresql://...`) or `sqlite:///./carebridge.db` (ephemeral demo) |
| `CRON_API_KEY` | Secret token for securing `/api/cron/check-reminders` |
| `SMTP_ENABLED` | `false` (uses built-in audit & simulation mode on Render Free) |

> [!NOTE]
> **Render Free Considerations & Safe Notification Demonstration:**
> 1. **Database Persistence & Free-Plan Retention:** Free web service disks are ephemeral. Connecting a managed PostgreSQL database via `DATABASE_URL` ensures all patient profiles, medications, doses, and audits persist across restarts and redeployments. Note that Render's Free PostgreSQL plan includes a 30-day retention limit; for long-term production, upgrade the database or link an external managed PostgreSQL instance (e.g., Neon, Supabase, Cloud SQL).
> 2. **SMTP Port Block:** Render Free blocks outbound SMTP traffic on ports 25, 465, and 587. CareBridge AI provides a built-in **Simulation Mode** (`SMTP_ENABLED=false` by default) which safely evaluates schedules, dispatches reminders, logs them to the console, and records complete delivery audits in the database visible on the caregiver portal.

---

## 🐳 Alternative Deployment: Docker & Google Cloud Run

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
