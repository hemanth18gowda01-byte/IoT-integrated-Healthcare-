"""
VitalSync MQTT Service
Bridges MQTT broker → FastAPI database
Topic structure: vitalsync/user/{user_id}/vitals
"""
import asyncio
import json
import logging
import paho.mqtt.client as mqtt
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.models import PatientProfile, VitalReading, HealthAlert, HealthStatus
from app.ml.vitals_model import get_analyzer

settings = get_settings()
logger = logging.getLogger("vitalsync.mqtt")

VITALS_TOPIC = "vitalsync/user/+/vitals"


def on_message(client, userdata, msg):
    """Called when MQTT message arrives. Runs in MQTT thread."""
    try:
        topic_parts = msg.topic.split("/")
        # Topic: vitalsync/user/{device_id}/vitals
        device_id = topic_parts[2]

        payload = json.loads(msg.payload.decode())
        logger.info(f"MQTT received from device {device_id}: {payload}")

        # Process in sync context
        _process_vitals(device_id, payload)

    except Exception as e:
        logger.error(f"MQTT message processing error: {e}")


def _process_vitals(device_id: str, payload: dict):
    """Process incoming IoT vitals and save to DB."""
    db = SessionLocal()
    try:
        # Find patient by device_id
        profile = db.query(PatientProfile).filter(
            PatientProfile.device_id == device_id
        ).first()

        if not profile:
            logger.warning(f"Unknown device_id: {device_id}")
            return

        analyzer = get_analyzer()
        analysis = analyzer.analyze_vitals(payload)

        reading = VitalReading(
            patient_id=profile.id,
            heart_rate=payload.get("heart_rate"),
            spo2=payload.get("spo2"),
            temperature=payload.get("temperature"),
            systolic_bp=payload.get("systolic_bp", 120),
            diastolic_bp=payload.get("diastolic_bp", 80),
            ecg_value=payload.get("ecg_value", 0.5),
            motion_x=payload.get("motion_x", 0),
            motion_y=payload.get("motion_y", 0),
            motion_z=payload.get("motion_z", 9.8),
            fall_detected=payload.get("fall_detected", False),
            source="iot",
            health_status=HealthStatus(analysis["status"]),
            ml_confidence=analysis["confidence"],
            ml_notes=analysis["notes"],
        )
        db.add(reading)

        # Create alert if critical/emergency
        if analysis["status"] in ("critical", "emergency") or analysis["emergency_flags"]:
            alert = HealthAlert(
                patient_id=profile.id,
                alert_type=analysis["emergency_flags"][0] if analysis["emergency_flags"] else analysis["status"].upper(),
                severity=analysis["status"],
                message=analysis["notes"],
                vital_snapshot=payload,
            )
            db.add(alert)

        db.commit()
        logger.info(f"Saved vitals from IoT device {device_id}: {analysis['status']}")

    except Exception as e:
        logger.error(f"DB error processing MQTT vitals: {e}")
        db.rollback()
    finally:
        db.close()


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logger.info("✅ Connected to MQTT broker")
        client.subscribe(VITALS_TOPIC)
        logger.info(f"Subscribed to: {VITALS_TOPIC}")
    else:
        logger.error(f"MQTT connection failed with code {rc}")


def on_disconnect(client, userdata, rc):
    logger.warning(f"MQTT disconnected (rc={rc}). Will auto-reconnect.")


async def start_mqtt_subscriber():
    """Start MQTT subscriber in background (non-blocking)."""
    client = mqtt.Client(client_id="vitalsync-backend")
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    if settings.MQTT_USERNAME:
        client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD)

    try:
        client.connect(settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT, keepalive=60)
        # Run in a thread so it doesn't block asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, client.loop_forever)
    except Exception as e:
        logger.error(f"MQTT connection error: {e}")
