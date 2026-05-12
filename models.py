"""
VitalSync Database Models
All sensitive medical fields are Fernet-encrypted before storage.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime,
    ForeignKey, Text, Enum, JSON
)
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum


class UserRole(str, enum.Enum):
    patient = "patient"
    hospital = "hospital"
    pharmacy = "pharmacy"
    blood_bank = "blood_bank"
    admin = "admin"


class HealthStatus(str, enum.Enum):
    healthy = "healthy"
    warning = "warning"
    critical = "critical"
    emergency = "emergency"


# ── Users ─────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    phone = Column(String(20), unique=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.patient, nullable=False)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    patient_profile = relationship("PatientProfile", back_populates="user", uselist=False)
    hospital_profile = relationship("HospitalProfile", back_populates="user", uselist=False)
    pharmacy_profile = relationship("PharmacyProfile", back_populates="user", uselist=False)
    family_members = relationship("FamilyConnection", foreign_keys="FamilyConnection.user_id", back_populates="user")


class PatientProfile(Base):
    __tablename__ = "patient_profiles"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    date_of_birth = Column(String(20))
    blood_group = Column(String(5))
    gender = Column(String(10))
    height_cm = Column(Float)
    weight_kg = Column(Float)
    allergies = Column(Text)          # Encrypted
    medical_history = Column(Text)    # Encrypted
    emergency_contact_name = Column(String(255))
    emergency_contact_phone = Column(String(20))
    device_id = Column(String(100))   # IoT device identifier

    user = relationship("User", back_populates="patient_profile")
    vitals = relationship("VitalReading", back_populates="patient")
    daily_logs = relationship("DailyHealthLog", back_populates="patient")
    alerts = relationship("HealthAlert", back_populates="patient")
    prescriptions = relationship("Prescription", back_populates="patient")


class FamilyConnection(Base):
    __tablename__ = "family_connections"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    member_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    member_name = Column(String(255))
    member_phone = Column(String(20))
    relationship_type = Column(String(50))  # spouse, parent, child, sibling
    notify_on_emergency = Column(Boolean, default=True)

    user = relationship("User", foreign_keys=[user_id], back_populates="family_members")


# ── Vitals ────────────────────────────────────────────────────────────────────

class VitalReading(Base):
    __tablename__ = "vital_readings"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patient_profiles.id"))
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    heart_rate = Column(Float)        # BPM
    spo2 = Column(Float)              # Oxygen saturation %
    temperature = Column(Float)       # Celsius
    systolic_bp = Column(Float)       # mmHg (estimated)
    diastolic_bp = Column(Float)      # mmHg (estimated)
    ecg_value = Column(Float)         # Raw ECG amplitude
    motion_x = Column(Float)          # Accelerometer X
    motion_y = Column(Float)          # Accelerometer Y
    motion_z = Column(Float)          # Accelerometer Z
    fall_detected = Column(Boolean, default=False)
    source = Column(String(20), default="iot")  # iot | manual | simulator

    # ML analysis results
    health_status = Column(Enum(HealthStatus), default=HealthStatus.healthy)
    ml_confidence = Column(Float)
    ml_notes = Column(Text)

    patient = relationship("PatientProfile", back_populates="vitals")


class DailyHealthLog(Base):
    __tablename__ = "daily_health_logs"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patient_profiles.id"))
    log_date = Column(String(10), index=True)  # YYYY-MM-DD

    # Averaged vitals for the day
    avg_heart_rate = Column(Float)
    avg_spo2 = Column(Float)
    avg_temperature = Column(Float)
    avg_systolic_bp = Column(Float)
    avg_diastolic_bp = Column(Float)

    # Lifestyle check-in (from LLM conversation)
    food_intake = Column(Text)        # Encrypted
    symptoms = Column(Text)           # Encrypted
    diet_notes = Column(Text)         # Encrypted
    sleep_hours = Column(Float)
    exercise_minutes = Column(Float)
    stress_level = Column(Integer)    # 1-10
    llm_analysis = Column(Text)       # Encrypted - doctor-like analysis

    # Scores
    daily_health_score = Column(Float)  # 0-100
    weekly_health_score = Column(Float)
    monthly_health_score = Column(Float)

    created_at = Column(DateTime, default=datetime.utcnow)
    patient = relationship("PatientProfile", back_populates="daily_logs")


class HealthAlert(Base):
    __tablename__ = "health_alerts"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patient_profiles.id"))
    alert_type = Column(String(50))   # heart_attack, fall, low_spo2, high_temp, etc.
    severity = Column(String(20))     # warning | critical | emergency
    message = Column(Text)
    vital_snapshot = Column(JSON)     # Raw vitals at time of alert
    is_acknowledged = Column(Boolean, default=False)
    acknowledged_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("PatientProfile", back_populates="alerts")


# ── Medical Records ───────────────────────────────────────────────────────────

class Prescription(Base):
    __tablename__ = "prescriptions"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patient_profiles.id"))
    hospital_id = Column(Integer, ForeignKey("hospital_profiles.id"), nullable=True)
    prescribed_by = Column(String(255))  # Doctor name or "VitalSync AI"
    diagnosis = Column(Text)             # Encrypted
    medicines = Column(Text)             # Encrypted JSON list
    instructions = Column(Text)          # Encrypted
    valid_until = Column(String(10))
    is_ai_generated = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("PatientProfile", back_populates="prescriptions")


class LabReport(Base):
    __tablename__ = "lab_reports"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patient_profiles.id"))
    report_type = Column(String(100))
    report_data = Column(Text)    # Encrypted JSON
    report_date = Column(String(10))
    hospital_id = Column(Integer, ForeignKey("hospital_profiles.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ── Hospital ──────────────────────────────────────────────────────────────────

class HospitalProfile(Base):
    __tablename__ = "hospital_profiles"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    name = Column(String(255), nullable=False)
    address = Column(Text)
    city = Column(String(100))
    pincode = Column(String(10))
    phone = Column(String(20))
    email = Column(String(255))
    license_number = Column(String(100))
    specializations = Column(JSON)  # List of specialties

    # Bed availability (updated by hospital)
    general_beds_total = Column(Integer, default=0)
    general_beds_available = Column(Integer, default=0)
    semi_special_beds_total = Column(Integer, default=0)
    semi_special_beds_available = Column(Integer, default=0)
    special_beds_total = Column(Integer, default=0)
    special_beds_available = Column(Integer, default=0)
    icu_beds_total = Column(Integer, default=0)
    icu_beds_available = Column(Integer, default=0)

    # Pricing (per day)
    general_bed_price = Column(Float, default=0)
    semi_special_bed_price = Column(Float, default=0)
    special_bed_price = Column(Float, default=0)
    icu_bed_price = Column(Float, default=0)
    consultation_fee = Column(Float, default=0)

    has_ambulance = Column(Boolean, default=False)
    ambulance_fee = Column(Float, default=0)

    latitude = Column(Float)
    longitude = Column(Float)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="hospital_profile")
    bookings = relationship("HospitalBooking", back_populates="hospital")


class HospitalBooking(Base):
    __tablename__ = "hospital_bookings"

    id = Column(Integer, primary_key=True)
    patient_id = Column(Integer, ForeignKey("patient_profiles.id"))
    hospital_id = Column(Integer, ForeignKey("hospital_profiles.id"))
    booking_type = Column(String(50))  # consultation | admission | emergency
    bed_type = Column(String(30), nullable=True)
    scheduled_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="pending")  # pending | confirmed | cancelled | completed
    estimated_cost = Column(Float)
    ambulance_requested = Column(Boolean, default=False)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    hospital = relationship("HospitalProfile", back_populates="bookings")


# ── Pharmacy / Blood Bank ─────────────────────────────────────────────────────

class PharmacyProfile(Base):
    __tablename__ = "pharmacy_profiles"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    name = Column(String(255))
    address = Column(Text)
    city = Column(String(100))
    pincode = Column(String(10))
    phone = Column(String(20))
    license_number = Column(String(100))
    is_blood_bank = Column(Boolean, default=False)
    latitude = Column(Float)
    longitude = Column(Float)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="pharmacy_profile")
    inventory = relationship("MedicineInventory", back_populates="pharmacy")
    blood_inventory = relationship("BloodInventory", back_populates="pharmacy")


class MedicineInventory(Base):
    __tablename__ = "medicine_inventory"

    id = Column(Integer, primary_key=True)
    pharmacy_id = Column(Integer, ForeignKey("pharmacy_profiles.id"))
    medicine_name = Column(String(255), index=True)
    generic_name = Column(String(255))
    quantity_available = Column(Integer, default=0)
    price_per_unit = Column(Float)
    unit = Column(String(20))  # tablet, ml, mg
    requires_prescription = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    pharmacy = relationship("PharmacyProfile", back_populates="inventory")


class BloodInventory(Base):
    __tablename__ = "blood_inventory"

    id = Column(Integer, primary_key=True)
    pharmacy_id = Column(Integer, ForeignKey("pharmacy_profiles.id"))
    blood_group = Column(String(5), index=True)  # A+, A-, B+, B-, AB+, AB-, O+, O-
    units_available = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    pharmacy = relationship("PharmacyProfile", back_populates="blood_inventory")
