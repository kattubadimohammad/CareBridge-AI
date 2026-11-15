import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_medication_crud_and_schedules():
    """Verify adding, updating, viewing, and deactivating medications with timezone schedules."""
    # Create Senior
    s_res = client.post(
        "/api/auth/register-senior",
        json={"full_name": "Margaret Smith", "passcode": "7788"},
    )
    senior_id = s_res.json()["id"]
    s_token = client.post(
        "/api/auth/login-passcode",
        json={"user_id": senior_id, "passcode": "7788"},
    ).json()["access_token"]

    # Add Medication with 2 schedules
    med_res = client.post(
        "/api/medications",
        headers={"Authorization": f"Bearer {s_token}"},
        json={
            "name": "Metformin",
            "dosage": "500 mg",
            "instructions": "Take after meals",
            "purpose": "Type 2 Diabetes regulation",
            "prescribed_by": "Dr. Davis",
            "schedules": [
                {"scheduled_time": "08:00", "days_of_week": "everyday", "timezone": "America/New_York"},
                {"scheduled_time": "18:00", "days_of_week": "everyday", "timezone": "America/New_York"},
            ],
        },
    )
    assert med_res.status_code == 201
    med_data = med_res.json()
    med_id = med_data["id"]
    assert med_data["name"] == "Metformin"
    assert len(med_data["schedules"]) == 2
    assert med_data["schedules"][0]["timezone"] == "America/New_York"

    # View Medication list
    list_res = client.get(
        f"/api/medications/senior/{senior_id}",
        headers={"Authorization": f"Bearer {s_token}"},
    )
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1

    # Edit Medication
    edit_res = client.put(
        f"/api/medications/{med_id}",
        headers={"Authorization": f"Bearer {s_token}"},
        json={"dosage": "850 mg", "instructions": "Take with dinner"},
    )
    assert edit_res.status_code == 200
    assert edit_res.json()["dosage"] == "850 mg"

    # Deactivate Medication
    deactivate_res = client.post(
        f"/api/medications/{med_id}/deactivate",
        headers={"Authorization": f"Bearer {s_token}"},
    )
    assert deactivate_res.status_code == 200
    assert deactivate_res.json()["is_active"] is False
