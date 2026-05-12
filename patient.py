from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, date, timedelta
import json

from app.core.database import get_db
from app.core.security import get_current_user, encrypt_field, decrypt_field
from app.models.models import (
    PatientProfile, VitalReading, DailyHealthLog, HealthAlert,
    Prescription, FamilyConnection, HealthStatus, User
)
from app.ml.vitals_model import get_analyzer
from app.ml.llm_advisor import run_daily_checkin, generate_ai_prescription, DAILY_CHECKIN_QUESTIONS
from app.services.alert_service import trigger_emergency_alert

router = APIRouter(prefix="/api/patient", tags=["Patient"])


# ── Pydantic Models ────────────────────────────────────────────────────────────

class VitalSubmit(BaseModel):
    heart_rate: float
    spo2: float
    temperature: float
    systolic_bp: Optional[float] = 120.0
    diastolic_bp: Optional[float] = 80.0
    ecg_value: Optional[float] = 0.5
    motion_x: Optional[float] = 0.0
    motion_y: Optional[float] = 0.0
    motion_z: Optional[float] = 9.8
    fall_detected: Optional[bool] = False
    source: Optional[str] = "manual"


class CheckinSubmit(BaseModel):
    food: str = ""
    symptoms: str = ""
    diet: str = ""
    sleep_hours: float = 7.0
    exercise_minutes: float = 0.0
    stress_level: int = 5
    water_intake: float = 8.0


class ProfileUpdate(BaseModel):
    date_of_birth: Optional[str] = None
    blood_group: Optional[str] = None
    gender: Optional[str] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    allergies: Optional[str] = None
    medical_history: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    device_id: Optional[str] = None


class FamilyMemberAdd(BaseModel):
    member_name: str
    member_phone: str
    relationship_type: str
    notify_on_emergency: bool = True


class PrescriptionRequest(BaseModel):
    symptoms: str


# ── Profile ────────────────────────────────────────────────────────────────────

@router.get("/profile")
def get_profile(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(PatientProfile).filter(PatientProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    return {
        "user_id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "phone": current_user.phone,
        "role": current_user.role.value,
        "profile": {
            "id": profile.id,
            "date_of_birth": profile.date_of_birth,
            "blood_group": profile.blood_group,
            "gender": profile.gender,
            "height_cm": profile.height_cm,
            "weight_kg": profile.weight_kg,
            "allergies": decrypt_field(profile.allergies or ""),
            "medical_history": decrypt_field(profile.medical_history or ""),
            "emergency_contact_name": profile.emergency_contact_name,
            "emergency_contact_phone": profile.emergency_contact_phone,
            "device_id": profile.device_id,
        }
    }


@router.put("/profile")
def update_profile(
    data: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    profile = db.query(PatientProfile).filter(PatientProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    for field, value in data.dict(exclude_none=True).items():
        if field in ("allergies", "medical_history") and value:
            value = encrypt_field(value)
        setattr(profile, field, value)

    db.commit()
    return {"message": "Profile updated successfully"}


# ── Vitals ─────────────────────────────────────────────────────────────────────

@router.post("/vitals")
def submit_vitals(
    data: VitalSubmit,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    profile = db.query(PatientProfile).filter(PatientProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    # Run ML analysis
    analyzer = get_analyzer()
    vitals_dict = data.dict()
    analysis = analyzer.analyze_vitals(vitals_dict)

    # Save reading
    reading = VitalReading(
        patient_id=profile.id,
        **{k: v for k, v in vitals_dict.items() if k != "source"},
        source=data.source,
        health_status=HealthStatus(analysis["status"]),
        ml_confidence=analysis["confidence"],
        ml_notes=analysis["notes"],
    )
    db.add(reading)

    # Create alert if needed
    if analysis["status"] in ("critical", "emergency") or analysis["emergency_flags"]:
        alert = HealthAlert(
            patient_id=profile.id,
            alert_type=analysis["emergency_flags"][0] if analysis["emergency_flags"] else analysis["status"].upper(),
            severity=analysis["status"],
            message=analysis["notes"],
            vital_snapshot=vitals_dict,
        )
        db.add(alert)
        db.flush()

        # Trigger emergency notifications in background
        if analysis["status"] == "emergency":
            background_tasks.add_task(
                trigger_emergency_alert,
                patient_id=profile.id,
                alert_id=alert.id,
                vitals=vitals_dict,
                flags=analysis["emergency_flags"],
                db=db,
            )

    db.commit()
    db.refresh(reading)

    return {
        "reading_id": reading.id,
        "timestamp": reading.timestamp.isoformat(),
        "analysis": analysis,
        "status": analysis["status"],
        "emergency": analysis["status"] == "emergency",
    }


@router.get("/vitals/latest")
def get_latest_vitals(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    profile = db.query(PatientProfile).filter(PatientProfile.user_id == current_user.id).first()
    readings = (
        db.query(VitalReading)
        .filter(VitalReading.patient_id == profile.id)
        .order_by(desc(VitalReading.timestamp))
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "timestamp": r.timestamp.isoformat(),
            "heart_rate": r.heart_rate,
            "spo2": r.spo2,
            "temperature": r.temperature,
            "systolic_bp": r.systolic_bp,
            "diastolic_bp": r.diastolic_bp,
            "fall_detected": r.fall_detected,
            "health_status": r.health_status.value if r.health_status else "healthy",
            "ml_notes": r.ml_notes,
        }
        for r in readings
    ]


@router.get("/vitals/stats")
def get_vital_stats(
    days: int = 7,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get daily averages for trend charts."""
    profile = db.query(PatientProfile).filter(PatientProfile.user_id == current_user.id).first()
    since = datetime.utcnow() - timedelta(days=days)

    readings = (
        db.query(VitalReading)
        .filter(VitalReading.patient_id == profile.id, VitalReading.timestamp >= since)
        .all()
    )

    if not readings:
        return {"days": [], "averages": {}}

    # Group by day
    from collections import defaultdict
    daily = defaultdict(list)
    for r in readings:
        day = r.timestamp.strftime("%Y-%m-%d")
        daily[day].append(r)

    result = []
    for day in sorted(daily.keys()):
        rs = daily[day]
        result.append({
            "date": day,
            "avg_heart_rate": round(sum(r.heart_rate for r in rs) / len(rs), 1),
            "avg_spo2": round(sum(r.spo2 for r in rs) / len(rs), 1),
            "avg_temperature": round(sum(r.temperature for r in rs) / len(rs), 2),
            "avg_systolic_bp": round(sum(r.systolic_bp or 120 for r in rs) / len(rs), 1),
            "readings_count": len(rs),
        })

    return {"days": result}


# ── Health Score ───────────────────────────────────────────────────────────────

@router.get("/health-score")
def get_health_score(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    profile = db.query(PatientProfile).filter(PatientProfile.user_id == current_user.id).first()

    now = datetime.utcnow()
    today = now.strftime("%Y-%m-%d")
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    def avg_score_for_period(start_date: str):
        logs = (
            db.query(DailyHealthLog)
            .filter(
                DailyHealthLog.patient_id == profile.id,
                DailyHealthLog.log_date >= start_date
            )
            .all()
        )
        if not logs:
            return 75.0
        scores = [l.daily_health_score for l in logs if l.daily_health_score]
        return round(sum(scores) / len(scores), 1) if scores else 75.0

    today_log = db.query(DailyHealthLog).filter(
        DailyHealthLog.patient_id == profile.id,
        DailyHealthLog.log_date == today
    ).first()

    return {
        "daily": today_log.daily_health_score if today_log else None,
        "weekly": avg_score_for_period(week_ago),
        "monthly": avg_score_for_period(month_ago),
        "last_checkin": today_log.created_at.isoformat() if today_log else None,
    }


# ── Daily Check-in ─────────────────────────────────────────────────────────────

@router.get("/checkin/questions")
def get_checkin_questions():
    return {"questions": DAILY_CHECKIN_QUESTIONS}


@router.post("/checkin")
def submit_checkin(
    data: CheckinSubmit,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    profile = db.query(PatientProfile).filter(PatientProfile.user_id == current_user.id).first()
    today = datetime.utcnow().strftime("%Y-%m-%d")

    # Get today's average vitals
    since = datetime.utcnow().replace(hour=0, minute=0, second=0)
    readings = db.query(VitalReading).filter(
        VitalReading.patient_id == profile.id,
        VitalReading.timestamp >= since
    ).all()

    avg_vitals = {}
    if readings:
        avg_vitals = {
            "heart_rate": round(sum(r.heart_rate for r in readings) / len(readings), 1),
            "spo2": round(sum(r.spo2 for r in readings) / len(readings), 1),
            "temperature": round(sum(r.temperature for r in readings) / len(readings), 2),
            "systolic_bp": round(sum((r.systolic_bp or 120) for r in readings) / len(readings), 1),
            "diastolic_bp": round(sum((r.diastolic_bp or 80) for r in readings) / len(readings), 1),
        }
    else:
        avg_vitals = {"heart_rate": 72, "spo2": 98, "temperature": 36.8, "systolic_bp": 120, "diastolic_bp": 80}

    # Run LLM analysis
    try:
        llm_result = run_daily_checkin(
            patient_name=current_user.full_name,
            avg_vitals=avg_vitals,
            user_responses=data.dict()
        )
        health_score = float(llm_result.get("health_score", 75))
        llm_text = json.dumps(llm_result)
    except Exception as e:
        health_score = 75.0
        llm_text = json.dumps({"error": str(e), "overall_assessment": "Analysis unavailable. Please try again."})

    # Upsert daily log
    log = db.query(DailyHealthLog).filter(
        DailyHealthLog.patient_id == profile.id,
        DailyHealthLog.log_date == today
    ).first()

    if not log:
        log = DailyHealthLog(patient_id=profile.id, log_date=today)
        db.add(log)

    log.avg_heart_rate = avg_vitals.get("heart_rate")
    log.avg_spo2 = avg_vitals.get("spo2")
    log.avg_temperature = avg_vitals.get("temperature")
    log.avg_systolic_bp = avg_vitals.get("systolic_bp")
    log.avg_diastolic_bp = avg_vitals.get("diastolic_bp")
    log.food_intake = encrypt_field(data.food)
    log.symptoms = encrypt_field(data.symptoms)
    log.diet_notes = encrypt_field(data.diet)
    log.sleep_hours = data.sleep_hours
    log.exercise_minutes = data.exercise_minutes
    log.stress_level = data.stress_level
    log.daily_health_score = health_score
    log.llm_analysis = encrypt_field(llm_text)

    db.commit()

    return {
        "message": "Daily check-in submitted",
        "health_score": health_score,
        "analysis": json.loads(llm_text) if llm_text else {},
        "avg_vitals": avg_vitals,
    }


# ── Alerts ─────────────────────────────────────────────────────────────────────

@router.get("/alerts")
def get_alerts(
    unread_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    profile = db.query(PatientProfile).filter(PatientProfile.user_id == current_user.id).first()
    q = db.query(HealthAlert).filter(HealthAlert.patient_id == profile.id)
    if unread_only:
        q = q.filter(HealthAlert.is_acknowledged == False)
    alerts = q.order_by(desc(HealthAlert.created_at)).limit(50).all()

    return [
        {
            "id": a.id,
            "alert_type": a.alert_type,
            "severity": a.severity,
            "message": a.message,
            "vital_snapshot": a.vital_snapshot,
            "is_acknowledged": a.is_acknowledged,
            "created_at": a.created_at.isoformat(),
        }
        for a in alerts
    ]


@router.put("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(
    alert_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    profile = db.query(PatientProfile).filter(PatientProfile.user_id == current_user.id).first()
    alert = db.query(HealthAlert).filter(
        HealthAlert.id == alert_id,
        HealthAlert.patient_id == profile.id
    ).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.is_acknowledged = True
    alert.acknowledged_at = datetime.utcnow()
    db.commit()
    return {"message": "Alert acknowledged"}


# ── AI Prescription ────────────────────────────────────────────────────────────

@router.post("/prescription/ai")
def get_ai_prescription(
    data: PrescriptionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    profile = db.query(PatientProfile).filter(PatientProfile.user_id == current_user.id).first()

    # Get latest vitals
    latest = db.query(VitalReading).filter(
        VitalReading.patient_id == profile.id
    ).order_by(desc(VitalReading.timestamp)).first()

    vitals = {}
    if latest:
        vitals = {
            "heart_rate": latest.heart_rate,
            "spo2": latest.spo2,
            "temperature": latest.temperature,
            "systolic_bp": latest.systolic_bp,
            "diastolic_bp": latest.diastolic_bp,
        }
    else:
        vitals = {"heart_rate": 72, "spo2": 98, "temperature": 36.8, "systolic_bp": 120, "diastolic_bp": 80}

    # Calculate age
    age = 25  # Default
    if profile.date_of_birth:
        try:
            dob = datetime.strptime(profile.date_of_birth, "%Y-%m-%d")
            age = (datetime.utcnow() - dob).days // 365
        except Exception:
            pass

    allergies = decrypt_field(profile.allergies or "")
    result = generate_ai_prescription(
        patient_name=current_user.full_name,
        age=age,
        symptoms=data.symptoms,
        vitals=vitals,
        known_allergies=allergies
    )

    # Save as prescription
    if result.get("can_treat_at_home") and result.get("medicines"):
        rx = Prescription(
            patient_id=profile.id,
            prescribed_by="VitalSync AI",
            diagnosis=encrypt_field(result.get("condition_assessment", "")),
            medicines=encrypt_field(json.dumps(result.get("medicines", []))),
            instructions=encrypt_field(json.dumps(result.get("home_remedies", []))),
            valid_until=(datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%d"),
            is_ai_generated=True,
        )
        db.add(rx)
        db.commit()

    return result


# ── Family Connections ─────────────────────────────────────────────────────────

@router.get("/family")
def get_family(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    members = db.query(FamilyConnection).filter(FamilyConnection.user_id == current_user.id).all()
    return [
        {
            "id": m.id,
            "member_name": m.member_name,
            "member_phone": m.member_phone,
            "relationship_type": m.relationship_type,
            "notify_on_emergency": m.notify_on_emergency,
        }
        for m in members
    ]


@router.post("/family")
def add_family_member(
    data: FamilyMemberAdd,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    member = FamilyConnection(
        user_id=current_user.id,
        member_name=data.member_name,
        member_phone=data.member_phone,
        relationship_type=data.relationship_type,
        notify_on_emergency=data.notify_on_emergency,
    )
    db.add(member)
    db.commit()
    return {"message": "Family member added", "id": member.id}


@router.delete("/family/{member_id}")
def remove_family_member(
    member_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    member = db.query(FamilyConnection).filter(
        FamilyConnection.id == member_id,
        FamilyConnection.user_id == current_user.id
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Family member not found")
    db.delete(member)
    db.commit()
    return {"message": "Removed"}
