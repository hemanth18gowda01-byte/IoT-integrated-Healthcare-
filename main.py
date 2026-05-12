"""
VitalSync Backend - FastAPI Application
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
import logging

from app.core.config import get_settings
from app.core.database import create_tables
from app.api import auth, patient, hospital, pharmacy
from app.services.alert_service import router as ws_router
from app.ml.vitals_model import get_analyzer

settings = get_settings()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vitalsync")

scheduler = AsyncIOScheduler()


async def daily_checkin_reminder():
    """Sent at 8 PM every day — pushes check-in reminder via WebSocket."""
    from app.services.alert_service import manager
    from app.core.database import SessionLocal
    from app.models.models import PatientProfile

    db = SessionLocal()
    try:
        patients = db.query(PatientProfile).all()
        for p in patients:
            await manager.send_to_user(p.user_id, {
                "type": "checkin_reminder",
                "message": "Time for your daily health check-in! 🩺",
                "timestamp": datetime.utcnow().isoformat(),
            })
        logger.info(f"Daily check-in reminder sent to {len(patients)} patients")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 VitalSync backend starting up...")

    # Create DB tables (use Alembic migrations in production)
    create_tables()
    logger.info("✅ Database tables ready")

    # Pre-load ML models
    get_analyzer()
    logger.info("✅ ML models loaded")

    # Schedule daily check-in at 8 PM
    scheduler.add_job(
        daily_checkin_reminder,
        "cron",
        hour=settings.DAILY_CHECKIN_HOUR,
        minute=0,
        id="daily_checkin"
    )
    scheduler.start()
    logger.info(f"✅ Scheduler started (daily check-in at {settings.DAILY_CHECKIN_HOUR}:00)")

    # Start MQTT subscriber in background
    try:
        from app.services.mqtt_service import start_mqtt_subscriber
        import asyncio
        asyncio.create_task(start_mqtt_subscriber())
        logger.info("✅ MQTT subscriber started")
    except Exception as e:
        logger.warning(f"⚠️  MQTT not started: {e}")

    yield

    # Shutdown
    scheduler.shutdown()
    logger.info("VitalSync backend shut down cleanly")


app = FastAPI(
    title="VitalSync API",
    description="AI-Powered IoT Health Monitoring Platform",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:3000", "http://127.0.0.1:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router)
app.include_router(patient.router)
app.include_router(hospital.router)
app.include_router(pharmacy.router)
app.include_router(ws_router)


@app.get("/")
def root():
    return {
        "name": "VitalSync API",
        "version": "1.0.0",
        "status": "healthy",
        "docs": "/docs",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/health")
def health_check():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
