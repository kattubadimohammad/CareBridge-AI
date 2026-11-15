from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app, follow_redirects=False)


def test_unauthenticated_dashboard_redirects():
    """Verify unauthenticated requests to senior and caregiver dashboards redirect to login."""
    r_senior = client.get("/senior")
    assert r_senior.status_code == 302
    assert "/login" in r_senior.headers["location"]

    r_cg = client.get("/caregiver")
    assert r_cg.status_code == 302
    assert "/login" in r_cg.headers["location"]


def test_senior_end_to_end_dashboard_and_dose_confirmation():
    """Complete workflow: Senior registers, logs in, loads real doses, confirms dose, and checks update."""
    # 1. Register Senior
    reg_s = client.post(
        "/api/auth/register-senior",
        json={
            "full_name": "Harold Finch",
            "passcode": "8899",
            "emergency_contact_name": "John Reese",
            "emergency_contact_phone": "555-0199",
        },
    )
    senior_id = reg_s.json()["id"]

    # 2. Login as Senior (sets HttpOnly cookie)
    login_res = client.post(
        "/api/auth/login-passcode",
        json={"user_id": senior_id, "passcode": "8899"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    assert "access_token" in login_res.cookies

    # 3. Add a real medication for this senior
    med_res = client.post(
        "/api/medications",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "CoQ10",
            "dosage": "100 mg",
            "instructions": "Take with breakfast",
            "purpose": "Cardiovascular support",
            "schedules": [{"scheduled_time": "08:00", "days_of_week": "everyday"}],
        },
    )
    assert med_res.status_code == 201

    # 4. Access senior dashboard using cookie session
    client.cookies.set("access_token", token)
    dashboard_res = client.get("/senior")
    assert dashboard_res.status_code == 200
    assert "Hello, Harold Finch!" in dashboard_res.text
    assert "CoQ10" in dashboard_res.text
    assert "555-0199" in dashboard_res.text
    assert "I TOOK THIS" in dashboard_res.text

    # 5. Fetch generated dose log ID
    doses_res = client.get(
        f"/api/adherence/senior/{senior_id}/today",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert doses_res.status_code == 200
    doses = doses_res.json()
    assert len(doses) == 1
    dose_id = doses[0]["id"]
    assert doses[0]["status"] == "pending"

    # 6. Senior confirms dose via API
    confirm_res = client.post(
        f"/api/adherence/logs/{dose_id}/confirm",
        headers={"Authorization": f"Bearer {token}"},
        json={"action": "taken", "notes": "Confirmed by Harold"},
    )
    assert confirm_res.status_code == 200
    assert confirm_res.json()["status"] == "taken"

    # 7. Reload dashboard and verify TAKEN status is displayed
    reloaded_dash = client.get("/senior")
    assert reloaded_dash.status_code == 200
    assert "TAKEN" in reloaded_dash.text


def test_caregiver_end_to_end_portal_workflow():
    """Complete workflow: Caregiver registers, links to senior, manages medications, appointments, and profile."""
    # 1. Create Senior
    reg_s = client.post(
        "/api/auth/register-senior",
        json={"full_name": "Beatrice Potter", "passcode": "5566"},
    )
    senior_id = reg_s.json()["id"]

    # 2. Create Caregiver
    reg_cg = client.post(
        "/api/auth/register",
        json={
            "full_name": "Nurse Kelly",
            "role": "caregiver",
            "email": "nurse.kelly@hospital.org",
            "password": "StrongPassword123!",
        },
    )
    cg_id = reg_cg.json()["id"]

    # 3. Login as Caregiver
    cg_login = client.post(
        "/api/auth/login",
        json={"email": "nurse.kelly@hospital.org", "password": "StrongPassword123!"},
    )
    assert cg_login.status_code == 200
    cg_token = cg_login.json()["access_token"]

    # 4. Link Caregiver to Senior (Caregiver requests link -> Status is PENDING)
    link_res = client.post(
        "/api/auth/link-caregiver",
        headers={"Authorization": f"Bearer {cg_token}"},
        json={
            "senior_id": senior_id,
            "caregiver_id": cg_id,
            "relationship_type": "nurse",
            "can_view_profile": True,
            "can_edit_profile": True,
            "can_manage_medications": True,
            "can_manage_appointments": True,
            "can_log_adherence": True,
        },
    )
    assert link_res.status_code == 201
    link_data = link_res.json()
    assert link_data["status"] == "pending"
    assert link_data["is_active"] is False

    # Senior approves the caregiver's access request (Patient Consent)
    s_login = client.post(
        "/api/auth/login-passcode",
        json={"user_id": senior_id, "passcode": "5566"},
    )
    senior_token = s_login.json()["access_token"]
    appr_res = client.post(
        f"/api/auth/approve-caregiver/{link_data['id']}",
        headers={"Authorization": f"Bearer {senior_token}"},
    )
    assert appr_res.status_code == 200
    assert appr_res.json()["status"] == "approved"
    assert appr_res.json()["is_active"] is True

    # 5. Caregiver views portal
    client.cookies.set("access_token", cg_token)
    portal_res = client.get("/caregiver")
    assert portal_res.status_code == 200
    assert "Nurse Kelly" in portal_res.text
    assert "Beatrice Potter" in portal_res.text

    # 6. Caregiver adds medication for senior
    add_med = client.post(
        f"/api/medications?senior_id={senior_id}",
        headers={"Authorization": f"Bearer {cg_token}"},
        json={
            "name": "Levothyroxine",
            "dosage": "50 mcg",
            "instructions": "Take 30 mins before breakfast",
            "purpose": "Thyroid hormone replacement",
            "schedules": [{"scheduled_time": "07:00", "days_of_week": "everyday"}],
        },
    )
    assert add_med.status_code == 201

    # 7. Caregiver schedules doctor appointment
    appt_dt = (datetime.utcnow() + timedelta(days=7)).isoformat()
    add_appt = client.post(
        "/api/appointments",
        headers={"Authorization": f"Bearer {cg_token}"},
        json={
            "senior_id": senior_id,
            "doctor_name": "Dr. Watson",
            "specialty": "Endocrinology",
            "appointment_datetime": appt_dt,
            "clinic_name": "Baker Clinic",
            "preparation_instructions": "Fasting blood panel required",
        },
    )
    assert add_appt.status_code == 201

    # 8. Reload caregiver portal and verify new medication and appointment appear
    client.cookies.set("access_token", cg_token)
    reloaded_portal = client.get(f"/caregiver?senior_id={senior_id}")
    assert reloaded_portal.status_code == 200
    assert "Levothyroxine" in reloaded_portal.text
    assert "Dr. Watson" in reloaded_portal.text
    assert "Fasting blood panel required" in reloaded_portal.text


def test_senior_redirected_from_caregiver_portal():
    """Verify seniors navigating to /caregiver are automatically redirected to /senior."""
    reg_s = client.post(
        "/api/auth/register-senior",
        json={"full_name": "Walter White", "passcode": "1122"},
    )
    senior_id = reg_s.json()["id"]
    login_s = client.post(
        "/api/auth/login-passcode",
        json={"user_id": senior_id, "passcode": "1122"},
    )
    token = login_s.json()["access_token"]

    client.cookies.set("access_token", token)
    cg_redirect = client.get("/caregiver")
    assert cg_redirect.status_code == 302
    assert "/senior" in cg_redirect.headers["location"]
