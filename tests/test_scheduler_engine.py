from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import (
    User,
    UserRole,
    HealthcareProfile,
    Medication,
    MedicationSchedule,
    MedicationLog,
    MedicationStatusAudit,
)
from app.services.scheduler_service import SchedulerService

client = TestClient(app)


def test_multiple_daily_doses_generation():
    """Verify medication scheduling supports multiple doses per day with audit tracking."""
    # 1. Register Senior
    reg_s = client.post(
        "/api/auth/register-senior",
        json={"full_name": "Robert Frost", "passcode": "3344"},
    )
    senior_id = reg_s.json()["id"]

    # 2. Add Medication with 3 daily doses (Morning, Afternoon, Evening)
    login_s = client.post("/api/auth/login-passcode", json={"user_id": senior_id, "passcode": "3344"})
    token = login_s.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    med_res = client.post(
        f"/api/medications?senior_id={senior_id}",
        headers=headers,
        json={
            "name": "Metformin",
            "dosage": "500 mg",
            "instructions": "Take with meals",
            "purpose": "Glycemic regulation",
            "schedules": [
                {"scheduled_time": "08:00", "days_of_week": "everyday", "timezone": "UTC"},
                {"scheduled_time": "14:00", "days_of_week": "everyday", "timezone": "UTC"},
                {"scheduled_time": "20:00", "days_of_week": "everyday", "timezone": "UTC"},
            ],
        },
    )
    assert med_res.status_code == 201

    with SessionLocal() as db:
        # Generate doses for 2026-05-10
        target = date(2026, 5, 10)
        generated = SchedulerService.generate_scheduled_doses(db, target_date=target, senior_id=senior_id)
        assert len(generated) == 3

        # Verify all 3 distinct times exist in database
        logs = (
            db.query(MedicationLog)
            .filter(MedicationLog.senior_id == senior_id)
            .order_by(MedicationLog.scheduled_for.asc())
            .all()
        )
        assert len(logs) == 3
        times = [log.scheduled_for.strftime("%H:%M") for log in logs]
        assert times == ["08:00", "14:00", "20:00"]
        assert all(log.status == "pending" for log in logs)
        assert all(log.reminder_sent is False for log in logs)

        # Verify audit trail records for each dose
        audits = db.query(MedicationStatusAudit).filter(MedicationStatusAudit.senior_id == senior_id).all()
        assert len(audits) == 3
        assert all(a.new_status == "pending" for a in audits)


def test_different_timezones_scheduling():
    """Verify senior timezone configuration converts local scheduled wall-clock time to UTC correctly."""
    with SessionLocal() as db:
        # Senior 1: London (Europe/London)
        user_lon = User(full_name="Arthur London", role=UserRole.SENIOR, password_hash="dummy")
        db.add(user_lon)
        db.flush()
        prof_lon = HealthcareProfile(user_id=user_lon.id, timezone="Europe/London")
        db.add(prof_lon)
        med_lon = Medication(user_id=user_lon.id, name="Med London", dosage="1 tab")
        db.add(med_lon)
        db.flush()
        sch_lon = MedicationSchedule(medication_id=med_lon.id, scheduled_time="09:00", days_of_week="everyday")
        db.add(sch_lon)

        # Senior 2: Tokyo (Asia/Tokyo, UTC+9 year-round)
        user_tok = User(full_name="Kenji Tokyo", role=UserRole.SENIOR, password_hash="dummy")
        db.add(user_tok)
        db.flush()
        prof_tok = HealthcareProfile(user_id=user_tok.id, timezone="Asia/Tokyo")
        db.add(prof_tok)
        med_tok = Medication(user_id=user_tok.id, name="Med Tokyo", dosage="1 tab")
        db.add(med_tok)
        db.flush()
        sch_tok = MedicationSchedule(medication_id=med_tok.id, scheduled_time="09:00", days_of_week="everyday")
        db.add(sch_tok)

        # Senior 3: New York (America/New_York, EST = UTC-5 in January)
        user_ny = User(full_name="Emily NewYork", role=UserRole.SENIOR, password_hash="dummy")
        db.add(user_ny)
        db.flush()
        prof_ny = HealthcareProfile(user_id=user_ny.id, timezone="America/New_York")
        db.add(prof_ny)
        med_ny = Medication(user_id=user_ny.id, name="Med NewYork", dosage="1 tab")
        db.add(med_ny)
        db.flush()
        sch_ny = MedicationSchedule(medication_id=med_ny.id, scheduled_time="09:00", days_of_week="everyday")
        db.add(sch_ny)

        db.commit()

        # Target winter date: 2026-01-15
        target = date(2026, 1, 15)
        SchedulerService.generate_scheduled_doses(db, target_date=target)

        # Verify London: 09:00 GMT -> 09:00 UTC
        log_lon = db.query(MedicationLog).filter(MedicationLog.senior_id == user_lon.id).first()
        assert log_lon is not None
        assert log_lon.scheduled_for == datetime(2026, 1, 15, 9, 0, 0)

        # Verify Tokyo: 09:00 JST -> 00:00 UTC (9:00 - 9h = 00:00 UTC)
        log_tok = db.query(MedicationLog).filter(MedicationLog.senior_id == user_tok.id).first()
        assert log_tok is not None
        assert log_tok.scheduled_for == datetime(2026, 1, 15, 0, 0, 0)

        # Verify New York: 09:00 EST -> 14:00 UTC (9:00 + 5h = 14:00 UTC)
        log_ny = db.query(MedicationLog).filter(MedicationLog.senior_id == user_ny.id).first()
        assert log_ny is not None
        assert log_ny.scheduled_for == datetime(2026, 1, 15, 14, 0, 0)


def test_daylight_saving_transitions():
    """Verify that Daylight Saving Time (DST) changes are accurately handled across transition dates."""
    with SessionLocal() as db:
        # Senior in America/New_York (EST/EDT)
        user = User(full_name="Eleanor NYC", role=UserRole.SENIOR, password_hash="dummy")
        db.add(user)
        db.flush()
        prof = HealthcareProfile(user_id=user.id, timezone="America/New_York")
        db.add(prof)
        med = Medication(user_id=user.id, name="Daily Blood Pressure", dosage="10 mg")
        db.add(med)
        db.flush()
        sch = MedicationSchedule(medication_id=med.id, scheduled_time="08:00", days_of_week="everyday")
        db.add(sch)
        db.commit()

        # Date 1: Standard Time (EST = UTC-5) -> 2026-03-07
        # 08:00 AM EST is 13:00 UTC
        SchedulerService.generate_scheduled_doses(db, target_date=date(2026, 3, 7), senior_id=user.id)
        log_est = (
            db.query(MedicationLog)
            .filter(MedicationLog.senior_id == user.id, MedicationLog.scheduled_for >= datetime(2026, 3, 7, 0, 0))
            .first()
        )
        assert log_est is not None
        assert log_est.scheduled_for == datetime(2026, 3, 7, 13, 0, 0)

        # Date 2: Daylight Saving Time (EDT = UTC-4) -> 2026-03-10 (DST starts March 8, 2026)
        # 08:00 AM EDT is 12:00 UTC
        SchedulerService.generate_scheduled_doses(db, target_date=date(2026, 3, 10), senior_id=user.id)
        log_edt = (
            db.query(MedicationLog)
            .filter(MedicationLog.senior_id == user.id, MedicationLog.scheduled_for >= datetime(2026, 3, 10, 0, 0))
            .first()
        )
        assert log_edt is not None
        assert log_edt.scheduled_for == datetime(2026, 3, 10, 12, 0, 0)


def test_upcoming_reminders_identification():
    """Verify scheduler identifies pending doses within reminder window and prevents duplicate alerts."""
    with SessionLocal() as db:
        user = User(full_name="Grace Hopper", role=UserRole.SENIOR, password_hash="dummy")
        db.add(user)
        db.flush()
        med = Medication(user_id=user.id, name="Antibiotic", dosage="250 mg")
        db.add(med)
        db.flush()

        # Scheduled for 10:00 UTC
        dose_time = datetime(2026, 6, 1, 10, 0, 0)
        log = MedicationLog(medication_id=med.id, senior_id=user.id, scheduled_for=dose_time, status="pending")
        db.add(log)
        db.commit()

        # At 09:15 UTC (45 min before): Outside 30-min window -> no reminder
        reminders_early = SchedulerService.identify_upcoming_reminders(
            db, as_of=datetime(2026, 6, 1, 9, 15, 0), window_minutes=30, senior_id=user.id
        )
        assert len(reminders_early) == 0

        # At 09:40 UTC (20 min before): Within 30-min window -> reminder triggered
        reminders_due = SchedulerService.identify_upcoming_reminders(
            db, as_of=datetime(2026, 6, 1, 9, 40, 0), window_minutes=30, senior_id=user.id
        )
        assert len(reminders_due) == 1
        assert reminders_due[0].id == log.id

        # Verify reminder state persisted in database
        db.refresh(log)
        assert log.reminder_sent is True
        assert log.reminder_sent_at == datetime(2026, 6, 1, 9, 40, 0)

        # Idempotency check: Consecutive check at 09:45 UTC does NOT trigger duplicate reminder
        reminders_repeat = SchedulerService.identify_upcoming_reminders(
            db, as_of=datetime(2026, 6, 1, 9, 45, 0), window_minutes=30, senior_id=user.id
        )
        assert len(reminders_repeat) == 0


def test_overdue_and_grace_period_handling():
    """Verify doses transition to missed only after configured grace period expires."""
    with SessionLocal() as db:
        user = User(full_name="Alan Turing", role=UserRole.SENIOR, password_hash="dummy")
        db.add(user)
        db.flush()
        med = Medication(user_id=user.id, name="Daily Vitamin", dosage="1 cap")
        db.add(med)
        db.flush()

        # Scheduled for 08:00 UTC. Grace period = 60 minutes.
        dose_time = datetime(2026, 6, 1, 8, 0, 0)
        log = MedicationLog(medication_id=med.id, senior_id=user.id, scheduled_for=dose_time, status="pending")
        db.add(log)
        db.commit()

        # Check at 08:45 UTC (45 minutes past schedule): Inside 60-min grace period -> remains pending
        overdue_in_grace = SchedulerService.process_overdue_doses(
            db, as_of=datetime(2026, 6, 1, 8, 45, 0), grace_period_minutes=60, senior_id=user.id
        )
        assert len(overdue_in_grace) == 0
        db.refresh(log)
        assert log.status == "pending"

        # Check at 09:05 UTC (65 minutes past schedule): Grace period expired -> transitioned to missed
        overdue_past_grace = SchedulerService.process_overdue_doses(
            db, as_of=datetime(2026, 6, 1, 9, 5, 0), grace_period_minutes=60, senior_id=user.id
        )
        assert len(overdue_past_grace) == 1
        db.refresh(log)
        assert log.status == "missed"

        # Verify audit record created for missed status
        audit = (
            db.query(MedicationStatusAudit)
            .filter(MedicationStatusAudit.log_id == log.id, MedicationStatusAudit.new_status == "missed")
            .first()
        )
        assert audit is not None
        assert "Grace period of 60 minute(s) exceeded" in audit.reason


def test_taken_and_skipped_dose_protection():
    """STRICT SAFETY TEST: Doses already confirmed as taken or skipped must NEVER be marked as missed."""
    with SessionLocal() as db:
        user = User(full_name="Margaret Hamilton", role=UserRole.SENIOR, password_hash="dummy")
        db.add(user)
        db.flush()
        med = Medication(user_id=user.id, name="Heart Medication", dosage="20 mg")
        db.add(med)
        db.flush()

        dose_time = datetime(2026, 6, 1, 8, 0, 0)

        # Log 1: Confirmed TAKEN
        log_taken = MedicationLog(
            medication_id=med.id,
            senior_id=user.id,
            scheduled_for=dose_time,
            status="taken",
            taken_at=datetime(2026, 6, 1, 8, 10, 0),
        )
        db.add(log_taken)

        # Log 2: Confirmed SKIPPED (e.g. physician advised skip for fasting)
        log_skipped = MedicationLog(
            medication_id=med.id,
            senior_id=user.id,
            scheduled_for=dose_time + timedelta(hours=4),
            status="skipped",
            notes="Fasting blood test today",
        )
        db.add(log_skipped)

        # Log 3: Unconfirmed PENDING
        log_pending = MedicationLog(
            medication_id=med.id,
            senior_id=user.id,
            scheduled_for=dose_time + timedelta(hours=8),
            status="pending",
        )
        db.add(log_pending)
        db.commit()

        # Advance time to 24 hours later (long past grace period)
        future_time = datetime(2026, 6, 2, 8, 0, 0)
        overdue = SchedulerService.process_overdue_doses(
            db, as_of=future_time, grace_period_minutes=60, senior_id=user.id
        )

        # Only the pending dose should be marked missed
        assert len(overdue) == 1
        assert overdue[0].id == log_pending.id

        # Verify taken and skipped doses were NOT modified
        db.refresh(log_taken)
        db.refresh(log_skipped)
        assert log_taken.status == "taken"
        assert log_skipped.status == "skipped"


def test_idempotent_duplicate_scheduler_execution():
    """Verify repeated execution of evaluate_pending_doses does not create duplicates or repeat alerts."""
    with SessionLocal() as db:
        user = User(full_name="Ada Lovelace", role=UserRole.SENIOR, password_hash="dummy")
        db.add(user)
        db.flush()
        prof = HealthcareProfile(user_id=user.id, timezone="UTC")
        db.add(prof)
        med = Medication(user_id=user.id, name="Daily Multivitamin", dosage="1 tablet")
        db.add(med)
        db.flush()
        sch = MedicationSchedule(medication_id=med.id, scheduled_time="08:00", days_of_week="everyday")
        db.add(sch)
        db.commit()

        as_of = datetime(2026, 7, 1, 8, 15, 0)

        # First run: Generates dose, evaluates
        run1 = SchedulerService.evaluate_pending_doses(db=db, as_of=as_of)
        assert run1["generated_doses"] == 1
        assert run1["alerts"] == 1

        # Second consecutive run with same timestamp: 0 new doses, 0 duplicate alerts
        run2 = SchedulerService.evaluate_pending_doses(db=db, as_of=as_of)
        assert run2["generated_doses"] == 0
        assert run2["alerts"] == 0

        # Third consecutive run: Still 0
        run3 = SchedulerService.evaluate_pending_doses(db=db, as_of=as_of)
        assert run3["generated_doses"] == 0
        assert run3["alerts"] == 0

        # Verify total database records count is strictly 1
        total_logs = db.query(MedicationLog).filter(MedicationLog.senior_id == user.id).count()
        assert total_logs == 1


def test_audit_trail_and_api_persistence():
    """Verify end-to-end audit logging via API dose confirmation and audit retrieval endpoint."""
    # 1. Register Senior
    reg_s = client.post(
        "/api/auth/register-senior",
        json={"full_name": "Katherine Johnson", "passcode": "7788"},
    )
    senior_id = reg_s.json()["id"]

    # Login as Senior
    login_s = client.post("/api/auth/login-passcode", json={"user_id": senior_id, "passcode": "7788"})
    senior_token = login_s.json()["access_token"]
    senior_headers = {"Authorization": f"Bearer {senior_token}"}

    # Add medication
    med_res = client.post(
        f"/api/medications?senior_id={senior_id}",
        headers=senior_headers,
        json={
            "name": "Vitamin D3",
            "dosage": "1000 IU",
            "schedules": [{"scheduled_time": "08:00", "days_of_week": "everyday"}],
        },
    )
    assert med_res.status_code == 201

    # Fetch today's doses to generate log
    today_res = client.get(f"/api/adherence/senior/{senior_id}/today", headers=senior_headers)
    assert today_res.status_code == 200
    doses = today_res.json()
    assert len(doses) == 1
    log_id = doses[0]["id"]

    # Confirm dose as TAKEN via API
    confirm_res = client.post(
        f"/api/adherence/logs/{log_id}/confirm",
        headers=senior_headers,
        json={"action": "taken", "notes": "Taken with breakfast and juice"},
    )
    assert confirm_res.status_code == 200
    assert confirm_res.json()["status"] == "taken"

    # Fetch audits via API
    audits_res = client.get(f"/api/adherence/senior/{senior_id}/audits", headers=senior_headers)
    assert audits_res.status_code == 200
    audits = audits_res.json()
    assert len(audits) >= 2  # Generation audit + Taken transition audit

    latest_audit = audits[0]
    assert latest_audit["new_status"] == "taken"
    assert latest_audit["changed_by_user_id"] == senior_id
    assert "Taken with breakfast and juice" in latest_audit["reason"]

    # Test unauthorized access to audits is rejected
    client.cookies.clear()
    unauth_res = client.get(f"/api/adherence/senior/{senior_id}/audits")
    assert unauth_res.status_code == 401


def test_asia_kolkata_schedule_timezone_regression():
    """Regression test: Senior in Asia/Kolkata with medication scheduled for 18:00 must display as 6:00 PM on dashboard.

    Verifies:
    1. Underlying database MedicationLog.scheduled_for persists UTC timestamp (12:30:00).
    2. Adherence API (/api/adherence/senior/{id}/today) converts UTC to senior timezone (18:00:00+05:30).
    3. Senior Dashboard (/senior) displays '6:00 PM' and does not display raw UTC '12:30 PM'.
    4. Dose remains pending without unauthorized status mutation (never marked taken or skipped).
    """
    client.cookies.clear()

    # 1. Register Senior
    reg_res = client.post(
        "/api/auth/register-senior",
        json={"full_name": "Aarav Sharma", "passcode": "5566"},
    )
    assert reg_res.status_code == 201
    senior_id = reg_res.json()["id"]

    # 2. Login as Senior
    login_res = client.post(
        "/api/auth/login-passcode",
        json={"user_id": senior_id, "passcode": "5566"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Configure Senior Profile Timezone as Asia/Kolkata
    prof_res = client.put(
        "/api/profile/me",
        headers=headers,
        json={"timezone": "Asia/Kolkata"},
    )
    assert prof_res.status_code == 200
    assert prof_res.json()["timezone"] == "Asia/Kolkata"

    # 4. Create Medication with schedule 18:00
    med_res = client.post(
        "/api/medications",
        headers=headers,
        json={
            "name": "Metformin XR",
            "dosage": "500 mg",
            "instructions": "Take with dinner",
            "schedules": [
                {"scheduled_time": "18:00", "days_of_week": "everyday", "timezone": "Asia/Kolkata"}
            ],
        },
    )
    assert med_res.status_code == 201

    # 5. Fetch today's doses via adherence API
    today_res = client.get(f"/api/adherence/senior/{senior_id}/today", headers=headers)
    assert today_res.status_code == 200
    doses = today_res.json()
    assert len(doses) == 1
    dose = doses[0]
    assert dose["status"] == "pending"

    # Verify API returned local scheduled time has hour 18, minute 0
    parsed_sched = datetime.fromisoformat(dose["scheduled_for"])
    assert parsed_sched.hour == 18
    assert parsed_sched.minute == 0

    # 6. Verify UTC storage in database (18:00 Asia/Kolkata -> 12:30 UTC)
    with SessionLocal() as db:
        log = db.query(MedicationLog).filter(MedicationLog.senior_id == senior_id).first()
        assert log is not None
        assert log.scheduled_for.hour == 12
        assert log.scheduled_for.minute == 30
        assert log.status == "pending"
        assert log.taken_at is None

    # 7. Verify Senior Dashboard rendering
    dash_res = client.get("/senior")
    assert dash_res.status_code == 200
    assert "6:00 PM" in dash_res.text
    assert "12:30 PM" not in dash_res.text
    assert "Metformin XR" in dash_res.text

    # Re-verify database dose was not mutated by dashboard access
    with SessionLocal() as db:
        log_after = db.query(MedicationLog).filter(MedicationLog.senior_id == senior_id).first()
        assert log_after.status == "pending"
        assert log_after.taken_at is None


def test_utc_schedule_timezone_regression():
    """Regression test: Senior in UTC with medication scheduled for 18:00 displays as 6:00 PM."""
    client.cookies.clear()

    # 1. Register Senior
    reg_res = client.post(
        "/api/auth/register-senior",
        json={"full_name": "Oliver Twist", "passcode": "1122"},
    )
    assert reg_res.status_code == 201
    senior_id = reg_res.json()["id"]

    # 2. Login as Senior
    login_res = client.post(
        "/api/auth/login-passcode",
        json={"user_id": senior_id, "passcode": "1122"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Configure Senior Profile Timezone as UTC
    prof_res = client.put(
        "/api/profile/me",
        headers=headers,
        json={"timezone": "UTC"},
    )
    assert prof_res.status_code == 200
    assert prof_res.json()["timezone"] == "UTC"

    # 4. Create Medication with schedule 18:00 UTC
    med_res = client.post(
        "/api/medications",
        headers=headers,
        json={
            "name": "Lisinopril",
            "dosage": "10 mg",
            "instructions": "Take in evening",
            "schedules": [
                {"scheduled_time": "18:00", "days_of_week": "everyday", "timezone": "UTC"}
            ],
        },
    )
    assert med_res.status_code == 201

    # 5. Fetch today's doses via adherence API
    today_res = client.get(f"/api/adherence/senior/{senior_id}/today", headers=headers)
    assert today_res.status_code == 200
    doses = today_res.json()
    assert len(doses) == 1
    assert doses[0]["status"] == "pending"

    parsed_sched = datetime.fromisoformat(doses[0]["scheduled_for"])
    assert parsed_sched.hour == 18
    assert parsed_sched.minute == 0

    # 6. Verify UTC storage in database (18:00 UTC -> 18:00 UTC)
    with SessionLocal() as db:
        log = db.query(MedicationLog).filter(MedicationLog.senior_id == senior_id).first()
        assert log is not None
        assert log.scheduled_for.hour == 18
        assert log.scheduled_for.minute == 0
        assert log.status == "pending"
        assert log.taken_at is None

    # 7. Verify Senior Dashboard rendering
    dash_res = client.get("/senior")
    assert dash_res.status_code == 200
    assert "6:00 PM" in dash_res.text
    assert "Lisinopril" in dash_res.text

    # Re-verify database dose was not mutated
    with SessionLocal() as db:
        log_after = db.query(MedicationLog).filter(MedicationLog.senior_id == senior_id).first()
        assert log_after.status == "pending"
        assert log_after.taken_at is None
