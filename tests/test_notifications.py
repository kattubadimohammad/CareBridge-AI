import asyncio
from datetime import datetime, date, timedelta
from unittest.mock import AsyncMock, patch
import pytest
import aiosmtplib
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.database import SessionLocal
from app.models import (
    User,
    UserRole,
    CaregiverLink,
    CaregiverLinkStatus,
    HealthcareProfile,
    Medication,
    MedicationSchedule,
    MedicationLog,
    DoctorAppointment,
    NotificationLog,
)
from app.services.notification_service import NotificationService
from app.services.scheduler_service import SchedulerService

client = TestClient(app)


@pytest.mark.anyio
async def test_upcoming_medication_email_mock_delivery():
    """Verify upcoming medication reminder email is dispatched with correct details in mock mode."""
    with SessionLocal() as db:
        # Senior in America/New_York
        senior = User(full_name="Beatrice Webb", role=UserRole.SENIOR, email="beatrice@carebridge-test.org", password_hash="dummy")
        db.add(senior)
        db.flush()
        prof = HealthcareProfile(user_id=senior.id, timezone="America/New_York")
        db.add(prof)

        # Approved Caregiver
        caregiver = User(full_name="Nurse Florence", role=UserRole.CAREGIVER, email="florence@hospital.org", password_hash="dummy")
        db.add(caregiver)
        db.flush()

        link = CaregiverLink(
            senior_id=senior.id,
            caregiver_id=caregiver.id,
            status=CaregiverLinkStatus.APPROVED,
            can_manage_medications=True,
            is_active=True,
        )
        db.add(link)

        med = Medication(user_id=senior.id, name="Lisinopril", dosage="10 mg", instructions="Take with water", purpose="Hypertension")
        db.add(med)
        db.flush()

        # Scheduled for 10:00 UTC (06:00 AM EDT)
        dose_time = datetime(2026, 6, 1, 10, 0, 0)
        log = MedicationLog(medication_id=med.id, senior_id=senior.id, scheduled_for=dose_time, status="pending")
        db.add(log)
        db.commit()

        # Execute upcoming reminder dispatch 20 mins before
        as_of = datetime(2026, 6, 1, 9, 40, 0)
        count = await SchedulerService.dispatch_upcoming_medication_notifications(db, as_of=as_of, senior_id=senior.id)
        assert count == 1

        # Check sent messages queue in NotificationService
        sent = NotificationService.get_sent_messages()
        assert len(sent) == 2  # Sent to both senior and approved caregiver
        recipients = [m["recipient_email"] for m in sent]
        assert "beatrice@carebridge-test.org" in recipients
        assert "florence@hospital.org" in recipients

        # Verify email contents
        senior_msg = next(m for m in sent if m["recipient_email"] == "beatrice@carebridge-test.org")
        assert "Lisinopril" in senior_msg["subject"]
        assert "Beatrice Webb" in senior_msg["subject"]
        assert "10 mg" in senior_msg["body_text"]
        assert "06:00 AM (EDT)" in senior_msg["body_text"]
        assert "Take with water" in senior_msg["body_text"]

        # Verify NotificationLog database records
        logs = db.query(NotificationLog).filter(NotificationLog.senior_id == senior.id).all()
        assert len(logs) == 2
        assert all(l.status == "simulated" for l in logs)
        assert all(l.notification_type == "upcoming_medication" for l in logs)


@pytest.mark.anyio
async def test_missed_dose_urgent_caregiver_email():
    """Verify urgent alert is dispatched to approved caregiver when a dose transitions to missed."""
    with SessionLocal() as db:
        senior = User(full_name="Walter Cronkite", role=UserRole.SENIOR, email="walter@news.org", password_hash="dummy")
        db.add(senior)
        db.flush()
        prof = HealthcareProfile(user_id=senior.id, timezone="America/Chicago")
        db.add(prof)

        caregiver = User(full_name="Nurse Jackie", role=UserRole.CAREGIVER, email="jackie@hospital.org", password_hash="dummy")
        db.add(caregiver)
        db.flush()

        link = CaregiverLink(
            senior_id=senior.id,
            caregiver_id=caregiver.id,
            status=CaregiverLinkStatus.APPROVED,
            can_manage_medications=True,
            is_active=True,
        )
        db.add(link)

        med = Medication(user_id=senior.id, name="Warfarin", dosage="5 mg")
        db.add(med)
        db.flush()

        # Missed dose
        dose_time = datetime(2026, 6, 1, 14, 0, 0)
        log = MedicationLog(medication_id=med.id, senior_id=senior.id, scheduled_for=dose_time, status="missed")
        db.add(log)
        db.commit()

        # Dispatch missed dose alert
        count = await SchedulerService.dispatch_missed_dose_notifications(db, as_of=datetime(2026, 6, 1, 15, 30, 0), senior_id=senior.id)
        assert count == 1

        sent = NotificationService.get_sent_messages()
        assert len(sent) == 1
        msg = sent[0]
        assert msg["recipient_email"] == "jackie@hospital.org"
        assert "[CareBridge URGENT] Missed Dose Alert" in msg["subject"]
        assert "Warfarin" in msg["subject"]
        assert "Walter Cronkite" in msg["body_text"]
        assert "MISSED" in msg["body_text"]
        assert "09:00 AM (CDT)" in msg["body_text"]

        db.refresh(log)
        assert log.missed_notification_sent is True


@pytest.mark.anyio
async def test_doctor_appointment_reminder_email():
    """Verify appointment reminders are sent with clinic and preparation details."""
    with SessionLocal() as db:
        senior = User(full_name="Helen Keller", role=UserRole.SENIOR, email="helen@inspire.org", password_hash="dummy")
        db.add(senior)
        db.flush()
        prof = HealthcareProfile(user_id=senior.id, timezone="America/New_York")
        db.add(prof)

        caregiver = User(full_name="Anne Sullivan", role=UserRole.CAREGIVER, email="anne@mentor.org", password_hash="dummy")
        db.add(caregiver)
        db.flush()

        link = CaregiverLink(
            senior_id=senior.id,
            caregiver_id=caregiver.id,
            status=CaregiverLinkStatus.APPROVED,
            can_manage_appointments=True,
            is_active=True,
        )
        db.add(link)

        # Appointment 24 hours in the future
        now = datetime(2026, 8, 10, 10, 0, 0)
        appt_time = now + timedelta(hours=24)
        appt = DoctorAppointment(
            senior_id=senior.id,
            created_by_user_id=caregiver.id,
            doctor_name="Dr. Gregory House",
            specialty="Diagnostics",
            clinic_name="Princeton Clinic",
            clinic_address="123 Hospital Way",
            contact_phone="555-0188",
            appointment_datetime=appt_time,
            purpose="Annual Diagnostic Review",
            preparation_instructions="Bring previous health logs and fast 12 hours",
            status="scheduled",
            reminder_sent=False,
        )
        db.add(appt)
        db.commit()

        # Dispatch appointment reminders
        count = await SchedulerService.dispatch_appointment_reminders(db, as_of=now, senior_id=senior.id)
        assert count == 1

        sent = NotificationService.get_sent_messages()
        assert len(sent) == 2  # Senior + Caregiver
        cg_msg = next(m for m in sent if m["recipient_email"] == "anne@mentor.org")
        assert "Dr. Gregory House" in cg_msg["subject"]
        assert "Princeton Clinic" in cg_msg["body_text"]
        assert "fast 12 hours" in cg_msg["body_text"]
        assert "555-0188" in cg_msg["body_text"]

        db.refresh(appt)
        assert appt.reminder_sent is True


@pytest.mark.anyio
async def test_unauthorized_caregiver_notification_rejection():
    """SECURITY TEST: Caregivers with pending, rejected, or revoked links MUST NOT receive emails."""
    with SessionLocal() as db:
        senior = User(full_name="Thomas Edison", role=UserRole.SENIOR, email="thomas@edison.org", password_hash="dummy")
        db.add(senior)
        db.flush()

        # 1. Approved caregiver
        cg_approved = User(full_name="Approved Nurse", role=UserRole.CAREGIVER, email="nurse.approved@hospital.org", password_hash="dummy")
        db.add(cg_approved)
        db.flush()
        link_appr = CaregiverLink(
            senior_id=senior.id,
            caregiver_id=cg_approved.id,
            status=CaregiverLinkStatus.APPROVED,
            can_manage_medications=True,
            is_active=True,
        )
        db.add(link_appr)

        # 2. Pending caregiver (NOT approved)
        cg_pending = User(full_name="Pending Caregiver", role=UserRole.CAREGIVER, email="caregiver.pending@hospital.org", password_hash="dummy")
        db.add(cg_pending)
        db.flush()
        link_pend = CaregiverLink(
            senior_id=senior.id,
            caregiver_id=cg_pending.id,
            status=CaregiverLinkStatus.PENDING,
            can_manage_medications=True,
            is_active=False,
        )
        db.add(link_pend)

        # 3. Revoked caregiver
        cg_revoked = User(full_name="Revoked Caregiver", role=UserRole.CAREGIVER, email="caregiver.revoked@hospital.org", password_hash="dummy")
        db.add(cg_revoked)
        db.flush()
        link_rev = CaregiverLink(
            senior_id=senior.id,
            caregiver_id=cg_revoked.id,
            status=CaregiverLinkStatus.REVOKED,
            can_manage_medications=True,
            is_active=False,
        )
        db.add(link_rev)

        med = Medication(user_id=senior.id, name="Heart Pill", dosage="25 mg")
        db.add(med)
        db.flush()
        log = MedicationLog(medication_id=med.id, senior_id=senior.id, scheduled_for=datetime.utcnow() + timedelta(minutes=15), status="pending")
        db.add(log)
        db.commit()

        # Dispatch
        await SchedulerService.dispatch_upcoming_medication_notifications(db, as_of=datetime.utcnow(), senior_id=senior.id)

        sent = NotificationService.get_sent_messages()
        recipients = [m["recipient_email"] for m in sent]

        # Approved caregiver received alert
        assert "nurse.approved@hospital.org" in recipients
        # Pending and revoked caregivers were strictly EXCLUDED
        assert "caregiver.pending@hospital.org" not in recipients
        assert "caregiver.revoked@hospital.org" not in recipients


@pytest.mark.anyio
async def test_duplicate_notification_prevention():
    """Verify repeated dispatch calls do NOT produce duplicate emails."""
    with SessionLocal() as db:
        senior = User(full_name="Nikola Tesla", role=UserRole.SENIOR, email="tesla@lab.org", password_hash="dummy")
        db.add(senior)
        db.flush()
        med = Medication(user_id=senior.id, name="Daily Supplement", dosage="1 tab")
        db.add(med)
        db.flush()
        dose_time = datetime(2026, 9, 1, 12, 0, 0)
        log = MedicationLog(medication_id=med.id, senior_id=senior.id, scheduled_for=dose_time, status="pending")
        db.add(log)
        db.commit()

        as_of = datetime(2026, 9, 1, 11, 45, 0)

        # 1st execution
        res1 = await SchedulerService.dispatch_all_notifications(db, as_of=as_of, senior_id=senior.id)
        assert res1["medication_reminders"] == 1
        initial_count = len(NotificationService.get_sent_messages())
        assert initial_count == 1

        # 2nd consecutive execution at same timestamp
        res2 = await SchedulerService.dispatch_all_notifications(db, as_of=as_of, senior_id=senior.id)
        assert res2["medication_reminders"] == 0
        assert len(NotificationService.get_sent_messages()) == initial_count

        # 3rd execution 5 minutes later
        res3 = await SchedulerService.dispatch_all_notifications(db, as_of=as_of + timedelta(minutes=5), senior_id=senior.id)
        assert res3["medication_reminders"] == 0
        assert len(NotificationService.get_sent_messages()) == initial_count


@pytest.mark.anyio
async def test_smtp_failure_and_safe_retry(monkeypatch):
    """Verify that transient SMTP failures record a failure and allow subsequent safe retries without state corruption."""
    with SessionLocal() as db:
        senior = User(full_name="Marie Curie", role=UserRole.SENIOR, email="marie@rad.org", password_hash="dummy")
        db.add(senior)
        db.flush()
        med = Medication(user_id=senior.id, name="Calcium", dosage="500 mg")
        db.add(med)
        db.flush()
        log = MedicationLog(medication_id=med.id, senior_id=senior.id, scheduled_for=datetime(2026, 10, 1, 8, 0, 0), status="pending")
        db.add(log)
        db.commit()

        as_of = datetime(2026, 10, 1, 7, 45, 0)

        # Enable real SMTP mode
        monkeypatch.setattr(settings, "smtp_enabled", True)
        monkeypatch.setattr(settings, "smtp_host", "smtp.mock-provider.net")
        monkeypatch.setattr(settings, "smtp_user", "carebridge-user")
        monkeypatch.setattr(settings, "smtp_password", "SuperSecretPassword123")

        # Mock aiosmtplib.send to simulate network connection error
        with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = aiosmtplib.SMTPConnectError("Connection to smtp.mock-provider.net timed out.")

            # Attempt 1: Delivery fails
            count_failed = await SchedulerService.dispatch_upcoming_medication_notifications(db, as_of=as_of, senior_id=senior.id)
            assert count_failed == 0

            # Verify log entry in NotificationLog has status failed
            failed_log = db.query(NotificationLog).filter(NotificationLog.recipient_email == "marie@rad.org").first()
            assert failed_log is not None
            assert failed_log.status == "failed"
            assert "Connection to smtp.mock-provider.net timed out" in failed_log.error_message
            # Sensitive password MUST NOT be exposed in error message
            assert "SuperSecretPassword123" not in failed_log.error_message

            # MedicationLog reminder_sent MUST still be False (allowing retry)
            db.refresh(log)
            assert log.reminder_sent is False

        # Attempt 2: SMTP provider recovers, mock successful transmission
        with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send_ok:
            mock_send_ok.return_value = ({"marie@rad.org": (250, "OK")}, "Queued")

            count_success = await SchedulerService.dispatch_upcoming_medication_notifications(db, as_of=as_of, senior_id=senior.id)
            assert count_success == 1

            # Delivery successfully confirmed
            success_log = (
                db.query(NotificationLog)
                .filter(NotificationLog.recipient_email == "marie@rad.org", NotificationLog.status == "sent")
                .first()
            )
            assert success_log is not None
            assert success_log.status == "sent"

            # MedicationLog now marked as sent
            db.refresh(log)
            assert log.reminder_sent is True


def test_cron_endpoint_integration_and_auth(monkeypatch):
    """Verify /api/cron/check-reminders triggers scheduler and notifications with proper auth."""
    # 1. Dev mode: No auth token required
    res_dev = client.post("/api/cron/check-reminders")
    assert res_dev.status_code == 200
    data_dev = res_dev.json()
    assert data_dev["status"] == "success"
    assert "notifications_sent_count" in data_dev

    # 2. Production mode: Token required
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "cron_api_key", "secret-cron-token-xyz")

    # Missing token -> 401
    res_no_token = client.post("/api/cron/check-reminders")
    assert res_no_token.status_code == 401

    # Invalid token -> 401
    res_bad_token = client.post(
        "/api/cron/check-reminders",
        headers={"X-Scheduler-Token": "wrong-token"},
    )
    assert res_bad_token.status_code == 401

    # Valid token -> 200 OK
    res_auth = client.post(
        "/api/cron/check-reminders",
        headers={"X-Scheduler-Token": "secret-cron-token-xyz"},
    )
    assert res_auth.status_code == 200
    assert res_auth.json()["status"] == "success"
