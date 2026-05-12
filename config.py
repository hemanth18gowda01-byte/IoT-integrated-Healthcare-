from pydantic_settings import BaseSettings
from cryptography.fernet import Fernet
from functools import lru_cache
import os


class Settings(BaseSettings):
    # App
    APP_NAME: str = "VitalSync"
    APP_ENV: str = "development"
    DEBUG: bool = True
    FRONTEND_URL: str = "http://localhost:3000"

    # Database
    DATABASE_URL: str = "mysql+pymysql://vitalsync:password@localhost:3306/vitalsync"

    # Security
    SECRET_KEY: str = "change-this-in-production-minimum-32-chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # Encryption
    ENCRYPTION_KEY: str = ""

    # AI
    ANTHROPIC_API_KEY: str = ""

    # MQTT
    MQTT_BROKER_HOST: str = "localhost"
    MQTT_BROKER_PORT: int = 1883
    MQTT_USERNAME: str = "vitalsync"
    MQTT_PASSWORD: str = ""

    # Scheduler
    VITAL_CHECK_INTERVAL: int = 30
    DAILY_CHECKIN_HOUR: int = 20

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


def get_fernet() -> Fernet:
    settings = get_settings()
    key = settings.ENCRYPTION_KEY
    if not key:
        # Generate a key for development (NOT for production)
        key = Fernet.generate_key().decode()
    return Fernet(key.encode() if isinstance(key, str) else key)
