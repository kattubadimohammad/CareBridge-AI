import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    Date,
    ForeignKey,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from app.database import Base


class UserRole:
    SENIOR = "senior"
    CAREGIVER = "caregiver"
    FAMILY = "family"
    ADMIN = "admin"

    ALL_ROLES = [SENIOR, CAREGIVER, FAMILY, ADMIN]


class CaregiverLinkStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"


class User(Base):
    """User account model supporting seniors, caregivers, family members, and admins."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(120), nullable=False)
    role = Column(String(30), nullable=False, default=UserRole.SENIOR)
    # Hashed passcode (numeric for seniors) or secure password for caregivers/family
    password_hash = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=True)
    phone = Column(String(50), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    profile = relationship("HealthcareProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    medications = relationship("Medication", back_populates="patient", cascade="all, delete-orphan")
    appointments = relationship("DoctorAppointment", foreign_keys="DoctorAppointment.senior_id", back_populates="senior", cascade="all, delete-orphan")
    
    # Caregiver links where this user is the senior/patient
    caregiver_links_as_senior = relationship(
        "CaregiverLink",
        foreign_keys="CaregiverLink.senior_id",
        back_populates="senior",
        cascade="all, delete-orphan",
    )
    # Caregiver links where this user is the caregiver/family
    caregiver_links_as_caregiver = relationship(
        "CaregiverLink",
        foreign_keys="CaregiverLink.caregiver_id",
        back_populates="caregiver",
        cascade="all, delete-orphan",
    )


class CaregiverLink(Base):
    """Authorized association linking a caregiver or family member to an elderly person."""

    __tablename__ = "caregiver_links"

    id = Column(Integer, primary_key=True, index=True)
    senior_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    caregiver_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    relationship_type = Column(String(50), default="primary_caregiver")  # e.g., nurse, daughter, son, physician
    can_view_profile = Column(Boolean, default=True)
    can_edit_profile = Column(Boolean, default=False)
    can_manage_medications = Column(Boolean, default=True)
    can_log_adherence = Column(Boolean, default=True)
    can_manage_appointments = Column(Boolean, default=True)
    status = Column(String(30), default=CaregiverLinkStatus.PENDING, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("senior_id", "caregiver_id", name="uq_senior_caregiver"),
    )

    senior = relationship("User", foreign_keys=[senior_id], back_populates="caregiver_links_as_senior")
    caregiver = relationship("User", foreign_keys=[caregiver_id], back_populates="caregiver_links_as_caregiver")


class HealthcareProfile(Base):
    """Shared elderly healthcare profile containing emergency contacts and health info."""

    __tablename__ = "healthcare_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    date_of_birth = Column(Date, nullable=True)
    blood_group = Column(String(10), nullable=True)
    known_allergies = Column(Text, nullable=True)          # e.g., "Penicillin, Peanuts"
    chronic_conditions = Column(Text, nullable=True)       # e.g., "Hypertension, Mild Arthritis"
    dietary_notes = Column(Text, nullable=True)            # e.g., "Low sodium diet"
    mobility_notes = Column(Text, nullable=True)           # e.g., "Uses walking stick"
    primary_physician_name = Column(String(120), nullable=True)
    primary_physician_phone = Column(String(50), nullable=True)
    primary_physician_clinic = Column(String(200), nullable=True)
    emergency_contact_name = Column(String(120), nullable=True)
    emergency_contact_phone = Column(String(50), nullable=True)
    emergency_contact_relation = Column(String(50), nullable=True)
    timezone = Column(String(50), default="UTC", nullable=False)  # Senior's home timezone (e.g., America/New_York)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = relationship("User", back_populates="profile")


class Medication(Base):
    """Medication profile associated with a patient."""

    __tablename__ = "medications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(150), nullable=False)
    dosage = Column(String(80), nullable=False)            # e.g., "10mg", "1 tablet"
    instructions = Column(Text, nullable=True)             # e.g., "Take with food"
    purpose = Column(String(200), nullable=True)           # e.g., "Blood pressure regulation"
    prescribed_by = Column(String(120), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    patient = relationship("User", back_populates="medications")
    schedules = relationship("MedicationSchedule", back_populates="medication", cascade="all, delete-orphan")
    logs = relationship("MedicationLog", back_populates="medication", cascade="all, delete-orphan")


class MedicationSchedule(Base):
    """Scheduled dosage timings for a medication with timezone awareness."""

    __tablename__ = "medication_schedules"

    id = Column(Integer, primary_key=True, index=True)
    medication_id = Column(Integer, ForeignKey("medications.id"), nullable=False)
    scheduled_time = Column(String(10), nullable=False)    # "HH:MM" 24h format, e.g., "08:00"
    days_of_week = Column(String(50), default="everyday")  # e.g., "everyday" or "mon,wed,fri"
    timezone = Column(String(50), default="UTC")           # e.g., "UTC", "America/New_York"
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    medication = relationship("Medication", back_populates="schedules")


class MedicationLog(Base):
    """Historical and real-time logs for scheduled doses with audit confirmation."""

    __tablename__ = "medication_logs"

    id = Column(Integer, primary_key=True, index=True)
    medication_id = Column(Integer, ForeignKey("medications.id"), nullable=False)
    senior_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    scheduled_for = Column(DateTime, nullable=False)
    status = Column(String(30), default="pending")         # pending, taken, missed, skipped
    taken_at = Column(DateTime, nullable=True)
    reminder_sent = Column(Boolean, default=False, nullable=False)
    reminder_sent_at = Column(DateTime, nullable=True)
    missed_notification_sent = Column(Boolean, default=False, nullable=False)
    missed_notification_sent_at = Column(DateTime, nullable=True)
    # User ID of the person who confirmed this dose (senior themselves, caregiver, or family)
    confirmed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("medication_id", "scheduled_for", name="uq_medication_scheduled_dose"),
    )

    medication = relationship("Medication", back_populates="logs")
    senior = relationship("User", foreign_keys=[senior_id])
    confirmed_by = relationship("User", foreign_keys=[confirmed_by_user_id])
    audits = relationship("MedicationStatusAudit", back_populates="log", cascade="all, delete-orphan")


class MedicationStatusAudit(Base):
    """Audit trail tracking every dose status transition and scheduler action."""

    __tablename__ = "medication_status_audits"

    id = Column(Integer, primary_key=True, index=True)
    log_id = Column(Integer, ForeignKey("medication_logs.id"), nullable=False)
    senior_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    medication_id = Column(Integer, ForeignKey("medications.id"), nullable=False)
    previous_status = Column(String(30), nullable=True)     # None, pending, taken, missed, skipped
    new_status = Column(String(30), nullable=False)          # pending, taken, missed, skipped
    changed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # None = system scheduler
    reason = Column(String(255), nullable=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    log = relationship("MedicationLog", back_populates="audits")
    senior = relationship("User", foreign_keys=[senior_id])
    changed_by = relationship("User", foreign_keys=[changed_by_user_id])


class DoctorAppointment(Base):
    """Doctor appointment management and reminders for seniors."""

    __tablename__ = "doctor_appointments"

    id = Column(Integer, primary_key=True, index=True)
    senior_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    doctor_name = Column(String(120), nullable=False)
    specialty = Column(String(100), nullable=True)         # e.g., "Cardiologist", "Optometrist"
    clinic_name = Column(String(150), nullable=True)
    clinic_address = Column(String(255), nullable=True)
    contact_phone = Column(String(50), nullable=True)
    appointment_datetime = Column(DateTime, nullable=False)
    purpose = Column(Text, nullable=True)                  # e.g., "Routine 6-month checkup"
    preparation_instructions = Column(Text, nullable=True) # e.g., "Fasting for blood tests"
    status = Column(String(30), default="scheduled")       # scheduled, completed, cancelled
    reminder_sent = Column(Boolean, default=False, nullable=False)
    reminder_sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    senior = relationship("User", foreign_keys=[senior_id], back_populates="appointments")
    created_by = relationship("User", foreign_keys=[created_by_user_id])


class NotificationLog(Base):
    """Persistent audit log of all outbound email alerts, status, and provider responses."""

    __tablename__ = "notification_logs"

    id = Column(Integer, primary_key=True, index=True)
    recipient_email = Column(String(255), nullable=False)
    recipient_name = Column(String(120), nullable=True)
    senior_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    notification_type = Column(String(50), nullable=False)  # upcoming_medication, missed_dose, doctor_appointment
    subject = Column(String(255), nullable=False)
    body_text = Column(Text, nullable=False)
    status = Column(String(30), default="sent")             # sent, simulated, failed
    error_message = Column(Text, nullable=True)
    related_entity_id = Column(Integer, nullable=True)      # medication_log_id or appointment_id
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    senior = relationship("User", foreign_keys=[senior_id])
