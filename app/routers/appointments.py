from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DoctorAppointment, User
from app.schemas import AppointmentCreate, AppointmentUpdate, AppointmentResponse
from app.services.auth_service import get_current_user, verify_senior_access

appointments_router = APIRouter(prefix="/api/appointments", tags=["Doctor Appointments"])


@appointments_router.post("", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED)
def create_appointment(
    req: AppointmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Schedule a new doctor appointment for a senior."""
    verify_senior_access(db, current_user, req.senior_id, required_permission="can_manage_appointments")

    appointment = DoctorAppointment(
        senior_id=req.senior_id,
        created_by_user_id=current_user.id,
        doctor_name=req.doctor_name,
        specialty=req.specialty,
        clinic_name=req.clinic_name,
        clinic_address=req.clinic_address,
        contact_phone=req.contact_phone,
        appointment_datetime=req.appointment_datetime,
        purpose=req.purpose,
        preparation_instructions=req.preparation_instructions,
        status=req.status or "scheduled",
    )
    db.add(appointment)
    db.commit()
    db.refresh(appointment)
    return appointment


@appointments_router.get("/senior/{senior_id}", response_model=List[AppointmentResponse])
def get_senior_appointments(
    senior_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all doctor appointments for a senior."""
    verify_senior_access(db, current_user, senior_id, required_permission="can_manage_appointments")

    appointments = (
        db.query(DoctorAppointment)
        .filter(DoctorAppointment.senior_id == senior_id)
        .order_by(DoctorAppointment.appointment_datetime.asc())
        .all()
    )
    return appointments


@appointments_router.get("/senior/{senior_id}/upcoming", response_model=List[AppointmentResponse])
def get_upcoming_appointments(
    senior_id: int,
    days_ahead: int = 30,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List upcoming scheduled appointments for a senior within a given time window."""
    verify_senior_access(db, current_user, senior_id, required_permission="can_manage_appointments")

    now = datetime.utcnow()
    cutoff = now + timedelta(days=days_ahead)

    appointments = (
        db.query(DoctorAppointment)
        .filter(
            DoctorAppointment.senior_id == senior_id,
            DoctorAppointment.appointment_datetime >= now,
            DoctorAppointment.appointment_datetime <= cutoff,
            DoctorAppointment.status == "scheduled",
        )
        .order_by(DoctorAppointment.appointment_datetime.asc())
        .all()
    )
    return appointments


@appointments_router.get("/{appointment_id}", response_model=AppointmentResponse)
def get_appointment_details(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get details for a single doctor appointment."""
    app = db.query(DoctorAppointment).filter(DoctorAppointment.id == appointment_id).first()
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found.")

    verify_senior_access(db, current_user, app.senior_id, required_permission="can_manage_appointments")
    return app


@appointments_router.put("/{appointment_id}", response_model=AppointmentResponse)
def update_appointment(
    appointment_id: int,
    req: AppointmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update details or status of a doctor appointment."""
    app = db.query(DoctorAppointment).filter(DoctorAppointment.id == appointment_id).first()
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found.")

    verify_senior_access(db, current_user, app.senior_id, required_permission="can_manage_appointments")

    update_data = req.model_dump(exclude_unset=True)
    for field, val in update_data.items():
        setattr(app, field, val)

    db.commit()
    db.refresh(app)
    return app


@appointments_router.post("/{appointment_id}/cancel", response_model=AppointmentResponse)
def cancel_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cancel a scheduled appointment."""
    app = db.query(DoctorAppointment).filter(DoctorAppointment.id == appointment_id).first()
    if not app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found.")

    verify_senior_access(db, current_user, app.senior_id, required_permission="can_manage_appointments")
    app.status = "cancelled"
    db.commit()
    db.refresh(app)
    return app
