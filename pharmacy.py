from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models.models import PharmacyProfile, MedicineInventory, BloodInventory, User

router = APIRouter(prefix="/api/pharmacy", tags=["Pharmacy & Blood Bank"])


class PharmacyUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    pincode: Optional[str] = None
    phone: Optional[str] = None
    license_number: Optional[str] = None
    is_blood_bank: Optional[bool] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class MedicineUpdate(BaseModel):
    medicine_name: str
    generic_name: Optional[str] = ""
    quantity_available: int
    price_per_unit: float
    unit: str = "tablet"
    requires_prescription: bool = False


class BloodUpdate(BaseModel):
    blood_group: str  # A+, A-, B+, etc.
    units_available: int


# ── Public: Search Medicine ────────────────────────────────────────────────────

@router.get("/medicine/search")
def search_medicine(
    name: str,
    city: Optional[str] = None,
    db: Session = Depends(get_db)
):
    q = (
        db.query(MedicineInventory, PharmacyProfile)
        .join(PharmacyProfile, MedicineInventory.pharmacy_id == PharmacyProfile.id)
        .filter(
            MedicineInventory.medicine_name.ilike(f"%{name}%"),
            MedicineInventory.quantity_available > 0
        )
    )
    if city:
        q = q.filter(PharmacyProfile.city.ilike(f"%{city}%"))

    results = q.all()
    return [
        {
            "medicine_name": m.medicine_name,
            "generic_name": m.generic_name,
            "quantity_available": m.quantity_available,
            "price_per_unit": m.price_per_unit,
            "unit": m.unit,
            "requires_prescription": m.requires_prescription,
            "pharmacy": {
                "id": p.id,
                "name": p.name,
                "address": p.address,
                "city": p.city,
                "phone": p.phone,
                "latitude": p.latitude,
                "longitude": p.longitude,
            }
        }
        for m, p in results
    ]


# ── Public: Search Blood ───────────────────────────────────────────────────────

@router.get("/blood/search")
def search_blood(
    blood_group: str,
    city: Optional[str] = None,
    db: Session = Depends(get_db)
):
    q = (
        db.query(BloodInventory, PharmacyProfile)
        .join(PharmacyProfile, BloodInventory.pharmacy_id == PharmacyProfile.id)
        .filter(
            BloodInventory.blood_group == blood_group,
            BloodInventory.units_available > 0,
            PharmacyProfile.is_blood_bank == True
        )
    )
    if city:
        q = q.filter(PharmacyProfile.city.ilike(f"%{city}%"))

    results = q.all()
    return [
        {
            "blood_group": b.blood_group,
            "units_available": b.units_available,
            "updated_at": b.updated_at.isoformat() if b.updated_at else None,
            "blood_bank": {
                "id": p.id,
                "name": p.name,
                "address": p.address,
                "city": p.city,
                "phone": p.phone,
                "latitude": p.latitude,
                "longitude": p.longitude,
            }
        }
        for b, p in results
    ]


@router.get("/blood/all-groups")
def get_all_blood_groups(city: Optional[str] = None, db: Session = Depends(get_db)):
    """Get availability of all blood groups."""
    BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
    result = {}
    for bg in BLOOD_GROUPS:
        q = db.query(BloodInventory).join(PharmacyProfile).filter(
            BloodInventory.blood_group == bg,
            BloodInventory.units_available > 0,
            PharmacyProfile.is_blood_bank == True
        )
        if city:
            q = q.filter(PharmacyProfile.city.ilike(f"%{city}%"))
        result[bg] = q.count()
    return result


# ── Public: List Pharmacies ────────────────────────────────────────────────────

@router.get("/list")
def list_pharmacies(
    city: Optional[str] = None,
    is_blood_bank: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    q = db.query(PharmacyProfile)
    if city:
        q = q.filter(PharmacyProfile.city.ilike(f"%{city}%"))
    if is_blood_bank is not None:
        q = q.filter(PharmacyProfile.is_blood_bank == is_blood_bank)
    pharmacies = q.all()
    return [_serialize_pharmacy(p) for p in pharmacies]


def _serialize_pharmacy(p: PharmacyProfile) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "address": p.address,
        "city": p.city,
        "pincode": p.pincode,
        "phone": p.phone,
        "is_blood_bank": p.is_blood_bank,
        "latitude": p.latitude,
        "longitude": p.longitude,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


# ── Pharmacy Management (Pharmacy role only) ───────────────────────────────────

@router.put("/profile")
def update_pharmacy_profile(
    data: PharmacyUpdate,
    current_user: User = Depends(require_role("pharmacy", "blood_bank", "admin")),
    db: Session = Depends(get_db)
):
    p = db.query(PharmacyProfile).filter(PharmacyProfile.user_id == current_user.id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Pharmacy profile not found")

    for field, value in data.dict(exclude_none=True).items():
        setattr(p, field, value)
    p.updated_at = datetime.utcnow()
    db.commit()
    return {"message": "Pharmacy profile updated"}


@router.post("/medicine")
def add_or_update_medicine(
    data: MedicineUpdate,
    current_user: User = Depends(require_role("pharmacy", "admin")),
    db: Session = Depends(get_db)
):
    p = db.query(PharmacyProfile).filter(PharmacyProfile.user_id == current_user.id).first()

    # Check if exists
    existing = db.query(MedicineInventory).filter(
        MedicineInventory.pharmacy_id == p.id,
        MedicineInventory.medicine_name == data.medicine_name
    ).first()

    if existing:
        for field, value in data.dict().items():
            setattr(existing, field, value)
        existing.updated_at = datetime.utcnow()
        db.commit()
        return {"message": "Medicine inventory updated"}
    else:
        med = MedicineInventory(pharmacy_id=p.id, **data.dict())
        db.add(med)
        db.commit()
        return {"message": "Medicine added to inventory"}


@router.get("/medicine/my")
def get_my_inventory(
    current_user: User = Depends(require_role("pharmacy", "admin")),
    db: Session = Depends(get_db)
):
    p = db.query(PharmacyProfile).filter(PharmacyProfile.user_id == current_user.id).first()
    meds = db.query(MedicineInventory).filter(MedicineInventory.pharmacy_id == p.id).all()
    return [
        {
            "id": m.id,
            "medicine_name": m.medicine_name,
            "generic_name": m.generic_name,
            "quantity_available": m.quantity_available,
            "price_per_unit": m.price_per_unit,
            "unit": m.unit,
            "requires_prescription": m.requires_prescription,
            "updated_at": m.updated_at.isoformat() if m.updated_at else None,
        }
        for m in meds
    ]


@router.post("/blood")
def update_blood_inventory(
    data: BloodUpdate,
    current_user: User = Depends(require_role("pharmacy", "blood_bank", "admin")),
    db: Session = Depends(get_db)
):
    p = db.query(PharmacyProfile).filter(PharmacyProfile.user_id == current_user.id).first()

    existing = db.query(BloodInventory).filter(
        BloodInventory.pharmacy_id == p.id,
        BloodInventory.blood_group == data.blood_group
    ).first()

    if existing:
        existing.units_available = data.units_available
        existing.updated_at = datetime.utcnow()
    else:
        blood = BloodInventory(
            pharmacy_id=p.id,
            blood_group=data.blood_group,
            units_available=data.units_available
        )
        db.add(blood)

    db.commit()
    return {"message": f"Blood inventory updated for {data.blood_group}"}


@router.get("/blood/my")
def get_my_blood_inventory(
    current_user: User = Depends(require_role("pharmacy", "blood_bank", "admin")),
    db: Session = Depends(get_db)
):
    p = db.query(PharmacyProfile).filter(PharmacyProfile.user_id == current_user.id).first()
    blood = db.query(BloodInventory).filter(BloodInventory.pharmacy_id == p.id).all()
    return [
        {
            "blood_group": b.blood_group,
            "units_available": b.units_available,
            "updated_at": b.updated_at.isoformat() if b.updated_at else None,
        }
        for b in blood
    ]
