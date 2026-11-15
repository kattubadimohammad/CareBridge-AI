import logging
from datetime import datetime, date, time, timedelta, timezone
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sqlalchemy.orm import Session

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
    MedicationStatusAudit,
    DoctorAppointment,
    NotificationLog,
)
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


def get_safe_timezone(tz_name: Optional[str]) -> ZoneInfo:
    """Retrieve a valid ZoneInfo instance, falling back safely to UTC if invalid."""
    if not tz_name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, Exception):
        logger.warning(f"Invalid timezone '{tz_name}' requested. Defaulting to UTC.")
        return ZoneInfo("UTC")


class SchedulerService:
    """Medication Scheduling and Reminder Engine with timezone awareness, grace-period evaluation, and audit tracking."""

    @classmethod
    def generate_scheduled_doses(
        cls,
        db: Session,
        target_date: Optional[date] = None,
        senior_id: Optional[int] = None,
    ) -> List[MedicationLog]:
        """Generate scheduled dose entries for active medications on the target date.
        
        Supports multiple daily doses per medication and respects senior and schedule timezones.
        Guarantees idempotency via database unique constraints and existence checks.
        """
        # Query active seniors
        senior_query = db.query(User).filter(User.role == UserRole.SENIOR, User.is_active == True)
        if senior_id is not None:
            senior_query = senior_query.filter(User.id == senior_id)
        seniors = senior_query.all()

        created_logs: List[MedicationLog] = []

        for senior in seniors:
            # 1. Determine senior's configured timezone
            senior_tz = get_safe_timezone(senior.profile.timezone if senior.profile else "UTC")

            # 2. Fetch active medications for this senior
            medications = (
                db.query(Medication)
                .filter(Medication.user_id == senior.id, Medication.is_active == True)
                .all()
            )

            for med in medications:
                for sch in med.schedules:
                    # Resolve timezone: schedule-level override or senior profile timezone
                    sch_tz = get_safe_timezone(sch.timezone) if sch.timezone and sch.timezone != "UTC" else senior_tz

                    # Resolve local date in the resolved timezone
                    local_date = target_date if target_date is not None else datetime.now(sch_tz).date()

                    # Check day of week matching (e.g., 'everyday' or 'mon,wed,fri')
                    weekday_abbr = local_date.strftime("%a").lower()[:3]
                    if sch.days_of_week and sch.days_of_week.lower() != "everyday":
                        allowed_days = [d.strip().lower()[:3] for d in sch.days_of_week.split(",")]
                        if weekday_abbr not in allowed_days:
                            continue

                    # Parse scheduled wall-clock time
                    try:
                        hour_str, min_str = sch.scheduled_time.split(":")
                        hour, minute = int(hour_str), int(min_str)
                    except ValueError:
                        logger.error(f"Invalid scheduled_time format '{sch.scheduled_time}' on schedule {sch.id}")
                        continue

                    # Construct timezone-aware local datetime and convert to UTC
                    local_dt = datetime(local_date.year, local_date.month, local_date.day, hour, minute, tzinfo=sch_tz)
                    utc_dt = local_dt.astimezone(timezone.utc).replace(tzinfo=None)

                    # Check for existing dose log (idempotent duplicate prevention)
                    existing_log = (
                        db.query(MedicationLog)
                        .filter(
                            MedicationLog.medication_id == med.id,
                            MedicationLog.scheduled_for == utc_dt,
                        )
                        .first()
                    )

                    if not existing_log:
                        new_log = MedicationLog(
                            medication_id=med.id,
                            senior_id=senior.id,
                            scheduled_for=utc_dt,
                            status="pending",
                            reminder_sent=False,
                        )
                        db.add(new_log)
                        db.flush()

                        # Record audit trail for initial generation
                        audit = MedicationStatusAudit(
                            log_id=new_log.id,
                            senior_id=senior.id,
                            medication_id=med.id,
                            previous_status=None,
                            new_status="pending",
                            changed_by_user_id=None,
                            reason="Scheduled dose generated by scheduler engine",
                            timestamp=datetime.utcnow(),
                        )
                        db.add(audit)
                        created_logs.append(new_log)

        db.commit()
        return created_logs

    @classmethod
    def identify_upcoming_reminders(
        cls,
        db: Session,
        as_of: Optional[datetime] = None,
        window_minutes: Optional[int] = None,
        senior_id: Optional[int] = None,
    ) -> List[MedicationLog]:
        """Identify upcoming pending doses within the reminder window and flag them as reminded.
        
        Guarantees idempotency: doses with reminder_sent=True are excluded.
        """
        now = as_of or datetime.utcnow()
        window = window_minutes if window_minutes is not None else settings.reminder_window_minutes
        window_end = now + timedelta(minutes=window)
        # Include pending doses within the reminder window and any recent pending doses still within grace period
        window_start = now - timedelta(minutes=settings.dose_grace_period_minutes)

        query = (
            db.query(MedicationLog)
            .join(Medication, Medication.id == MedicationLog.medication_id)
            .join(User, User.id == MedicationLog.senior_id)
            .filter(
                MedicationLog.status == "pending",
                MedicationLog.reminder_sent == False,
                MedicationLog.scheduled_for >= window_start,
                MedicationLog.scheduled_for <= window_end,
                Medication.is_active == True,
                User.is_active == True,
            )
        )
        if senior_id is not None:
            query = query.filter(MedicationLog.senior_id == senior_id)

        pending_reminders = query.all()

        for log in pending_reminders:
            log.reminder_sent = True
            log.reminder_sent_at = now

            audit = MedicationStatusAudit(
                log_id=log.id,
                senior_id=log.senior_id,
                medication_id=log.medication_id,
                previous_status="pending",
                new_status="pending",
                changed_by_user_id=None,
                reason=f"Upcoming medication reminder triggered (scheduled for {log.scheduled_for.isoformat()}Z)",
                timestamp=now,
            )
            db.add(audit)

        if pending_reminders:
            db.commit()

        return pending_reminders

    @classmethod
    def process_overdue_doses(
        cls,
        db: Session,
        as_of: Optional[datetime] = None,
        grace_period_minutes: Optional[int] = None,
        senior_id: Optional[int] = None,
    ) -> List[MedicationLog]:
        """Identify overdue pending doses past the configured grace period and transition to 'missed'.
        
        STRICT SAFETY RULE: Doses already confirmed as 'taken' or 'skipped' are NEVER marked as missed.
        """
        now = as_of or datetime.utcnow()
        grace = grace_period_minutes if grace_period_minutes is not None else settings.dose_grace_period_minutes
        cutoff = now - timedelta(minutes=grace)

        query = (
            db.query(MedicationLog)
            .join(Medication, Medication.id == MedicationLog.medication_id)
            .join(User, User.id == MedicationLog.senior_id)
            .filter(
                MedicationLog.status == "pending",
                MedicationLog.scheduled_for < cutoff,
                Medication.is_active == True,
                User.is_active == True,
            )
        )
        if senior_id is not None:
            query = query.filter(MedicationLog.senior_id == senior_id)

        overdue_doses = query.all()

        for log in overdue_doses:
            log.status = "missed"

            audit = MedicationStatusAudit(
                log_id=log.id,
                senior_id=log.senior_id,
                medication_id=log.medication_id,
                previous_status="pending",
                new_status="missed",
                changed_by_user_id=None,
                reason=f"Grace period of {grace} minute(s) exceeded without confirmation. Transitioned to missed.",
                timestamp=now,
            )
            db.add(audit)

        if overdue_doses:
            db.commit()

        return overdue_doses

    @classmethod
    def record_dose_status_transition(
        cls,
        db: Session,
        log: MedicationLog,
        new_status: str,
        user_id: Optional[int],
        notes: Optional[str] = None,
    ) -> MedicationLog:
        """Record an explicit user confirmation (taken/skipped/missed) with audit tracking."""
        old_status = log.status
        log.status = new_status
        log.notes = notes
        log.confirmed_by_user_id = user_id

        if new_status == "taken":
            log.taken_at = datetime.utcnow()
        else:
            log.taken_at = None

        audit = MedicationStatusAudit(
            log_id=log.id,
            senior_id=log.senior_id,
            medication_id=log.medication_id,
            previous_status=old_status,
            new_status=new_status,
            changed_by_user_id=user_id,
            reason=f"Status changed from {old_status} to {new_status}. Notes: {notes or 'None'}",
            timestamp=datetime.utcnow(),
        )
        db.add(audit)
        db.commit()
        db.refresh(log)
        return log

    @classmethod
    def evaluate_pending_doses(
        cls,
        db: Optional[Session] = None,
        as_of: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Comprehensive scheduler execution: generate doses, trigger reminders, and transition overdue doses.
        
        Fully idempotent: running multiple times consecutively causes no duplicate records or alerts.
        """
        now = as_of or datetime.utcnow()

        def _run(session: Session) -> Dict[str, Any]:
            # Step 1: Ensure today's doses exist for all active seniors
            created_doses = cls.generate_scheduled_doses(session, target_date=now.date())

            # Step 2: Trigger upcoming reminders within reminder window
            reminders = cls.identify_upcoming_reminders(session, as_of=now)

            # Step 3: Transition overdue doses past grace period to missed
            missed = cls.process_overdue_doses(session, as_of=now)

            total_active = (
                session.query(MedicationLog)
                .join(Medication, Medication.id == MedicationLog.medication_id)
                .filter(Medication.is_active == True)
                .count()
            )

            return {
                "evaluated": total_active,
                "alerts": len(reminders),
                "upcoming_reminders": len(reminders),
                "missed_marked": len(missed),
                "generated_doses": len(created_doses),
            }

        if db is not None:
            return _run(db)
        else:
            with SessionLocal() as session:
                return _run(session)

    @classmethod
    def get_audit_trail(
        cls,
        db: Session,
        senior_id: int,
        limit: int = 100,
    ) -> List[MedicationStatusAudit]:
        """Retrieve historical audit records for a senior's medication status changes."""
        return (
            db.query(MedicationStatusAudit)
            .filter(MedicationStatusAudit.senior_id == senior_id)
            .order_by(MedicationStatusAudit.timestamp.desc())
            .limit(limit)
            .all()
        )

    @classmethod
    def get_authorized_notification_recipients(
        cls,
        db: Session,
        senior: User,
        notification_type: str,
    ) -> List[Dict[str, str]]:
        """Retrieve authorized email recipients respecting patient consent, active status, and permissions."""
        recipients_map: Dict[str, Dict[str, str]] = {}

        # 1. Senior themselves (for upcoming medication and appointment reminders)
        if senior.email and notification_type in ("upcoming_medication", "doctor_appointment"):
            recipients_map[senior.email.lower()] = {
                "email": senior.email,
                "name": senior.full_name,
                "role": "senior",
            }

        # 2. Approved caregivers with relevant permissions
        links = (
            db.query(CaregiverLink)
            .filter(
                CaregiverLink.senior_id == senior.id,
                CaregiverLink.status == CaregiverLinkStatus.APPROVED,
                CaregiverLink.is_active == True,
            )
            .all()
        )

        for link in links:
            cg = link.caregiver
            if not cg or not cg.email or not cg.is_active:
                continue

            # Check permission boundaries per notification category
            if notification_type in ("upcoming_medication", "missed_dose"):
                if link.can_manage_medications or link.can_log_adherence:
                    recipients_map[cg.email.lower()] = {
                        "email": cg.email,
                        "name": cg.full_name,
                        "role": "caregiver",
                    }
            elif notification_type == "doctor_appointment":
                if link.can_manage_appointments:
                    recipients_map[cg.email.lower()] = {
                        "email": cg.email,
                        "name": cg.full_name,
                        "role": "caregiver",
                    }

        return list(recipients_map.values())

    @classmethod
    async def dispatch_upcoming_medication_notifications(
        cls,
        db: Session,
        as_of: Optional[datetime] = None,
        senior_id: Optional[int] = None,
    ) -> int:
        """Send email reminders for upcoming doses in reminder window without duplicate dispatches."""
        now = as_of or datetime.utcnow()
        window = settings.reminder_window_minutes
        window_end = now + timedelta(minutes=window)
        window_start = now - timedelta(minutes=settings.dose_grace_period_minutes)

        query = (
            db.query(MedicationLog)
            .join(Medication, Medication.id == MedicationLog.medication_id)
            .join(User, User.id == MedicationLog.senior_id)
            .filter(
                MedicationLog.status == "pending",
                MedicationLog.scheduled_for >= window_start,
                MedicationLog.scheduled_for <= window_end,
                Medication.is_active == True,
                User.is_active == True,
            )
        )
        if senior_id is not None:
            query = query.filter(MedicationLog.senior_id == senior_id)

        pending_logs = query.all()
        dispatched_count = 0

        for log in pending_logs:
            # Check if successfully notified already (idempotency & duplicate protection)
            already_sent = (
                db.query(NotificationLog)
                .filter(
                    NotificationLog.related_entity_id == log.id,
                    NotificationLog.notification_type == "upcoming_medication",
                    NotificationLog.status.in_(["sent", "simulated"]),
                )
                .first()
            )
            if already_sent:
                continue

            senior = log.senior
            med = log.medication
            senior_tz = get_safe_timezone(senior.profile.timezone if senior.profile else "UTC")
            local_time_str = log.scheduled_for.replace(tzinfo=timezone.utc).astimezone(senior_tz).strftime("%I:%M %p (%Z)")

            recipients = cls.get_authorized_notification_recipients(db, senior, "upcoming_medication")
            if not recipients:
                continue

            any_sent = False
            for rec in recipients:
                subject = f"[CareBridge] Medication Reminder: {med.name} for {senior.full_name}"
                body = (
                    f"Dear {rec['name']},\n\n"
                    f"This is an automated medication reminder from CareBridge AI.\n\n"
                    f"Patient: {senior.full_name}\n"
                    f"Medication: {med.name}\n"
                    f"Dosage: {med.dosage}\n"
                    f"Scheduled Time: {local_time_str}\n"
                    f"Instructions: {med.instructions or 'None'}\n"
                    f"Purpose: {med.purpose or 'Regimen maintenance'}\n\n"
                    f"Please confirm when this dose is taken using the CareBridge dashboard.\n\n"
                    f"Best regards,\nCareBridge AI Support"
                )

                sent = await NotificationService.send_email(
                    db=db,
                    recipient_email=rec["email"],
                    recipient_name=rec["name"],
                    subject=subject,
                    body_text=body,
                    notification_type="upcoming_medication",
                    senior_id=senior.id,
                    related_entity_id=log.id,
                )
                if sent:
                    any_sent = True

            if any_sent:
                log.reminder_sent = True
                log.reminder_sent_at = now
                dispatched_count += 1

        if dispatched_count > 0:
            db.commit()

        return dispatched_count

    @classmethod
    async def dispatch_missed_dose_notifications(
        cls,
        db: Session,
        as_of: Optional[datetime] = None,
        senior_id: Optional[int] = None,
    ) -> int:
        """Send urgent missed-dose alert emails to authorized caregivers after grace period expiry."""
        now = as_of or datetime.utcnow()

        query = (
            db.query(MedicationLog)
            .join(Medication, Medication.id == MedicationLog.medication_id)
            .join(User, User.id == MedicationLog.senior_id)
            .filter(
                MedicationLog.status == "missed",
                MedicationLog.missed_notification_sent == False,
                Medication.is_active == True,
                User.is_active == True,
            )
        )
        if senior_id is not None:
            query = query.filter(MedicationLog.senior_id == senior_id)

        missed_logs = query.all()
        dispatched_count = 0

        for log in missed_logs:
            # Check if missed notification already recorded
            already_sent = (
                db.query(NotificationLog)
                .filter(
                    NotificationLog.related_entity_id == log.id,
                    NotificationLog.notification_type == "missed_dose",
                    NotificationLog.status.in_(["sent", "simulated"]),
                )
                .first()
            )
            if already_sent:
                log.missed_notification_sent = True
                continue

            senior = log.senior
            med = log.medication
            senior_tz = get_safe_timezone(senior.profile.timezone if senior.profile else "UTC")
            local_time_str = log.scheduled_for.replace(tzinfo=timezone.utc).astimezone(senior_tz).strftime("%I:%M %p (%Z)")

            recipients = cls.get_authorized_notification_recipients(db, senior, "missed_dose")
            if not recipients:
                continue

            any_sent = False
            for rec in recipients:
                subject = f"[CareBridge URGENT] Missed Dose Alert: {med.name} for {senior.full_name}"
                body = (
                    f"Dear {rec['name']},\n\n"
                    f"CareBridge AI has detected an overdue medication dose that was NOT confirmed within the "
                    f"{settings.dose_grace_period_minutes}-minute grace period.\n\n"
                    f"Patient: {senior.full_name}\n"
                    f"Medication: {med.name} ({med.dosage})\n"
                    f"Scheduled For: {local_time_str}\n"
                    f"Status: MISSED\n\n"
                    f"Please contact {senior.full_name} or check the CareBridge portal to review adherence and provide support.\n\n"
                    f"CareBridge AI Monitoring System"
                )

                sent = await NotificationService.send_email(
                    db=db,
                    recipient_email=rec["email"],
                    recipient_name=rec["name"],
                    subject=subject,
                    body_text=body,
                    notification_type="missed_dose",
                    senior_id=senior.id,
                    related_entity_id=log.id,
                )
                if sent:
                    any_sent = True

            if any_sent:
                log.missed_notification_sent = True
                log.missed_notification_sent_at = now
                dispatched_count += 1

        if dispatched_count > 0:
            db.commit()

        return dispatched_count

    @classmethod
    async def dispatch_appointment_reminders(
        cls,
        db: Session,
        as_of: Optional[datetime] = None,
        senior_id: Optional[int] = None,
    ) -> int:
        """Send appointment reminders for upcoming doctor appointments within configured hours."""
        now = as_of or datetime.utcnow()
        window_end = now + timedelta(hours=settings.appointment_reminder_hours)

        query = (
            db.query(DoctorAppointment)
            .join(User, User.id == DoctorAppointment.senior_id)
            .filter(
                DoctorAppointment.status == "scheduled",
                DoctorAppointment.reminder_sent == False,
                DoctorAppointment.appointment_datetime >= now,
                DoctorAppointment.appointment_datetime <= window_end,
                User.is_active == True,
            )
        )
        if senior_id is not None:
            query = query.filter(DoctorAppointment.senior_id == senior_id)

        upcoming_appts = query.all()
        dispatched_count = 0

        for appt in upcoming_appts:
            already_sent = (
                db.query(NotificationLog)
                .filter(
                    NotificationLog.related_entity_id == appt.id,
                    NotificationLog.notification_type == "doctor_appointment",
                    NotificationLog.status.in_(["sent", "simulated"]),
                )
                .first()
            )
            if already_sent:
                appt.reminder_sent = True
                continue

            senior = appt.senior
            senior_tz = get_safe_timezone(senior.profile.timezone if senior.profile else "UTC")
            local_appt_str = appt.appointment_datetime.replace(tzinfo=timezone.utc).astimezone(senior_tz).strftime("%A, %B %d, %Y at %I:%M %p (%Z)")

            recipients = cls.get_authorized_notification_recipients(db, senior, "doctor_appointment")
            if not recipients:
                continue

            any_sent = False
            for rec in recipients:
                subject = f"[CareBridge] Appointment Reminder: Dr. {appt.doctor_name} for {senior.full_name}"
                body = (
                    f"Dear {rec['name']},\n\n"
                    f"This is an automated appointment reminder from CareBridge AI.\n\n"
                    f"Patient: {senior.full_name}\n"
                    f"Doctor: Dr. {appt.doctor_name} ({appt.specialty or 'General Practice'})\n"
                    f"Date & Time: {local_appt_str}\n"
                    f"Clinic: {appt.clinic_name or 'Not specified'}\n"
                    f"Address: {appt.clinic_address or 'Not specified'}\n"
                    f"Clinic Phone: {appt.contact_phone or 'Not specified'}\n"
                    f"Purpose: {appt.purpose or 'Routine appointment'}\n"
                    f"Instructions: {appt.preparation_instructions or 'None'}\n\n"
                    f"CareBridge AI Support"
                )

                sent = await NotificationService.send_email(
                    db=db,
                    recipient_email=rec["email"],
                    recipient_name=rec["name"],
                    subject=subject,
                    body_text=body,
                    notification_type="doctor_appointment",
                    senior_id=senior.id,
                    related_entity_id=appt.id,
                )
                if sent:
                    any_sent = True

            if any_sent:
                appt.reminder_sent = True
                appt.reminder_sent_at = now
                dispatched_count += 1

        if dispatched_count > 0:
            db.commit()

        return dispatched_count

    @classmethod
    async def dispatch_all_notifications(
        cls,
        db: Session,
        as_of: Optional[datetime] = None,
        senior_id: Optional[int] = None,
    ) -> Dict[str, int]:
        """Dispatch all due email notifications across medication reminders, missed doses, and doctor appointments."""
        med_reminders = await cls.dispatch_upcoming_medication_notifications(db=db, as_of=as_of, senior_id=senior_id)
        missed_alerts = await cls.dispatch_missed_dose_notifications(db=db, as_of=as_of, senior_id=senior_id)
        appt_reminders = await cls.dispatch_appointment_reminders(db=db, as_of=as_of, senior_id=senior_id)

        total = med_reminders + missed_alerts + appt_reminders
        return {
            "medication_reminders": med_reminders,
            "missed_dose_alerts": missed_alerts,
            "appointment_reminders": appt_reminders,
            "total": total,
        }
