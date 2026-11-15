from datetime import timedelta
import pytest
from jose import jwt
from fastapi.testclient import TestClient

from app.main import app
from app.config import Settings, settings
from app.services.auth_service import AuthService, ALGORITHM

client = TestClient(app)


def test_senior_pin_brute_force_lockout_and_generic_messaging():
    """Verify PIN lockout after 5 consecutive failed attempts and generic error messaging."""
    # Register senior
    reg = client.post(
        "/api/auth/register-senior",
        json={"full_name": "Marcus Aurelius", "passcode": "2468"},
    )
    assert reg.status_code == 201
    senior_id = reg.json()["id"]

    # 1-4. Four failed attempts should return 401 with generic error
    for i in range(4):
        res = client.post(
            "/api/auth/login-passcode",
            json={"user_id": senior_id, "passcode": "0000"},
        )
        assert res.status_code == 401
        assert res.json()["detail"] == "Invalid Patient ID or Passcode."

    # 5. Fifth failed attempt triggers account lockout (HTTP 429)
    res_5 = client.post(
        "/api/auth/login-passcode",
        json={"user_id": senior_id, "passcode": "0000"},
    )
    assert res_5.status_code == 429
    assert "Account locked due to exceeding 5 failed passcode attempts" in res_5.json()["detail"]

    # 6. Subsequent attempt with the CORRECT PIN while locked out is still rejected (HTTP 429)
    res_locked = client.post(
        "/api/auth/login-passcode",
        json={"user_id": senior_id, "passcode": "2468"},
    )
    assert res_locked.status_code == 429
    assert "Account temporarily locked" in res_locked.json()["detail"]

    # 7. Non-existent user ID returns identical generic error (prevents enumeration)
    res_nonexistent = client.post(
        "/api/auth/login-passcode",
        json={"user_id": 999999, "passcode": "1234"},
    )
    assert res_nonexistent.status_code == 401
    assert res_nonexistent.json()["detail"] == "Invalid Patient ID or Passcode."


def test_caregiver_consent_pending_blocks_access():
    """Verify that a caregiver's self-link request is placed in pending status and cannot access records."""
    # 1. Register Senior
    senior_res = client.post(
        "/api/auth/register-senior",
        json={"full_name": "Alice Cooper", "passcode": "1122"},
    )
    senior_id = senior_res.json()["id"]

    # 2. Register Caregiver
    cg_res = client.post(
        "/api/auth/register",
        json={
            "full_name": "Bob Martin",
            "role": "caregiver",
            "email": "bob.martin@care.org",
            "password": "Password123!",
        },
    )
    cg_id = cg_res.json()["id"]

    # 3. Caregiver logs in
    cg_login = client.post(
        "/api/auth/login",
        json={"email": "bob.martin@care.org", "password": "Password123!"},
    )
    cg_token = cg_login.json()["access_token"]
    cg_headers = {"Authorization": f"Bearer {cg_token}"}

    # 4. Caregiver self-initiates link request to senior
    link_res = client.post(
        "/api/auth/link-caregiver",
        headers=cg_headers,
        json={
            "senior_id": senior_id,
            "caregiver_id": cg_id,
            "relationship_type": "caregiver",
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

    # 5. Pending caregiver attempts to access healthcare profile -> 403 Forbidden
    profile_res = client.get(f"/api/profile/{senior_id}", headers=cg_headers)
    assert profile_res.status_code == 403
    assert "pending approval" in profile_res.json()["detail"]

    # 6. Pending caregiver attempts to access medications -> 403 Forbidden
    meds_res = client.get(f"/api/medications/senior/{senior_id}", headers=cg_headers)
    assert meds_res.status_code == 403

    # 7. Pending caregiver attempts to access appointments -> 403 Forbidden
    appts_res = client.get(f"/api/appointments/senior/{senior_id}", headers=cg_headers)
    assert appts_res.status_code == 403

    # 8. Pending caregiver attempts to access adherence -> 403 Forbidden
    adhere_res = client.get(f"/api/adherence/senior/{senior_id}/today", headers=cg_headers)
    assert adhere_res.status_code == 403


def test_caregiver_approval_and_authorization_workflow():
    """Verify senior approval grants access and unauthorized users cannot approve."""
    # 1. Register Senior Alice
    s_res = client.post(
        "/api/auth/register-senior",
        json={"full_name": "Alice Springs", "passcode": "3344"},
    )
    alice_id = s_res.json()["id"]

    # 2. Register Senior Eve (unauthorized bystander)
    eve_res = client.post(
        "/api/auth/register-senior",
        json={"full_name": "Eve Bystander", "passcode": "9999"},
    )
    eve_id = eve_res.json()["id"]
    eve_token = client.post(
        "/api/auth/login-passcode",
        json={"user_id": eve_id, "passcode": "9999"},
    ).json()["access_token"]

    # 3. Register Caregiver Bob
    cg_res = client.post(
        "/api/auth/register",
        json={
            "full_name": "Bob Helper",
            "role": "caregiver",
            "email": "bob.helper@care.org",
            "password": "Password123!",
        },
    )
    bob_id = cg_res.json()["id"]
    bob_token = client.post(
        "/api/auth/login",
        json={"email": "bob.helper@care.org", "password": "Password123!"},
    ).json()["access_token"]

    # 4. Bob requests link to Alice
    link_res = client.post(
        "/api/auth/link-caregiver",
        headers={"Authorization": f"Bearer {bob_token}"},
        json={
            "senior_id": alice_id,
            "caregiver_id": bob_id,
            "relationship_type": "caregiver",
            "can_view_profile": True,
            "can_manage_medications": True,
        },
    )
    link_id = link_res.json()["id"]
    assert link_res.json()["status"] == "pending"

    # 5. Unauthorized user Eve tries to approve Bob's link -> 403 Forbidden
    eve_appr = client.post(
        f"/api/auth/approve-caregiver/{link_id}",
        headers={"Authorization": f"Bearer {eve_token}"},
    )
    assert eve_appr.status_code == 403
    assert "Only the patient or system administrator" in eve_appr.json()["detail"]

    # 6. Alice (the patient) approves Bob's link
    alice_token = client.post(
        "/api/auth/login-passcode",
        json={"user_id": alice_id, "passcode": "3344"},
    ).json()["access_token"]

    alice_appr = client.post(
        f"/api/auth/approve-caregiver/{link_id}",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert alice_appr.status_code == 200
    assert alice_appr.json()["status"] == "approved"
    assert alice_appr.json()["is_active"] is True

    # 7. Bob now has access to Alice's profile and medications
    profile_check = client.get(
        f"/api/profile/{alice_id}",
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert profile_check.status_code == 200

    meds_check = client.get(
        f"/api/medications/senior/{alice_id}",
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert meds_check.status_code == 200


def test_caregiver_rejection_workflow():
    """Verify senior can reject a caregiver link request."""
    # 1. Register Senior & Caregiver
    s_res = client.post("/api/auth/register-senior", json={"full_name": "Charlie Chaplin", "passcode": "5678"})
    charlie_id = s_res.json()["id"]
    charlie_token = client.post("/api/auth/login-passcode", json={"user_id": charlie_id, "passcode": "5678"}).json()["access_token"]

    cg_res = client.post(
        "/api/auth/register",
        json={"full_name": "Unknown Caregiver", "role": "caregiver", "email": "unknown@care.org", "password": "Password123!"},
    )
    cg_id = cg_res.json()["id"]
    cg_token = client.post("/api/auth/login", json={"email": "unknown@care.org", "password": "Password123!"}).json()["access_token"]

    # 2. Caregiver requests link
    link_res = client.post(
        "/api/auth/link-caregiver",
        headers={"Authorization": f"Bearer {cg_token}"},
        json={"senior_id": charlie_id, "caregiver_id": cg_id, "relationship_type": "caregiver"},
    )
    link_id = link_res.json()["id"]

    # 3. Senior rejects request
    rej_res = client.post(
        f"/api/auth/reject-caregiver/{link_id}",
        headers={"Authorization": f"Bearer {charlie_token}"},
    )
    assert rej_res.status_code == 200
    assert rej_res.json()["status"] == "rejected"
    assert rej_res.json()["is_active"] is False

    # 4. Caregiver access is blocked
    check_res = client.get(f"/api/profile/{charlie_id}", headers={"Authorization": f"Bearer {cg_token}"})
    assert check_res.status_code == 403


def test_caregiver_access_revocation_by_senior():
    """Verify senior can revoke previously approved caregiver access with immediate effect."""
    # 1. Register Senior & Caregiver
    s_res = client.post("/api/auth/register-senior", json={"full_name": "Eleanor Vance", "passcode": "7788"})
    senior_id = s_res.json()["id"]
    senior_token = client.post("/api/auth/login-passcode", json={"user_id": senior_id, "passcode": "7788"}).json()["access_token"]

    cg_res = client.post(
        "/api/auth/register",
        json={"full_name": "Theodora Crain", "role": "caregiver", "email": "theo.crain@care.org", "password": "Password123!"},
    )
    cg_id = cg_res.json()["id"]
    cg_token = client.post("/api/auth/login", json={"email": "theo.crain@care.org", "password": "Password123!"}).json()["access_token"]

    # 2. Senior directly links Caregiver (direct consent -> approved)
    link_res = client.post(
        "/api/auth/link-caregiver",
        headers={"Authorization": f"Bearer {senior_token}"},
        json={
            "senior_id": senior_id,
            "caregiver_id": cg_id,
            "relationship_type": "caregiver",
            "can_view_profile": True,
            "can_manage_medications": True,
        },
    )
    assert link_res.status_code == 201
    assert link_res.json()["status"] == "approved"
    link_id = link_res.json()["id"]

    # 3. Verify Caregiver can access profile
    assert client.get(f"/api/profile/{senior_id}", headers={"Authorization": f"Bearer {cg_token}"}).status_code == 200

    # 4. Senior revokes access
    revoke_res = client.post(
        f"/api/auth/revoke-caregiver/{link_id}",
        headers={"Authorization": f"Bearer {senior_token}"},
    )
    assert revoke_res.status_code == 200
    assert revoke_res.json()["status"] == "revoked"
    assert revoke_res.json()["is_active"] is False

    # 5. Subsequent access attempt is immediately rejected with 403 Forbidden
    blocked_res = client.get(f"/api/profile/{senior_id}", headers={"Authorization": f"Bearer {cg_token}"})
    assert blocked_res.status_code == 403
    assert "not have active authorization" in blocked_res.json()["detail"]


def test_production_jwt_secret_validation():
    """Verify Settings rejects default secret key or weak secret in production."""
    # 1. Reject default secret key in production
    with pytest.raises(ValueError, match="cannot use the default placeholder"):
        Settings(
            environment="production",
            app_secret_key="carebridge-default-secret-key-change-me",
        )

    # 2. Reject short secret key (< 32 chars) in production
    with pytest.raises(ValueError, match="at least 32 characters"):
        Settings(
            environment="production",
            app_secret_key="short-secret-key-under-32-chars",
        )

    # 3. Allow strong secret key in production
    prod_settings = Settings(
        environment="production",
        app_secret_key="a" * 32,
    )
    assert prod_settings.environment == "production"

    # 4. Allow default secret in development
    dev_settings = Settings(
        environment="development",
        app_secret_key="carebridge-default-secret-key-change-me",
    )
    assert dev_settings.environment == "development"

    # 5. Allow setting secret via jwt_secret alias
    alias_settings = Settings(
        environment="production",
        jwt_secret="b" * 32,
    )
    assert alias_settings.app_secret_key == "b" * 32


def test_token_security_and_expiration():
    """Verify invalid, expired, and tampered JWT tokens are strictly rejected."""
    # 1. Malformed token string
    res_malformed = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer not.a.valid.jwt"},
    )
    assert res_malformed.status_code == 401

    # 2. Forged token signed with incorrect secret key
    forged_token = jwt.encode(
        {"sub": "1", "role": "senior", "name": "Fake"},
        "completely-different-signing-key-1234567890",
        algorithm=ALGORITHM,
    )
    res_forged = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {forged_token}"},
    )
    assert res_forged.status_code == 401

    # 3. Expired token (delta in the past)
    expired_token = AuthService.create_access_token(
        {"sub": "1", "role": "senior", "name": "Expired"},
        expires_delta=-timedelta(hours=1),
    )
    res_expired = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert res_expired.status_code == 401

    # 4. No token at all
    res_empty = client.get("/api/auth/me")
    assert res_empty.status_code == 401


def test_emergency_contact_no_hardcoded_fallback():
    """Verify senior dashboard does not display hardcoded '911' when no emergency contact is set."""
    # 1. Register Senior without emergency contact
    s_res = client.post(
        "/api/auth/register-senior",
        json={"full_name": "Arthur Pendelton", "passcode": "4455"},
    )
    senior_id = s_res.json()["id"]

    # Login to set cookie
    login_res = client.post(
        "/api/auth/login-passcode",
        json={"user_id": senior_id, "passcode": "4455"},
    )
    token = login_res.json()["access_token"]

    # 2. View senior dashboard
    dash_res = client.get("/senior")
    assert dash_res.status_code == 200
    # Must NOT have hardcoded '911' button
    assert "tel:911" not in dash_res.text
    # Must display 'Not Configured' notice
    assert "Not Configured" in dash_res.text

    # 3. Update emergency contact
    client.put(
        "/api/profile/me",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "emergency_contact_name": "Dr. Watson",
            "emergency_contact_phone": "555-0199",
        },
    )

    # 4. View senior dashboard again
    dash_updated = client.get("/senior")
    assert dash_updated.status_code == 200
    assert "Dr. Watson" in dash_updated.text
    assert "555-0199" in dash_updated.text
