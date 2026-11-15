from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_accessible_views_rendering():
    """Verify all responsive and accessible HTML web views render HTTP 200 with appropriate semantics."""
    # 1. Homepage
    r_home = client.get("/")
    assert r_home.status_code == 200
    assert "CareBridge AI" in r_home.text
    assert "👴 Senior Mode" in r_home.text
    assert "👩‍⚕️ Caregiver Portal" in r_home.text

    # 2. Accessible Login View
    r_login = client.get("/login")
    assert r_login.status_code == 200
    assert "Senior PIN Login" in r_login.text
    assert "Numeric Passcode Keypad" in r_login.text
    assert "Caregiver / Family" in r_login.text

    # 3. Senior Quick View (authenticated session)
    reg_s = client.post(
        "/api/auth/register-senior",
        json={"full_name": "Arthur Davies", "passcode": "1234", "emergency_contact_phone": "911"},
    )
    senior_id = reg_s.json()["id"]
    client.post("/api/auth/login-passcode", json={"user_id": senior_id, "passcode": "1234"})

    r_senior = client.get("/senior")
    assert r_senior.status_code == 200
    assert "SENIOR EASY VIEW" in r_senior.text
    assert "CALL" in r_senior.text
    assert "Medication Schedule" in r_senior.text

    # 4. Caregiver Oversight Portal (authenticated caregiver session)
    reg_cg = client.post(
        "/api/auth/register",
        json={"full_name": "Sarah Davies", "role": "caregiver", "email": "sarah.view@example.com", "password": "Password123!"},
    )
    cg_id = reg_cg.json()["id"]

    # Link caregiver to senior
    client.post(
        "/api/auth/link-caregiver",
        json={"senior_id": senior_id, "caregiver_id": cg_id, "relationship_type": "daughter"},
    )

    client.post("/api/auth/login", json={"email": "sarah.view@example.com", "password": "Password123!"})

    r_cg = client.get("/caregiver")
    assert r_cg.status_code == 200
    assert "CAREGIVER & FAMILY OVERSIGHT" in r_cg.text
    assert "Adherence Rate" in r_cg.text
