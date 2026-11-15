from datetime import datetime, date, time
from typing import Optional
from fastapi import APIRouter, Header, HTTPException, Request, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User, UserRole, HealthcareProfile, Medication, MedicationLog, DoctorAppointment, CaregiverLink
from app.schemas import HealthResponse, SchedulerTriggerResponse
from app.services import SchedulerService
from app.services.auth_service import get_optional_current_user
from app.routers.adherence import get_or_generate_today_doses, get_adherence_stats

# Setup Jinja2 templates for accessible HTML UI
templates = Jinja2Templates(directory="app/templates")

# Web router for server-rendered HTML pages
web_router = APIRouter(tags=["Web Pages"])

# API router for health & system operations
api_router = APIRouter(prefix="/api", tags=["API"])


@web_router.get("/", response_class=HTMLResponse)
async def index_view(request: Request, db: Session = Depends(get_db)):
    """Render homepage with dynamic session awareness."""
    current_user = get_optional_current_user(request, db)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "app_name": settings.app_name,
            "environment": settings.environment,
            "current_user": current_user,
        },
    )


@web_router.get("/senior", response_class=HTMLResponse)
async def senior_dashboard_view(
    request: Request,
    senior_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Render senior-friendly dashboard populated with real patient data."""
    current_user = get_optional_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/login?next=/senior", status_code=status.HTTP_302_FOUND)

    # If logged-in user is a senior, target their own profile
    if current_user.role == UserRole.SENIOR:
        target_senior = current_user
    else:
        # Caregiver viewing senior
        if senior_id:
            target_senior = db.query(User).filter(User.id == senior_id, User.role == UserRole.SENIOR).first()
        else:
            first_link = db.query(CaregiverLink).filter(
                CaregiverLink.caregiver_id == current_user.id,
                CaregiverLink.is_active == True,
            ).first()
            target_senior = first_link.senior if first_link else None

    if not target_senior:
        return templates.TemplateResponse(
            request=request,
            name="senior_dashboard.html",
            context={
                "app_name": settings.app_name,
                "current_user": current_user,
                "senior": None,
                "profile": None,
                "doses": [],
                "appointments": [],
                "error_message": "No elderly care recipient profile found.",
            },
        )

    # Fetch real profile, real today doses, and real upcoming appointments
    profile = db.query(HealthcareProfile).filter(HealthcareProfile.user_id == target_senior.id).first()
    today_doses = get_or_generate_today_doses(target_senior.id, db, current_user)
    
    now = datetime.utcnow()
    upcoming_appointments = (
        db.query(DoctorAppointment)
        .filter(
            DoctorAppointment.senior_id == target_senior.id,
            DoctorAppointment.appointment_datetime >= now,
            DoctorAppointment.status == "scheduled",
        )
        .order_by(DoctorAppointment.appointment_datetime.asc())
        .limit(3)
        .all()
    )

    return templates.TemplateResponse(
        request=request,
        name="senior_dashboard.html",
        context={
            "app_name": settings.app_name,
            "environment": settings.environment,
            "current_user": current_user,
            "senior": target_senior,
            "profile": profile,
            "doses": today_doses,
            "appointments": upcoming_appointments,
        },
    )


@web_router.get("/caregiver", response_class=HTMLResponse)
async def caregiver_portal_view(
    request: Request,
    senior_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Render caregiver oversight portal populated with real linked senior records."""
    current_user = get_optional_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/login?next=/caregiver", status_code=status.HTTP_302_FOUND)

    # If senior visits caregiver portal, direct them to their senior mode
    if current_user.role == UserRole.SENIOR:
        return RedirectResponse(url="/senior", status_code=status.HTTP_302_FOUND)

    # Query all active seniors linked to this caregiver
    links = db.query(CaregiverLink).filter(
        CaregiverLink.caregiver_id == current_user.id,
        CaregiverLink.is_active == True,
    ).all()

    selected_senior = None
    if senior_id:
        link_match = next((l for l in links if l.senior_id == senior_id), None)
        if link_match:
            selected_senior = link_match.senior
    elif links:
        selected_senior = links[0].senior

    # Default empty container states if no senior is linked yet
    profile = None
    medications = []
    stats = None
    appointments = []

    if selected_senior:
        profile = db.query(HealthcareProfile).filter(HealthcareProfile.user_id == selected_senior.id).first()
        medications = db.query(Medication).filter(Medication.user_id == selected_senior.id).all()
        stats = get_adherence_stats(selected_senior.id, db, current_user)
        appointments = (
            db.query(DoctorAppointment)
            .filter(DoctorAppointment.senior_id == selected_senior.id)
            .order_by(DoctorAppointment.appointment_datetime.asc())
            .all()
        )

    return templates.TemplateResponse(
        request=request,
        name="caregiver_portal.html",
        context={
            "app_name": settings.app_name,
            "environment": settings.environment,
            "current_user": current_user,
            "links": links,
            "selected_senior": selected_senior,
            "profile": profile,
            "medications": medications,
            "stats": stats,
            "appointments": appointments,
        },
    )


@web_router.get("/login", response_class=HTMLResponse)
async def login_view(request: Request, db: Session = Depends(get_db)):
    """Render accessible login view; redirect if session active."""
    current_user = get_optional_current_user(request, db)
    if current_user:
        if current_user.role == UserRole.SENIOR:
            return RedirectResponse(url="/senior", status_code=status.HTTP_302_FOUND)
        return RedirectResponse(url="/caregiver", status_code=status.HTTP_302_FOUND)

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "app_name": settings.app_name,
            "environment": settings.environment,
        },
    )


@web_router.get("/logout")
def logout_view():
    """Clear access token cookie and redirect to login."""
    res = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    res.delete_cookie(key="access_token", path="/")
    return res


@web_router.get("/health", response_model=HealthResponse)
@api_router.get("/health", response_model=HealthResponse)
async def health_check():
    """System health check endpoint (available at /api/health and /health)."""
    return HealthResponse(
        status="healthy",
        app_name=settings.app_name,
        environment=settings.environment,
        timestamp=datetime.utcnow(),
    )


@api_router.post("/cron/check-reminders", response_model=SchedulerTriggerResponse)
async def run_reminder_cron(
    x_scheduler_token: str = Header(None, alias="X-Scheduler-Token"),
    db: Session = Depends(get_db),
):
    """Cloud Scheduler endpoint to evaluate medication schedules and trigger alerts."""
    if settings.environment != "development" and x_scheduler_token != settings.cron_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing scheduler authorization token.",
        )

    eval_result = SchedulerService.evaluate_pending_doses(db=db)
    dispatch_result = await SchedulerService.dispatch_all_notifications(db=db)

    return SchedulerTriggerResponse(
        status="success",
        evaluated_count=eval_result["evaluated"],
        alerts_triggered=eval_result["alerts"],
        missed_marked_count=eval_result.get("missed_marked", 0),
        upcoming_reminders_count=eval_result.get("upcoming_reminders", 0),
        notifications_sent_count=dispatch_result.get("total", 0),
        timestamp=datetime.utcnow(),
    )
