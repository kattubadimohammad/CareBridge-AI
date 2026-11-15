from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserRole, HealthcareProfile
from app.schemas import HealthcareProfileResponse, HealthcareProfileUpdate
from app.services.auth_service import get_current_user, verify_senior_access

profile_router = APIRouter(prefix="/api/profile", tags=["Healthcare Profile"])


@profile_router.get("/me", response_model=HealthcareProfileResponse)
def get_my_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve the current user's healthcare profile."""
    profile = db.query(HealthcareProfile).filter(HealthcareProfile.user_id == current_user.id).first()
    if not profile:
        profile = HealthcareProfile(user_id=current_user.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


@profile_router.put("/me", response_model=HealthcareProfileResponse)
def update_my_profile(
    req: HealthcareProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the current user's healthcare profile."""
    profile = db.query(HealthcareProfile).filter(HealthcareProfile.user_id == current_user.id).first()
    if not profile:
        profile = HealthcareProfile(user_id=current_user.id)
        db.add(profile)

    update_data = req.model_dump(exclude_unset=True)
    for field, val in update_data.items():
        setattr(profile, field, val)

    db.commit()
    db.refresh(profile)
    return profile


@profile_router.get("/{senior_id}", response_model=HealthcareProfileResponse)
def get_senior_profile(
    senior_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve an elderly person's healthcare profile with permission checks."""
    verify_senior_access(db, current_user, senior_id, required_permission="can_view_profile")
    profile = db.query(HealthcareProfile).filter(HealthcareProfile.user_id == senior_id).first()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Healthcare profile not found.")
    return profile


@profile_router.put("/{senior_id}", response_model=HealthcareProfileResponse)
def update_senior_profile(
    senior_id: int,
    req: HealthcareProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an elderly person's healthcare profile with permission checks."""
    verify_senior_access(db, current_user, senior_id, required_permission="can_edit_profile")
    profile = db.query(HealthcareProfile).filter(HealthcareProfile.user_id == senior_id).first()
    if not profile:
        profile = HealthcareProfile(user_id=senior_id)
        db.add(profile)

    update_data = req.model_dump(exclude_unset=True)
    for field, val in update_data.items():
        setattr(profile, field, val)

    db.commit()
    db.refresh(profile)
    return profile
