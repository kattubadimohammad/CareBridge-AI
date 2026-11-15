import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine

client = TestClient(app)


def test_senior_registration_and_passcode_login():
    """Test senior registration with numeric passcode and login."""
    # 1. Register Senior
    reg_res = client.post(
        "/api/auth/register-senior",
        json={
            "full_name": "Arthur Davies",
            "passcode": "1234",
            "phone": "555-0101",
            "emergency_contact_name": "Sarah Davies",
            "emergency_contact_phone": "555-0144",
        },
    )
    assert reg_res.status_code == 201
    senior_data = reg_res.json()
    senior_id = senior_data["id"]
    assert senior_data["role"] == "senior"

    # 2. Login with valid passcode
    login_res = client.post(
        "/api/auth/login-passcode",
        json={"user_id": senior_id, "passcode": "1234"},
    )
    assert login_res.status_code == 200
    token_data = login_res.json()
    assert "access_token" in token_data
    assert token_data["role"] == "senior"

    # 3. Login with invalid passcode -> 401
    bad_login = client.post(
        "/api/auth/login-passcode",
        json={"user_id": senior_id, "passcode": "9999"},
    )
    assert bad_login.status_code == 401

    # 4. Reject non-numeric passcode during registration
    bad_reg = client.post(
        "/api/auth/register-senior",
        json={"full_name": "Invalid Senior", "passcode": "abcd"},
    )
    assert bad_reg.status_code == 400


def test_caregiver_registration_and_login():
    """Test caregiver registration with email and password."""
    reg_res = client.post(
        "/api/auth/register",
        json={
            "full_name": "Sarah Davies",
            "role": "caregiver",
            "email": "sarah.caregiver@example.com",
            "password": "SecurePassword123!",
            "phone": "555-0144",
        },
    )
    assert reg_res.status_code == 201
    cg_data = reg_res.json()
    assert cg_data["role"] == "caregiver"

    # Login
    login_res = client.post(
        "/api/auth/login",
        json={
            "email": "sarah.caregiver@example.com",
            "password": "SecurePassword123!",
        },
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]

    # Access /me
    me_res = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_res.status_code == 200
    assert me_res.json()["email"] == "sarah.caregiver@example.com"


def test_caregiver_linking():
    """Test linking a caregiver to a senior with permissions."""
    # Create senior
    s_res = client.post(
        "/api/auth/register-senior",
        json={"full_name": "John Senior", "passcode": "4321"},
    )
    senior_id = s_res.json()["id"]

    # Login as senior to get token
    s_token = client.post(
        "/api/auth/login-passcode",
        json={"user_id": senior_id, "passcode": "4321"},
    ).json()["access_token"]

    # Create caregiver
    cg_res = client.post(
        "/api/auth/register",
        json={
            "full_name": "Nurse Jane",
            "role": "caregiver",
            "email": "nurse.jane@example.com",
            "password": "NursePassword123",
        },
    )
    cg_id = cg_res.json()["id"]

    # Link caregiver to senior
    link_res = client.post(
        "/api/auth/link-caregiver",
        headers={"Authorization": f"Bearer {s_token}"},
        json={
            "senior_id": senior_id,
            "caregiver_id": cg_id,
            "relationship_type": "nurse",
            "can_view_profile": True,
            "can_edit_profile": True,
            "can_manage_medications": True,
            "can_log_adherence": True,
            "can_manage_appointments": True,
        },
    )
    assert link_res.status_code == 201
    link_data = link_res.json()
    assert link_data["senior_id"] == senior_id
    assert link_data["caregiver_id"] == cg_id
    assert link_data["relationship_type"] == "nurse"
