from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Medication, MedicationSchedule, User
from app.schemas import (
    MedicationCreate,
    MedicationUpdate,
    MedicationResponse,
    MedicationScheduleBase,
    MedicationScheduleResponse,
)
from app.services.auth_service import get_current_user, verify_senior_access

medications_router = APIRouter(prefix="/api/medications", tags=["Medications"])


@medications_router.post("", response_model=MedicationResponse, status_code=status.HTTP_201_CREATED)
def create_medication(
    req: MedicationCreate,
    senior_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a new medication with schedules for a senior or current user."""
    target_senior_id = senior_id if senior_id is not None else current_user.id
    verify_senior_access(db, current_user, target_senior_id, required_permission="can_manage_medications")

    med = Medication(
        user_id=target_senior_id,
        name=req.name,
        dosage=req.dosage,
        instructions=req.instructions,
        purpose=req.purpose,
        prescribed_by=req.prescribed_by,
        is_active=req.is_active,
    )
    db.add(med)
    db.commit()
    db.refresh(med)

    for s in req.schedules:
        schedule = MedicationSchedule(
            medication_id=med.id,
            scheduled_time=s.scheduled_time,
            days_of_week=s.days_of_week,
            timezone=s.timezone,
        )
        db.add(schedule)

    db.commit()
    db.refresh(med)
    return med


@medications_router.get("/senior/{senior_id}", response_model=List[MedicationResponse])
def get_senior_medications(
    senior_id: int,
    active_only: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """View all medications and dosage schedules for an elderly person."""
    verify_senior_access(db, current_user, senior_id, required_permission="can_manage_medications")

    query = db.query(Medication).filter(Medication.user_id == senior_id)
    if active_only:
        query = query.filter(Medication.is_active == True)
    return query.all()


@medications_router.get("/{med_id}", response_model=MedicationResponse)
def get_medication_details(
    med_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get single medication details with its schedules."""
    med = db.query(Medication).filter(Medication.id == med_id).first()
    if not med:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medication not found.")

    verify_senior_access(db, current_user, med.user_id, required_permission="can_manage_medications")
    return med


@medications_router.put("/{med_id}", response_model=MedicationResponse)
def update_medication(
    med_id: int,
    req: MedicationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Edit medication details and instructions."""
    med = db.query(Medication).filter(Medication.id == med_id).first()
    if not med:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medication not found.")

    verify_senior_access(db, current_user, med.user_id, required_permission="can_manage_medications")

    update_data = req.model_dump(exclude_unset=True)
    for field, val in update_data.items():
        setattr(med, field, val)

    db.commit()
    db.refresh(med)
    return med


@medications_router.post("/{med_id}/deactivate", response_model=MedicationResponse)
def deactivate_medication(
    med_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Safely deactivate a discontinued or completed medication."""
    med = db.query(Medication).filter(Medication.id == med_id).first()
    if not med:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medication not found.")

    verify_senior_access(db, current_user, med.user_id, required_permission="can_manage_medications")
    med.is_active = False
    db.commit()
    db.refresh(med)
    return med


@medications_router.post("/{med_id}/schedules", response_model=MedicationScheduleResponse, status_code=status.HTTP_201_CREATED)
def add_medication_schedule(
    med_id: int,
    req: MedicationScheduleBase,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a new scheduled dosage time to a medication."""
    med = db.query(Medication).filter(Medication.id == med_id).first()
    if not med:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medication not found.")

    verify_senior_access(db, current_user, med.user_id, required_permission="can_manage_medications")

    schedule = MedicationSchedule(
        medication_id=med.id,
        scheduled_time=req.scheduled_time,
        days_of_week=req.days_of_week,
        timezone=req.timezone,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule
