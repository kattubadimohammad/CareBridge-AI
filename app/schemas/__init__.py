from datetime import datetime, date
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, EmailStr, Field


# --- Health & System ---
class HealthResponse(BaseModel):
    status: str
    app_name: str
    environment: str
    timestamp: datetime


class SchedulerTriggerResponse(BaseModel):
    status: str
    evaluated_count: int
    alerts_triggered: int
    missed_marked_count: int = 0
    upcoming_reminders_count: int = 0
    notifications_sent_count: int = 0
    timestamp: datetime


class NotificationLogResponse(BaseModel):
    id: int
    recipient_email: str
    recipient_name: Optional[str] = None
    senior_id: Optional[int] = None
    notification_type: str
    subject: str
    body_text: str
    status: str
    error_message: Optional[str] = None
    related_entity_id: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Authentication & Users ---
class UserBase(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=120)
    role: str = Field(default="senior")
    email: Optional[EmailStr] = None
    phone: Optional[str] = None


class UserRegister(UserBase):
    password: str = Field(..., min_length=4, description="Password for caregivers/family or numeric passcode for seniors")


class SeniorRegister(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=120)
    passcode: str = Field(..., min_length=4, max_length=8, description="Senior numeric 4-8 digit passcode")
    phone: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None


class PasscodeLogin(BaseModel):
    user_id: Optional[int] = None
    passcode: str


class EmailPasswordLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    full_name: str
    role: str


class UserResponse(UserBase):
    id: int
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Caregiver Linking ---
class CaregiverLinkCreate(BaseModel):
    senior_id: int
    caregiver_id: int
    relationship_type: str = "primary_caregiver"
    can_view_profile: bool = True
    can_edit_profile: bool = False
    can_manage_medications: bool = True
    can_log_adherence: bool = True
    can_manage_appointments: bool = True


class CaregiverLinkResponse(BaseModel):
    id: int
    senior_id: int
    caregiver_id: int
    relationship_type: str
    can_view_profile: bool
    can_edit_profile: bool
    can_manage_medications: bool
    can_log_adherence: bool
    can_manage_appointments: bool
    status: str = "pending"
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Shared Healthcare Profile ---
class HealthcareProfileBase(BaseModel):
    date_of_birth: Optional[date] = None
    blood_group: Optional[str] = None
    known_allergies: Optional[str] = None
    chronic_conditions: Optional[str] = None
    dietary_notes: Optional[str] = None
    mobility_notes: Optional[str] = None
    primary_physician_name: Optional[str] = None
    primary_physician_phone: Optional[str] = None
    primary_physician_clinic: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relation: Optional[str] = None
    timezone: str = "UTC"


class HealthcareProfileCreate(HealthcareProfileBase):
    user_id: int


class HealthcareProfileUpdate(HealthcareProfileBase):
    pass


class HealthcareProfileResponse(HealthcareProfileBase):
    id: int
    user_id: int
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# --- Medication & Schedules ---
class MedicationScheduleBase(BaseModel):
    scheduled_time: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="24h format HH:MM, e.g. 08:30")
    days_of_week: str = "everyday"
    timezone: str = "UTC"


class MedicationScheduleResponse(MedicationScheduleBase):
    id: int
    medication_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MedicationBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    dosage: str = Field(..., min_length=1, max_length=80)
    instructions: Optional[str] = None
    purpose: Optional[str] = None
    prescribed_by: Optional[str] = None
    is_active: bool = True


class MedicationCreate(MedicationBase):
    schedules: List[MedicationScheduleBase] = []


class MedicationUpdate(BaseModel):
    name: Optional[str] = None
    dosage: Optional[str] = None
    instructions: Optional[str] = None
    purpose: Optional[str] = None
    prescribed_by: Optional[str] = None
    is_active: Optional[bool] = None


class MedicationResponse(MedicationBase):
    id: int
    user_id: int
    created_at: datetime
    schedules: List[MedicationScheduleResponse] = []

    model_config = ConfigDict(from_attributes=True)


# --- Adherence Tracking ---
class DoseActionRequest(BaseModel):
    action: str = Field(..., pattern="^(taken|skipped|missed)$")
    notes: Optional[str] = None


class DoseLogResponse(BaseModel):
    id: int
    medication_id: int
    medication_name: Optional[str] = None
    dosage: Optional[str] = None
    senior_id: int
    scheduled_for: datetime
    status: str
    taken_at: Optional[datetime] = None
    reminder_sent: bool = False
    reminder_sent_at: Optional[datetime] = None
    confirmed_by_user_id: Optional[int] = None
    confirmed_by_name: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MedicationStatusAuditResponse(BaseModel):
    id: int
    log_id: int
    senior_id: int
    medication_id: int
    previous_status: Optional[str] = None
    new_status: str
    changed_by_user_id: Optional[int] = None
    reason: Optional[str] = None
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)


class AdherenceStats(BaseModel):
    total_doses: int
    taken_count: int
    missed_count: int
    skipped_count: int
    pending_count: int
    adherence_rate_percent: float


# --- Doctor Appointments ---
class AppointmentBase(BaseModel):
    doctor_name: str = Field(..., min_length=2, max_length=120)
    specialty: Optional[str] = None
    clinic_name: Optional[str] = None
    clinic_address: Optional[str] = None
    contact_phone: Optional[str] = None
    appointment_datetime: datetime
    purpose: Optional[str] = None
    preparation_instructions: Optional[str] = None
    status: str = "scheduled"


class AppointmentCreate(AppointmentBase):
    senior_id: int


class AppointmentUpdate(BaseModel):
    doctor_name: Optional[str] = None
    specialty: Optional[str] = None
    clinic_name: Optional[str] = None
    clinic_address: Optional[str] = None
    contact_phone: Optional[str] = None
    appointment_datetime: Optional[datetime] = None
    purpose: Optional[str] = None
    preparation_instructions: Optional[str] = None
    status: Optional[str] = None


class AppointmentResponse(AppointmentBase):
    id: int
    senior_id: int
    created_by_user_id: int
    reminder_sent: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
