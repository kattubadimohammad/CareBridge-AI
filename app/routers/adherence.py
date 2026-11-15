from datetime import datetime, date, time, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Medication, MedicationSchedule, MedicationLog, User, MedicationStatusAudit
from app.schemas import DoseActionRequest, DoseLogResponse, AdherenceStats, MedicationStatusAuditResponse
from app.services.auth_service import get_current_user, verify_senior_access
from app.services.scheduler_service import SchedulerService, get_safe_timezone

adherence_router = APIRouter(prefix="/api/adherence", tags=["Adherence Tracking"])


def _format_dose_log_response(
    log: MedicationLog,
    db: Session,
    target_tz: Optional[ZoneInfo] = None,
) -> DoseLogResponse:
    if target_tz is None:
        senior = (
            log.senior
            if hasattr(log, "senior") and log.senior
            else db.query(User).filter(User.id == log.senior_id).first()
        )
        tz_name = (
            senior.profile.timezone
            if (senior and senior.profile and senior.profile.timezone)
            else "UTC"
        )
        target_tz = get_safe_timezone(tz_name)

    # Convert UTC scheduled_for to senior's target timezone
    scheduled_for = log.scheduled_for
    if scheduled_for:
        if scheduled_for.tzinfo is None:
            scheduled_for = scheduled_for.replace(tzinfo=timezone.utc)
        scheduled_for = scheduled_for.astimezone(target_tz)

    # Convert UTC taken_at to senior's target timezone if present
    taken_at = log.taken_at
    if taken_at:
        if taken_at.tzinfo is None:
            taken_at = taken_at.replace(tzinfo=timezone.utc)
        taken_at = taken_at.astimezone(target_tz)

    med = log.medication
    confirmed_by_user = (
        db.query(User).filter(User.id == log.confirmed_by_user_id).first()
        if log.confirmed_by_user_id
        else None
    )
    return DoseLogResponse(
        id=log.id,
        medication_id=log.medication_id,
        medication_name=med.name if med else "Unknown",
        dosage=med.dosage if med else "",
        senior_id=log.senior_id,
        scheduled_for=scheduled_for,
        status=log.status,
        taken_at=taken_at,
        reminder_sent=log.reminder_sent,
        reminder_sent_at=log.reminder_sent_at,
        confirmed_by_user_id=log.confirmed_by_user_id,
        confirmed_by_name=confirmed_by_user.full_name if confirmed_by_user else None,
        notes=log.notes,
        created_at=log.created_at,
    )


@adherence_router.get("/senior/{senior_id}/today", response_model=List[DoseLogResponse])
def get_or_generate_today_doses(
    senior_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve today's medication doses for a senior, initializing pending doses without duplicates."""
    verify_senior_access(db, current_user, senior_id, required_permission="can_log_adherence")

    senior = db.query(User).filter(User.id == senior_id).first()
    tz_name = senior.profile.timezone if (senior and senior.profile and senior.profile.timezone) else "UTC"
    senior_tz = get_safe_timezone(tz_name)
    local_today = datetime.now(senior_tz).date()

    # Generate any missing scheduled doses for senior's local today
    SchedulerService.generate_scheduled_doses(db, target_date=local_today, senior_id=senior_id)

    # Compute UTC bounds corresponding to senior's local start and end of day
    local_start = datetime.combine(local_today, time.min, tzinfo=senior_tz)
    local_end = datetime.combine(local_today, time.max, tzinfo=senior_tz)
    utc_start = local_start.astimezone(timezone.utc).replace(tzinfo=None)
    utc_end = local_end.astimezone(timezone.utc).replace(tzinfo=None)

    # Query all doses for today within the UTC window
    today_logs = (
        db.query(MedicationLog)
        .filter(
            MedicationLog.senior_id == senior_id,
            MedicationLog.scheduled_for >= utc_start,
            MedicationLog.scheduled_for <= utc_end,
        )
        .order_by(MedicationLog.scheduled_for.asc())
        .all()
    )

    return [_format_dose_log_response(log, db, target_tz=senior_tz) for log in today_logs]


@adherence_router.post("/logs/{log_id}/confirm", response_model=DoseLogResponse)
def confirm_dose_action(
    log_id: int,
    req: DoseActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Record dose status (taken/skipped/missed) and record who confirmed the action with audit tracking."""
    log = db.query(MedicationLog).filter(MedicationLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dose log entry not found.")

    verify_senior_access(db, current_user, log.senior_id, required_permission="can_log_adherence")

    SchedulerService.record_dose_status_transition(
        db=db,
        log=log,
        new_status=req.action,
        user_id=current_user.id,
        notes=req.notes,
    )
    return _format_dose_log_response(log, db)


@adherence_router.get("/senior/{senior_id}/history", response_model=List[DoseLogResponse])
def get_adherence_history(
    senior_id: int,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List historical dose logs for a senior with audit information."""
    verify_senior_access(db, current_user, senior_id, required_permission="can_log_adherence")

    senior = db.query(User).filter(User.id == senior_id).first()
    tz_name = senior.profile.timezone if (senior and senior.profile and senior.profile.timezone) else "UTC"
    senior_tz = get_safe_timezone(tz_name)

    logs = (
        db.query(MedicationLog)
        .filter(MedicationLog.senior_id == senior_id)
        .order_by(MedicationLog.scheduled_for.desc())
        .limit(limit)
        .all()
    )

    return [_format_dose_log_response(log, db, target_tz=senior_tz) for log in logs]


@adherence_router.get("/senior/{senior_id}/stats", response_model=AdherenceStats)
def get_adherence_stats(
    senior_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Calculate adherence statistics and rate for an elderly person."""
    verify_senior_access(db, current_user, senior_id, required_permission="can_log_adherence")

    logs = db.query(MedicationLog).filter(MedicationLog.senior_id == senior_id).all()
    total = len(logs)
    taken = sum(1 for log in logs if log.status == "taken")
    missed = sum(1 for log in logs if log.status == "missed")
    skipped = sum(1 for log in logs if log.status == "skipped")
    pending = sum(1 for log in logs if log.status == "pending")

    # Rate based on completed schedule instances
    decided = taken + missed + skipped
    rate = (taken / decided * 100.0) if decided > 0 else 100.0

    return AdherenceStats(
        total_doses=total,
        taken_count=taken,
        missed_count=missed,
        skipped_count=skipped,
        pending_count=pending,
        adherence_rate_percent=round(rate, 1),
    )


@adherence_router.get("/senior/{senior_id}/audits", response_model=List[MedicationStatusAuditResponse])
def get_senior_dose_audits(
    senior_id: int,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve full audit trail for an elderly person's medication status changes and alerts."""
    verify_senior_access(db, current_user, senior_id, required_permission="can_log_adherence")
    return SchedulerService.get_audit_trail(db, senior_id=senior_id, limit=limit)
