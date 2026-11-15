from datetime import datetime, timedelta
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_doctor_appointments():
    """Verify appointment creation, listing, upcoming filtering, and cancellation."""
    # 1. Create Senior
    s_res = client.post(
        "/api/auth/register-senior",
        json={"full_name": "Thomas Brown", "passcode": "3344"},
    )
    senior_id = s_res.json()["id"]
    s_token = client.post(
        "/api/auth/login-passcode",
        json={"user_id": senior_id, "passcode": "3344"},
    ).json()["access_token"]

    # 2. Schedule Appointment
    appt_time = (datetime.utcnow() + timedelta(days=5)).isoformat()
    create_res = client.post(
        "/api/appointments",
        headers={"Authorization": f"Bearer {s_token}"},
        json={
            "senior_id": senior_id,
            "doctor_name": "Dr. Sarah Jenkins",
            "specialty": "Ophthalmology",
            "clinic_name": "Vision Care Associates",
            "clinic_address": "742 Evergreen Terrace",
            "contact_phone": "555-0188",
            "appointment_datetime": appt_time,
            "purpose": "Annual glaucoma and vision screening",
            "preparation_instructions": "Bring existing reading glasses",
        },
    )
    assert create_res.status_code == 201
    appt_data = create_res.json()
    appt_id = appt_data["id"]
    assert appt_data["doctor_name"] == "Dr. Sarah Jenkins"
    assert appt_data["status"] == "scheduled"

    # 3. List senior appointments
    list_res = client.get(
        f"/api/appointments/senior/{senior_id}",
        headers={"Authorization": f"Bearer {s_token}"},
    )
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1

    # 4. List upcoming appointments
    upcoming_res = client.get(
        f"/api/appointments/senior/{senior_id}/upcoming",
        headers={"Authorization": f"Bearer {s_token}"},
    )
    assert upcoming_res.status_code == 200
    assert len(upcoming_res.json()) >= 1

    # 5. Cancel appointment
    cancel_res = client.post(
        f"/api/appointments/{appt_id}/cancel",
        headers={"Authorization": f"Bearer {s_token}"},
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "cancelled"
