"""
VitalSync Seed Script
Creates default hospital, pharmacy, blood bank, and a test patient.
Run: python seed.py
"""
from app.core.database import create_tables, SessionLocal
from app.core.security import hash_password
from app.models.models import (
    User, UserRole, PatientProfile, HospitalProfile,
    PharmacyProfile, MedicineInventory, BloodInventory
)


def seed():
    create_tables()
    db = SessionLocal()
    try:
        print("🌱 Seeding VitalSync database...")

        # ── Default Hospital ──────────────────────────────────────────────────
        if not db.query(User).filter(User.email == "hospital@vitalsync.demo").first():
            hosp_user = User(
                email="hospital@vitalsync.demo",
                hashed_password=hash_password("Hospital@123"),
                full_name="City General Hospital",
                role=UserRole.hospital,
                is_verified=True,
            )
            db.add(hosp_user)
            db.flush()

            hosp_profile = HospitalProfile(
                user_id=hosp_user.id,
                name="City General Hospital",
                address="12, MG Road, Bengaluru",
                city="Bengaluru",
                pincode="560001",
                phone="+91-80-22001234",
                email="hospital@vitalsync.demo",
                license_number="KA-HOSP-2024-001",
                specializations=["Cardiology", "Neurology", "Orthopedics", "Emergency Medicine", "General Medicine"],
                general_beds_total=100,
                general_beds_available=45,
                semi_special_beds_total=50,
                semi_special_beds_available=20,
                special_beds_total=30,
                special_beds_available=10,
                icu_beds_total=20,
                icu_beds_available=5,
                general_bed_price=800,
                semi_special_bed_price=1500,
                special_bed_price=3000,
                icu_bed_price=8000,
                consultation_fee=500,
                has_ambulance=True,
                ambulance_fee=800,
                latitude=12.9716,
                longitude=77.5946,
            )
            db.add(hosp_profile)
            print("✅ Default hospital created | Login: hospital@vitalsync.demo / Hospital@123")

        # ── Default Pharmacy ──────────────────────────────────────────────────
        if not db.query(User).filter(User.email == "pharmacy@vitalsync.demo").first():
            pharm_user = User(
                email="pharmacy@vitalsync.demo",
                hashed_password=hash_password("Pharmacy@123"),
                full_name="HealthPlus Pharmacy",
                role=UserRole.pharmacy,
                is_verified=True,
            )
            db.add(pharm_user)
            db.flush()

            pharm_profile = PharmacyProfile(
                user_id=pharm_user.id,
                name="HealthPlus Pharmacy",
                address="45, Koramangala, Bengaluru",
                city="Bengaluru",
                pincode="560034",
                phone="+91-80-40001234",
                license_number="KA-PHARM-2024-001",
                is_blood_bank=False,
                latitude=12.9352,
                longitude=77.6245,
            )
            db.add(pharm_profile)
            db.flush()

            # Sample medicines
            medicines = [
                {"name": "Paracetamol 500mg", "generic": "Acetaminophen", "qty": 500, "price": 2.5, "unit": "tablet", "rx": False},
                {"name": "Amoxicillin 500mg", "generic": "Amoxicillin", "qty": 200, "price": 12.0, "unit": "capsule", "rx": True},
                {"name": "Metformin 500mg", "generic": "Metformin HCl", "qty": 300, "price": 5.0, "unit": "tablet", "rx": True},
                {"name": "Atorvastatin 10mg", "generic": "Atorvastatin", "qty": 150, "price": 8.0, "unit": "tablet", "rx": True},
                {"name": "ORS Sachet", "generic": "Oral Rehydration Salt", "qty": 100, "price": 15.0, "unit": "sachet", "rx": False},
                {"name": "Ibuprofen 400mg", "generic": "Ibuprofen", "qty": 300, "price": 4.5, "unit": "tablet", "rx": False},
                {"name": "Cetirizine 10mg", "generic": "Cetirizine HCl", "qty": 250, "price": 3.0, "unit": "tablet", "rx": False},
                {"name": "Pantoprazole 40mg", "generic": "Pantoprazole", "qty": 200, "price": 9.0, "unit": "tablet", "rx": True},
            ]
            for m in medicines:
                db.add(MedicineInventory(
                    pharmacy_id=pharm_profile.id,
                    medicine_name=m["name"],
                    generic_name=m["generic"],
                    quantity_available=m["qty"],
                    price_per_unit=m["price"],
                    unit=m["unit"],
                    requires_prescription=m["rx"],
                ))
            print("✅ Default pharmacy created | Login: pharmacy@vitalsync.demo / Pharmacy@123")

        # ── Default Blood Bank ────────────────────────────────────────────────
        if not db.query(User).filter(User.email == "bloodbank@vitalsync.demo").first():
            bb_user = User(
                email="bloodbank@vitalsync.demo",
                hashed_password=hash_password("BloodBank@123"),
                full_name="LifeSource Blood Bank",
                role=UserRole.blood_bank,
                is_verified=True,
            )
            db.add(bb_user)
            db.flush()

            bb_profile = PharmacyProfile(
                user_id=bb_user.id,
                name="LifeSource Blood Bank",
                address="78, Indiranagar, Bengaluru",
                city="Bengaluru",
                pincode="560038",
                phone="+91-80-25001234",
                license_number="KA-BB-2024-001",
                is_blood_bank=True,
                latitude=12.9784,
                longitude=77.6408,
            )
            db.add(bb_profile)
            db.flush()

            # Blood inventory
            blood_groups = [
                ("A+", 25), ("A-", 8), ("B+", 30), ("B-", 5),
                ("AB+", 12), ("AB-", 3), ("O+", 40), ("O-", 15)
            ]
            for bg, units in blood_groups:
                db.add(BloodInventory(
                    pharmacy_id=bb_profile.id,
                    blood_group=bg,
                    units_available=units
                ))
            print("✅ Default blood bank created | Login: bloodbank@vitalsync.demo / BloodBank@123")

        # ── Test Patient ──────────────────────────────────────────────────────
        if not db.query(User).filter(User.email == "patient@vitalsync.demo").first():
            pat_user = User(
                email="patient@vitalsync.demo",
                hashed_password=hash_password("Patient@123"),
                full_name="Hemanth Kumar",
                phone="+91-9876543210",
                role=UserRole.patient,
                is_verified=True,
            )
            db.add(pat_user)
            db.flush()

            pat_profile = PatientProfile(
                user_id=pat_user.id,
                date_of_birth="2005-01-15",
                blood_group="O+",
                gender="Male",
                height_cm=175,
                weight_kg=70,
                device_id="ESP32-DEMO-001",
                emergency_contact_name="Emergency Contact",
                emergency_contact_phone="+91-9876543211",
            )
            db.add(pat_profile)
            print("✅ Test patient created | Login: patient@vitalsync.demo / Patient@123")

        db.commit()
        print("\n🎉 Database seeded successfully!")
        print("\n📋 Demo Accounts:")
        print("  Patient:   patient@vitalsync.demo   / Patient@123")
        print("  Hospital:  hospital@vitalsync.demo  / Hospital@123")
        print("  Pharmacy:  pharmacy@vitalsync.demo  / Pharmacy@123")
        print("  Blood Bank:bloodbank@vitalsync.demo / BloodBank@123")

    except Exception as e:
        db.rollback()
        print(f"❌ Seed error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    seed()
