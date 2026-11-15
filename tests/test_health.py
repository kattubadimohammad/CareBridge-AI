from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_check():
    """Verify system health endpoint returns 200 OK and healthy status on both /api/health and /health."""
    for path in ["/api/health", "/health"]:
        response = client.get(path)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "CareBridge" in data["app_name"]


def test_homepage_render():
    """Verify root HTML route renders successfully."""
    response = client.get("/")
    assert response.status_code == 200
    assert "CareBridge AI" in response.text
    assert "text/html" in response.headers["content-type"]


def test_cron_endpoint_dev():
    """Verify cron evaluation endpoint responds successfully in development."""
    response = client.post("/api/cron/check-reminders")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"


def test_static_css_and_js_paths():
    """Verify static assets (CSS and JS) are properly mounted and served."""
    css_res = client.get("/static/css/style.css")
    assert css_res.status_code == 200
    assert "CareBridge AI" in css_res.text

    js_res = client.get("/static/js/app.js")
    assert js_res.status_code == 200
    assert "CareBridge" in js_res.text


def test_cron_auth_production_rejection(monkeypatch):
    """Verify cron endpoint rejects requests in production without valid token."""
    from app.config import settings

    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "cron_api_key", "super-secret-token")

    # Missing token -> 401
    res_missing = client.post("/api/cron/check-reminders")
    assert res_missing.status_code == 401
    assert "Invalid or missing" in res_missing.json()["detail"]

    # Wrong token -> 401
    res_wrong = client.post(
        "/api/cron/check-reminders",
        headers={"X-Scheduler-Token": "wrong-token"},
    )
    assert res_wrong.status_code == 401

    # Valid token -> 200
    res_valid = client.post(
        "/api/cron/check-reminders",
        headers={"X-Scheduler-Token": "super-secret-token"},
    )
    assert res_valid.status_code == 200
    assert res_valid.json()["status"] == "success"


def test_database_session_isolation():
    """Verify get_db provides an active session and rollback/close works properly."""
    from app.database import get_db, SessionLocal
    from sqlalchemy.sql import text

    gen = get_db()
    db = next(gen)
    assert db.is_active
    result = db.execute(text("SELECT 1")).scalar()
    assert result == 1
    # Cleanup generator
    try:
        next(gen)
    except StopIteration:
        pass


def test_database_url_normalization_and_driver_selection():
    """Verify database URLs are normalized to postgresql+psycopg2:// for SQLAlchemy 2.0."""
    from app.database import normalize_database_url

    # 1. Render default URL with postgres://
    render_postgres_url = "postgres://carebridge_user:secret_pass@dpg-abc123-a.singapore-postgres.render.com/carebridge"
    normalized_1 = normalize_database_url(render_postgres_url)
    assert normalized_1 == "postgresql+psycopg2://carebridge_user:secret_pass@dpg-abc123-a.singapore-postgres.render.com/carebridge"

    # 2. Render standard URL with postgresql://
    render_postgresql_url = "postgresql://carebridge_user:secret_pass@dpg-abc123-a.singapore-postgres.render.com/carebridge"
    normalized_2 = normalize_database_url(render_postgresql_url)
    assert normalized_2 == "postgresql+psycopg2://carebridge_user:secret_pass@dpg-abc123-a.singapore-postgres.render.com/carebridge"

    # 3. Already explicit postgresql+psycopg2://
    explicit_url = "postgresql+psycopg2://carebridge_user:secret_pass@dpg-abc123-a.singapore-postgres.render.com/carebridge"
    normalized_3 = normalize_database_url(explicit_url)
    assert normalized_3 == explicit_url

    # 4. Local SQLite URL
    sqlite_url = "sqlite:///./carebridge.db"
    normalized_4 = normalize_database_url(sqlite_url)
    assert normalized_4 == "sqlite:///./carebridge.db"
