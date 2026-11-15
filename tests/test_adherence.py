import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_adherence_tracking_and_audit():
    """Verify dose generation, audit tracking of who confirmed, duplicate avoidance, and stats."""
    # 1. Create Senior
    s_res = client.post(
        "/api/auth/register-senior",
        json={"full_name": "Harold Wilson", "passcode": "9911"},
    )
    senior_id = s_res.json()["id"]
    s_token = client.post(
        "/api/auth/login-passcode",
        json={"user_id": senior_id, "passcode": "9911"},
    ).json()["access_token"]

    # 2. Add Medication
    client.post(
        "/api/medications",
        headers={"Authorization": f"Bearer {s_token}"},
        json={
            "name": "Amlodipine",
            "dosage": "5 mg",
            "instructions": "Take once daily in morning",
            "schedules": [
                {"scheduled_time": "09:00", "days_of_week": "everyday"},
            ],
        },
    )

    # 3. Retrieve today's doses (generates pending dose)
    doses_res = client.get(
        f"/api/adherence/senior/{senior_id}/today",
        headers={"Authorization": f"Bearer {s_token}"},
    )
    assert doses_res.status_code == 200
    doses = doses_res.json()
    assert len(doses) == 1
    log_id = doses[0]["id"]
    assert doses[0]["status"] == "pending"

    # 4. DUPLICATE AVOIDANCE: calling today doses again must not create duplicates
    doses_repeat = client.get(
        f"/api/adherence/senior/{senior_id}/today",
        headers={"Authorization": f"Bearer {s_token}"},
    )
    assert doses_repeat.status_code == 200
    assert len(doses_repeat.json()) == 1
    assert doses_repeat.json()[0]["id"] == log_id

    # 5. Create Caregiver and Link
    cg_res = client.post(
        "/api/auth/register",
        json={
            "full_name": "Nurse Emily",
            "role": "caregiver",
            "email": "emily@nurse.org",
            "password": "Password123!",
        },
    )
    cg_id = cg_res.json()["id"]
    cg_token = client.post(
        "/api/auth/login",
        json={"email": "emily@nurse.org", "password": "Password123!"},
    ).json()["access_token"]

    client.post(
        "/api/auth/link-caregiver",
        headers={"Authorization": f"Bearer {s_token}"},
        json={
            "senior_id": senior_id,
            "caregiver_id": cg_id,
            "can_log_adherence": True,
        },
    )

    # 6. Caregiver confirms dose on behalf of senior
    confirm_res = client.post(
        f"/api/adherence/logs/{log_id}/confirm",
        headers={"Authorization": f"Bearer {cg_token}"},
        json={"action": "taken", "notes": "Observed by Nurse Emily with morning tea."},
    )
    assert confirm_res.status_code == 200
    confirmed_data = confirm_res.json()
    assert confirmed_data["status"] == "taken"
    assert confirmed_data["confirmed_by_user_id"] == cg_id
    assert "Emily" in confirmed_data["confirmed_by_name"]
    assert confirmed_data["taken_at"] is not None

    # 7. Check stats
    stats_res = client.get(
        f"/api/adherence/senior/{senior_id}/stats",
        headers={"Authorization": f"Bearer {cg_token}"},
    )
    assert stats_res.status_code == 200
    stats = stats_res.json()
    assert stats["taken_count"] == 1
    assert stats["adherence_rate_percent"] == 100.0
