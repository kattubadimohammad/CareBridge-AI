import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_shared_healthcare_profile_permissions():
    """Verify shared healthcare profile viewing and editing with RBAC."""
    # 1. Create Senior
    s_res = client.post(
        "/api/auth/register-senior",
        json={"full_name": "Eleanor Vance", "passcode": "5678"},
    )
    senior_id = s_res.json()["id"]
    s_token = client.post(
        "/api/auth/login-passcode",
        json={"user_id": senior_id, "passcode": "5678"},
    ).json()["access_token"]

    # 2. Update senior profile by senior
    update_res = client.put(
        "/api/profile/me",
        headers={"Authorization": f"Bearer {s_token}"},
        json={
            "blood_group": "A+",
            "known_allergies": "Penicillin",
            "chronic_conditions": "Hypertension",
            "mobility_notes": "Uses cane",
            "primary_physician_name": "Dr. Anderson",
            "emergency_contact_name": "David Vance",
            "emergency_contact_phone": "555-0199",
        },
    )
    assert update_res.status_code == 200
    assert update_res.json()["blood_group"] == "A+"
    assert update_res.json()["known_allergies"] == "Penicillin"

    # 3. Create Caregiver A (with view permission only)
    cg_res = client.post(
        "/api/auth/register",
        json={
            "full_name": "Caregiver Alice",
            "role": "caregiver",
            "email": "alice@caregiver.org",
            "password": "Password123!",
        },
    )
    cg_id = cg_res.json()["id"]
    cg_token = client.post(
        "/api/auth/login",
        json={"email": "alice@caregiver.org", "password": "Password123!"},
    ).json()["access_token"]

    # Link Caregiver A with can_view_profile=True, can_edit_profile=False
    client.post(
        "/api/auth/link-caregiver",
        headers={"Authorization": f"Bearer {s_token}"},
        json={
            "senior_id": senior_id,
            "caregiver_id": cg_id,
            "relationship_type": "caregiver",
            "can_view_profile": True,
            "can_edit_profile": False,
        },
    )

    # Caregiver A can view
    view_res = client.get(
        f"/api/profile/{senior_id}",
        headers={"Authorization": f"Bearer {cg_token}"},
    )
    assert view_res.status_code == 200
    assert view_res.json()["blood_group"] == "A+"

    # Caregiver A CANNOT edit (403 Forbidden)
    forbidden_edit = client.put(
        f"/api/profile/{senior_id}",
        headers={"Authorization": f"Bearer {cg_token}"},
        json={"blood_group": "B+"},
    )
    assert forbidden_edit.status_code == 403

    # 4. Unlinked user cannot view (403 Forbidden)
    unlinked_res = client.post(
        "/api/auth/register",
        json={
            "full_name": "Stranger Bob",
            "role": "caregiver",
            "email": "bob@random.com",
            "password": "Password123!",
        },
    )
    stranger_token = client.post(
        "/api/auth/login",
        json={"email": "bob@random.com", "password": "Password123!"},
    ).json()["access_token"]

    stranger_view = client.get(
        f"/api/profile/{senior_id}",
        headers={"Authorization": f"Bearer {stranger_token}"},
    )
    assert stranger_view.status_code == 403
