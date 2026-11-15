from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User, UserRole, CaregiverLink, CaregiverLinkStatus, HealthcareProfile
from app.schemas import (
    UserRegister,
    SeniorRegister,
    EmailPasswordLogin,
    PasscodeLogin,
    TokenResponse,
    UserResponse,
    CaregiverLinkCreate,
    CaregiverLinkResponse,
)
from app.services.auth_service import AuthService, get_current_user, pin_security_manager

auth_router = APIRouter(prefix="/api/auth", tags=["Authentication & Roles"])


@auth_router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_user(req: UserRegister, db: Session = Depends(get_db)):
    """Register a new user (senior, caregiver, family member, or administrator)."""
    if req.role not in UserRole.ALL_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role '{req.role}'. Allowed roles: {UserRole.ALL_ROLES}",
        )

    if req.email:
        existing = db.query(User).filter(User.email == req.email).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A user with this email address already exists.",
            )

    hashed_pw = AuthService.hash_password(req.password)
    user = User(
        full_name=req.full_name,
        role=req.role,
        password_hash=hashed_pw,
        email=req.email,
        phone=req.phone,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Initialize empty healthcare profile if user is a senior
    if user.role == UserRole.SENIOR:
        profile = HealthcareProfile(user_id=user.id)
        db.add(profile)
        db.commit()

    return user


@auth_router.post("/register-senior", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_senior(req: SeniorRegister, db: Session = Depends(get_db)):
    """Simplified registration for an elderly person with numeric passcode."""
    if not req.passcode.isdigit():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Senior passcode must be numeric.",
        )

    hashed_passcode = AuthService.hash_password(req.passcode)
    senior = User(
        full_name=req.full_name,
        role=UserRole.SENIOR,
        password_hash=hashed_passcode,
        phone=req.phone,
        is_active=True,
    )
    db.add(senior)
    db.commit()
    db.refresh(senior)

    # Initialize healthcare profile
    profile = HealthcareProfile(
        user_id=senior.id,
        emergency_contact_name=req.emergency_contact_name,
        emergency_contact_phone=req.emergency_contact_phone,
    )
    db.add(profile)
    db.commit()

    return senior


@auth_router.post("/login", response_model=TokenResponse)
def login_email_password(
    req: EmailPasswordLogin,
    response: Response,
    db: Session = Depends(get_db),
):
    """Login with email and password (for caregivers, family, and administrators). Sets HttpOnly cookie."""
    user = db.query(User).filter(User.email == req.email, User.is_active == True).first()
    if not user or not AuthService.verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )

    token = AuthService.create_access_token({"sub": str(user.id), "role": user.role, "name": user.full_name})

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=(settings.environment == "production"),
        samesite="lax",
        max_age=7 * 86400,
        path="/",
    )

    return TokenResponse(
        access_token=token,
        user_id=user.id,
        full_name=user.full_name,
        role=user.role,
    )


@auth_router.post("/login-passcode", response_model=TokenResponse)
def login_passcode(
    req: PasscodeLogin,
    response: Response,
    db: Session = Depends(get_db),
):
    """Senior login using user ID and numeric passcode with brute-force lockout protection."""
    # 1. Check for temporary lockout
    pin_security_manager.check_lockout(req.user_id)

    # 2. Validate user and passcode
    user = db.query(User).filter(User.id == req.user_id, User.is_active == True).first()
    if not user or not AuthService.verify_password(req.passcode, user.password_hash):
        pin_security_manager.record_failure(req.user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Patient ID or Passcode.",
        )

    # 3. Reset failed attempts on success
    pin_security_manager.record_success(req.user_id)

    token = AuthService.create_access_token({"sub": str(user.id), "role": user.role, "name": user.full_name})

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=(settings.environment == "production"),
        samesite="lax",
        max_age=7 * 86400,
        path="/",
    )

    return TokenResponse(
        access_token=token,
        user_id=user.id,
        full_name=user.full_name,
        role=user.role,
    )


@auth_router.post("/logout")
def logout_api(response: Response):
    """Log out by clearing authentication cookies."""
    response.delete_cookie(key="access_token", path="/")
    return {"status": "logged_out", "message": "Successfully logged out."}


@auth_router.get("/logout")
def logout_redirect():
    """Clear session cookie and redirect to login page."""
    res = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    res.delete_cookie(key="access_token", path="/")
    return res


@auth_router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Get the profile of the currently logged-in user."""
    return current_user


@auth_router.post("/link-caregiver", response_model=CaregiverLinkResponse, status_code=status.HTTP_201_CREATED)
def link_caregiver(
    req: CaregiverLinkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Link a caregiver or family member with consent verification."""
    # Check senior existence
    senior = db.query(User).filter(User.id == req.senior_id, User.role == UserRole.SENIOR).first()
    if not senior:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Senior user not found.")

    # Check caregiver existence
    caregiver = db.query(User).filter(User.id == req.caregiver_id).first()
    if not caregiver:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caregiver user not found.")

    # Determine approval status:
    # If the senior themselves or an administrator initiates the link, it is immediately APPROVED.
    # If a caregiver initiates the request, it is placed in PENDING status until approved by the senior.
    is_direct_consent = (current_user.id == req.senior_id or current_user.role == UserRole.ADMIN)
    initial_status = CaregiverLinkStatus.APPROVED if is_direct_consent else CaregiverLinkStatus.PENDING
    is_active = is_direct_consent

    # Check for existing link
    existing = db.query(CaregiverLink).filter(
        CaregiverLink.senior_id == req.senior_id,
        CaregiverLink.caregiver_id == req.caregiver_id,
    ).first()

    if existing:
        existing.relationship_type = req.relationship_type
        existing.can_view_profile = req.can_view_profile
        existing.can_edit_profile = req.can_edit_profile
        existing.can_manage_medications = req.can_manage_medications
        existing.can_log_adherence = req.can_log_adherence
        existing.can_manage_appointments = req.can_manage_appointments
        existing.status = initial_status
        existing.is_active = is_active
        db.commit()
        db.refresh(existing)
        return existing

    link = CaregiverLink(
        senior_id=req.senior_id,
        caregiver_id=req.caregiver_id,
        relationship_type=req.relationship_type,
        can_view_profile=req.can_view_profile,
        can_edit_profile=req.can_edit_profile,
        can_manage_medications=req.can_manage_medications,
        can_log_adherence=req.can_log_adherence,
        can_manage_appointments=req.can_manage_appointments,
        status=initial_status,
        is_active=is_active,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


@auth_router.post("/approve-caregiver/{link_id}", response_model=CaregiverLinkResponse)
def approve_caregiver_link(
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Approve a pending caregiver access request (Patient or Admin consent)."""
    link = db.query(CaregiverLink).filter(CaregiverLink.id == link_id).first()
    if not link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caregiver link not found.")

    if current_user.id != link.senior_id and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the patient or system administrator can approve this caregiver access request.",
        )

    link.status = CaregiverLinkStatus.APPROVED
    link.is_active = True
    db.commit()
    db.refresh(link)
    return link


@auth_router.post("/reject-caregiver/{link_id}", response_model=CaregiverLinkResponse)
def reject_caregiver_link(
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reject a pending caregiver access request."""
    link = db.query(CaregiverLink).filter(CaregiverLink.id == link_id).first()
    if not link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caregiver link not found.")

    if current_user.id != link.senior_id and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the patient or system administrator can reject this caregiver access request.",
        )

    link.status = CaregiverLinkStatus.REJECTED
    link.is_active = False
    db.commit()
    db.refresh(link)
    return link


@auth_router.post("/revoke-caregiver/{link_id}", response_model=CaregiverLinkResponse)
def revoke_caregiver_access(
    link_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Immediately revoke an approved caregiver or family member's access to the patient's records."""
    link = db.query(CaregiverLink).filter(CaregiverLink.id == link_id).first()
    if not link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caregiver link not found.")

    if current_user.id != link.senior_id and current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the patient or system administrator can revoke caregiver access.",
        )

    link.status = CaregiverLinkStatus.REVOKED
    link.is_active = False
    db.commit()
    db.refresh(link)
    return link


@auth_router.get("/my-seniors", response_model=List[CaregiverLinkResponse])
def get_my_seniors(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all seniors linked to the currently logged-in caregiver (approved only)."""
    links = db.query(CaregiverLink).filter(
        CaregiverLink.caregiver_id == current_user.id,
        CaregiverLink.status == CaregiverLinkStatus.APPROVED,
        CaregiverLink.is_active == True,
    ).all()
    return links


@auth_router.get("/my-caregivers", response_model=List[CaregiverLinkResponse])
def get_my_caregivers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all caregivers and family members linked to the currently logged-in senior."""
    links = db.query(CaregiverLink).filter(
        CaregiverLink.senior_id == current_user.id,
    ).all()
    return links
