from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models.models import (
    HospitalProfile, HospitalBooking, PatientProfile,
    LabReport, Prescription, User, UserRole
)
from app.ml.llm_advisor import estimate_treatment_budget
from app.core.security import encrypt_field, decrypt_field
import json

router = APIRouter(prefix="/api/hospital", tags=["Hospital"])


class HospitalUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    pincode: Optional[str] = None
    phone: Optional[str] = None
    license_number: Optional[str] = None
    specializations: Optional[List[str]] = None
    general_beds_total: Optional[int] = None
    general_beds_available: Optional[int] = None
    semi_special_beds_total: Optional[int] = None
    semi_special_beds_available: Optional[int] = None
    special_beds_total: Optional[int] = None
    special_beds_available: Optional[int] = None
    icu_beds_total: Optional[int] = None
    icu_beds_available: Optional[int] = None
    general_bed_price: Optional[float] = None
    semi_special_bed_price: Optional[float] = None
    special_bed_price: Optional[float] = None
    icu_bed_price: Optional[float] = None
    consultation_fee: Optional[float] = None
    has_ambulance: Optional[bool] = None
    ambulance_fee: Optional[float] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class BookingRequest(BaseModel):
    hospital_id: int
    booking_type: str  # consultation | admission | emergency
    bed_type: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    ambulance_requested: bool = False
    notes: Optional[str] = ""


class BudgetRequest(BaseModel):
    hospital_id: int
    diagnosis: str


# ── Public: List Hospitals ─────────────────────────────────────────────────────

@router.get("/list")
def list_hospitals(
    city: Optional[str] = None,
    has_icu: Optional[bool] = None,
    has_ambulance: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    q = db.query(HospitalProfile)
    if city:
        q = q.filter(HospitalProfile.city.ilike(f"%{city}%"))
    if has_icu:
        q = q.filter(HospitalProfile.icu_beds_available > 0)
    if has_ambulance:
        q = q.filter(HospitalProfile.has_ambulance == True)

    hospitals = q.all()
    return [_serialize_hospital(h) for h in hospitals]


@router.get("/{hospital_id}")
def get_hospital(hospital_id: int, db: Session = Depends(get_db)):
    h = db.query(HospitalProfile).filter(HospitalProfile.id == hospital_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Hospital not found")
    return _serialize_hospital(h)


def _serialize_hospital(h: HospitalProfile) -> dict:
    return {
        "id": h.id,
        "name": h.name,
        "address": h.address,
        "city": h.city,
        "pincode": h.pincode,
        "phone": h.phone,
        "specializations": h.specializations or [],
        "beds": {
            "general": {"total": h.general_beds_total, "available": h.general_beds_available, "price_per_day": h.general_bed_price},
            "semi_special": {"total": h.semi_special_beds_total, "available": h.semi_special_beds_available, "price_per_day": h.semi_special_bed_price},
            "special": {"total": h.special_beds_total, "available": h.special_beds_available, "price_per_day": h.special_bed_price},
            "icu": {"total": h.icu_beds_total, "available": h.icu_beds_available, "price_per_day": h.icu_bed_price},
        },
        "consultation_fee": h.consultation_fee,
        "has_ambulance": h.has_ambulance,
        "ambulance_fee": h.ambulance_fee,
        "latitude": h.latitude,
        "longitude": h.longitude,
        "updated_at": h.updated_at.isoformat() if h.updated_at else None,
    }


# ── Hospital Management (Hospital role only) ───────────────────────────────────

@router.put("/profile")
def update_hospital_profile(
    data: HospitalUpdate,
    current_user: User = Depends(require_role("hospital", "admin")),
    db: Session = Depends(get_db)
):
    h = db.query(HospitalProfile).filter(HospitalProfile.user_id == current_user.id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Hospital profile not found")

    for field, value in data.dict(exclude_none=True).items():
        setattr(h, field, value)
    h.updated_at = datetime.utcnow()
    db.commit()
    return {"message": "Hospital profile updated", "hospital": _serialize_hospital(h)}


@router.get("/profile/me")
def get_my_hospital_profile(
    current_user: User = Depends(require_role("hospital", "admin")),
    db: Session = Depends(get_db)
):
    h = db.query(HospitalProfile).filter(HospitalProfile.user_id == current_user.id).first()
    if not h:
        raise HTTPException(status_code=404, detail="Profile not found")
    return _serialize_hospital(h)


@router.get("/bookings/incoming")
def get_incoming_bookings(
    status: Optional[str] = None,
    current_user: User = Depends(require_role("hospital", "admin")),
    db: Session = Depends(get_db)
):
    h = db.query(HospitalProfile).filter(HospitalProfile.user_id == current_user.id).first()
    q = db.query(HospitalBooking).filter(HospitalBooking.hospital_id == h.id)
    if status:
        q = q.filter(HospitalBooking.status == status)
    bookings = q.order_by(desc(HospitalBooking.created_at)).all()

    return [
        {
            "id": b.id,
            "patient_id": b.patient_id,
            "booking_type": b.booking_type,
            "bed_type": b.bed_type,
            "scheduled_at": b.scheduled_at.isoformat() if b.scheduled_at else None,
            "status": b.status,
            "estimated_cost": b.estimated_cost,
            "ambulance_requested": b.ambulance_requested,
            "notes": b.notes,
            "created_at": b.created_at.isoformat(),
        }
        for b in bookings
    ]


@router.put("/bookings/{booking_id}/status")
def update_booking_status(
    booking_id: int,
    status: str,
    current_user: User = Depends(require_role("hospital", "admin")),
    db: Session = Depends(get_db)
):
    h = db.query(HospitalProfile).filter(HospitalProfile.user_id == current_user.id).first()
    booking = db.query(HospitalBooking).filter(
        HospitalBooking.id == booking_id,
        HospitalBooking.hospital_id == h.id
    ).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    booking.status = status
    db.commit()
    return {"message": f"Booking status updated to {status}"}


# ── Patient: Book Hospital ─────────────────────────────────────────────────────

@router.post("/book")
def book_hospital(
    data: BookingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    profile = db.query(PatientProfile).filter(PatientProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    hospital = db.query(HospitalProfile).filter(HospitalProfile.id == data.hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    # Calculate estimated cost
    bed_prices = {
        "general": hospital.general_bed_price or 0,
        "semi_special": hospital.semi_special_bed_price or 0,
        "special": hospital.special_bed_price or 0,
        "icu": hospital.icu_bed_price or 0,
    }
    estimated_cost = hospital.consultation_fee or 0
    if data.bed_type and data.bed_type in bed_prices:
        estimated_cost += bed_prices[data.bed_type]
    if data.ambulance_requested:
        estimated_cost += hospital.ambulance_fee or 0

    booking = HospitalBooking(
        patient_id=profile.id,
        hospital_id=data.hospital_id,
        booking_type=data.booking_type,
        bed_type=data.bed_type,
        scheduled_at=data.scheduled_at,
        ambulance_requested=data.ambulance_requested,
        estimated_cost=estimated_cost,
        notes=data.notes,
        status="pending",
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)

    return {
        "booking_id": booking.id,
        "status": booking.status,
        "estimated_cost": estimated_cost,
        "hospital": hospital.name,
        "ambulance_requested": data.ambulance_requested,
    }


@router.post("/budget-estimate")
def estimate_budget(
    data: BudgetRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    hospital = db.query(HospitalProfile).filter(HospitalProfile.id == data.hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="Hospital not found")

    hospital_data = {
        "name": hospital.name,
        "city": hospital.city,
        "consultation_fee": hospital.consultation_fee,
        "general_bed_per_day": hospital.general_bed_price,
        "icu_bed_per_day": hospital.icu_bed_price,
    }

    result = estimate_treatment_budget(
        diagnosis=data.diagnosis,
        city=hospital.city or "India",
        hospital_data=hospital_data
    )
    return result


# ── Digital Records ────────────────────────────────────────────────────────────

@router.get("/records/my")
def get_my_records(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    profile = db.query(PatientProfile).filter(PatientProfile.user_id == current_user.id).first()

    prescriptions = db.query(Prescription).filter(
        Prescription.patient_id == profile.id
    ).order_by(desc(Prescription.created_at)).all()

    lab_reports = db.query(LabReport).filter(
        LabReport.patient_id == profile.id
    ).order_by(desc(LabReport.created_at)).all()

    return {
        "prescriptions": [
            {
                "id": p.id,
                "prescribed_by": p.prescribed_by,
                "diagnosis": decrypt_field(p.diagnosis or ""),
                "medicines": json.loads(decrypt_field(p.medicines or "[]")),
                "instructions": decrypt_field(p.instructions or ""),
                "valid_until": p.valid_until,
                "is_ai_generated": p.is_ai_generated,
                "created_at": p.created_at.isoformat(),
            }
            for p in prescriptions
        ],
        "lab_reports": [
            {
                "id": r.id,
                "report_type": r.report_type,
                "report_date": r.report_date,
                "created_at": r.created_at.isoformat(),
            }
            for r in lab_reports
        ]
    }
